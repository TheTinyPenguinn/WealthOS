"""
Parse Indian bank exports and WealthOS CSV exports (date / description / amount / category).
Pure functions — no Streamlit — so we can regression-test imports.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Optional, Tuple

import pandas as pd


def clean_numeric(value) -> float:
    if pd.isna(value):
        return 0.0
    try:
        cleaned = str(value).replace(",", "").replace(" ", "").strip()
        if cleaned in ("", "-", "—"):
            return 0.0
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _detect_sep(line: str) -> str:
    line = line.lstrip("\ufeff")
    counts = {",": line.count(","), ";": line.count(";"), "\t": line.count("\t")}
    best = max(counts, key=counts.get)
    if counts[best] > 0:
        return best
    try:
        return csv.Sniffer().sniff(line, delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def _header_score(line: str) -> int:
    """Higher = more likely to be a transaction header row."""
    l = line.lstrip("\ufeff").strip().lower()
    if not l:
        return 0
    # Need at least one amount-like concept
    amount_hints = (
        "amount",
        " amt",
        ",amt",
        "\tamt",
        "debit",
        "credit",
        "withdrawal",
        "deposit",
        "withdraw",
        "paid in",
        "paid out",
    )
    if not any(h in l for h in amount_hints):
        return 0
    score = 3
    if "transaction date" in l or "txn date" in l:
        score += 4
    elif l.startswith("date") or re.search(r"(^|[,;\t])date([,;\t]|$)", l):
        score += 3
    elif "date" in l:
        score += 2
    if any(
        x in l
        for x in (
            "description",
            "narration",
            "particular",
            "details",
            "remarks",
            "payee",
            "merchant",
        )
    ):
        score += 2
    if "category" in l:
        score += 1
    return score


def _pick_date_column(columns: list) -> Optional[str]:
    """Choose a single date column; avoid duplicate 'Date' renames."""
    candidates: list[tuple[int, str]] = []
    for col in columns:
        c = str(col).lower().strip()
        if "date" not in c or "value" in c:
            continue
        pri = 0
        if "transaction" in c or "txn" in c:
            pri = 40
        elif c in ("date", "dt", "posting date"):
            pri = 30
        elif "posting" in c or "book" in c:
            pri = 20
        else:
            pri = 10
        candidates.append((pri, col))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def _pick_amount_column(columns: list) -> Optional[str]:
    for col in columns:
        c = str(col).lower().strip()
        if c in ("amount", "amt") or c.endswith(" amount") or c.endswith(" amt"):
            return col
    return None


def _withdrawal_deposit_columns(columns: list) -> tuple[Optional[str], Optional[str]]:
    wcol = dcol = None
    for col in columns:
        c = str(col).lower().strip()
        if any(x in c for x in ("withdrawal", "withdraw", "debit", "dr amt", "dr amount")):
            wcol = col
        if any(x in c for x in ("deposit", "credit", "cr amt", "cr amount")):
            dcol = col
    return wcol, dcol


def parse_bank_statement_csv_from_bytes(raw: bytes) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Returns (dataframe, error_message). DataFrame columns: Date, Description, Amount, Category.
    """
    content = _decode_bytes(raw)
    lines = [ln.strip("\r") for ln in content.splitlines()]

    header_idx = -1
    best = 0
    scan = min(len(lines), 200)
    for i in range(scan):
        s = _header_score(lines[i])
        if s > best:
            best = s
            header_idx = i

    # WealthOS-style: date + amount can score 3+3+2(desc)+1 = 9; minimal bank: 3+2(date)+2 = 7
    if header_idx == -1 or best < 6:
        return None, (
            "Could not find a valid header row. Need a row with a **date** column and an **amount** "
            "(or debit/credit / withdrawal / deposit). WealthOS export: `date, description, amount, category`."
        )

    sep = _detect_sep(lines[header_idx])
    # Slice from detected header so pandas header=0 matches (avoids blank-line / preamble skew).
    body = "\n".join(lines[header_idx:]).lstrip("\ufeff")
    try:
        df = pd.read_csv(
            io.StringIO(body),
            header=0,
            dtype=str,
            sep=sep,
            engine="python",
            on_bad_lines="skip",
        )
    except Exception as e:
        return None, f"Could not read CSV: {e}"

    # Normalize column labels (strip BOM/spaces)
    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]

    date_col = _pick_date_column(list(df.columns))
    amount_col = _pick_amount_column(list(df.columns))
    wcol, dcol = _withdrawal_deposit_columns(list(df.columns))

    col_map: dict = {}
    if date_col:
        col_map[date_col] = "Date"

    desc_col = None
    for col in df.columns:
        c = str(col).lower().strip()
        if "description" in c or "narration" in c or "particular" in c:
            desc_col = col
            break
    if desc_col is None:
        for col in df.columns:
            c = str(col).lower().strip()
            if any(x in c for x in ("details", "remarks", "payee", "merchant")):
                desc_col = col
                break
    if desc_col is not None:
        col_map[desc_col] = "Description"

    if amount_col:
        col_map[amount_col] = "Amount"

    type_col = None
    for col in df.columns:
        c = str(col).lower().strip()
        if "dr" in c and "cr" in c and "balance" not in c:
            type_col = col
            break

    for col in df.columns:
        c = str(col).lower().strip()
        if "category" in c:
            col_map[col] = "Category"

    df = df.rename(columns=col_map)

    # Build amount from withdrawal + deposit if there is no single Amount column
    if "Amount" not in df.columns:
        if wcol is not None and dcol is not None:

            def _from_withdraw_deposit(row: pd.Series) -> float:
                dr = clean_numeric(row[wcol]) if wcol in row.index else 0.0
                cr = clean_numeric(row[dcol]) if dcol in row.index else 0.0
                if cr != 0.0 and dr != 0.0:
                    return cr - dr
                if cr != 0.0:
                    return abs(cr)
                if dr != 0.0:
                    return -abs(dr)
                return 0.0

            df["Amount"] = df.apply(_from_withdraw_deposit, axis=1)
        elif wcol is not None:
            df["Amount"] = df[wcol].map(lambda x: -abs(clean_numeric(x)))
        elif dcol is not None:
            df["Amount"] = df[dcol].map(lambda x: abs(clean_numeric(x)))

    if "Date" not in df.columns or "Amount" not in df.columns:
        return None, (
            "After reading the file, **Date** and **Amount** columns were not found. "
            "Check spelling (e.g. `date`, `Transaction Date`, `amount`, or separate debit/credit columns)."
        )

    if "Description" not in df.columns:
        df["Description"] = "Unknown"

    def _coerce_transaction_dates(s: pd.Series) -> pd.Series:
        raw = s.astype(str).str.strip()
        out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
        iso_like = raw.str.match(r"^\d{4}-\d{1,2}-\d{1,2}", na=False)
        out.loc[iso_like] = pd.to_datetime(raw.loc[iso_like], errors="coerce")
        rest = ~iso_like
        if rest.any():
            out.loc[rest] = pd.to_datetime(raw.loc[rest], dayfirst=True, errors="coerce")
        return out

    df["Date"] = _coerce_transaction_dates(df["Date"])
    df = df.dropna(subset=["Date"])

    df["Amount"] = df["Amount"].apply(clean_numeric)
    if type_col and type_col in df.columns:
        def _sign(row):
            amt = float(row["Amount"])
            txn = str(row[type_col]).upper().strip()
            if "DR" in txn:
                return -abs(amt)
            if "CR" in txn:
                return abs(amt)
            return amt

        df["Amount"] = df.apply(_sign, axis=1)

    df["Description"] = df["Description"].fillna("Unknown").astype(str)
    ignore_keywords = ["sweep", "fd premat", "fd maturity", "auto trf"]
    pattern = "|".join(ignore_keywords)
    df = df[~df["Description"].str.contains(pattern, case=False, na=False)]

    if "Category" in df.columns:
        df["Category"] = df["Category"].fillna("Needs").astype(str).str.strip()
        df["Category"] = df["Category"].replace(
            {
                "needs": "Needs",
                "wants": "Wants",
                "financial": "Financial",
                "income": "Income",
                "asset": "Asset",
                "one-time": "One-Time",
                "one time": "One-Time",
            }
        )
    else:
        df["Category"] = "Needs"

    df = df.dropna(subset=["Date", "Amount"])
    # Drop rows where amount is zero and description empty-ish (often footers)
    df = df[~((df["Amount"].abs() < 1e-9) & (df["Description"].str.len() < 2))]

    if df.empty:
        return None, (
            "No valid transaction rows after parsing. Check date format (day/month/year) and numeric amounts."
        )

    out = df[["Date", "Description", "Amount", "Category"]].reset_index(drop=True)
    return out, None
