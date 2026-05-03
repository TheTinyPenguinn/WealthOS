from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from app.utils.llm_client import call_vision
from app.utils.privacy import sanitise_for_ai

PARSE_PROMPT = """
Extract ALL financial transactions from this image or PDF.
Return ONLY a valid JSON array, no explanation, no markdown.
Each element: {merchant: str, amount: float (positive=expense, negative=credit),
date: str YYYY-MM-DD, currency: str default INR,
category: one of [food transport shopping utilities
entertainment health income other]}
If not a financial document return: []
"""

ALLOWED_CATEGORIES = {
    "food",
    "transport",
    "shopping",
    "utilities",
    "entertainment",
    "health",
    "income",
    "other",
}


def _sanitised_hint(file_bytes: bytes) -> str:
    # Privacy-first best effort redaction before sending prompt context to AI.
    preview = file_bytes[:5000].decode("utf-8", errors="ignore")
    return sanitise_for_ai(preview)[:3000]


def _safe_json_array(raw: str):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _normalize_txn(row: dict) -> dict | None:
    try:
        merchant = str(row.get("merchant", "")).strip() or "Unknown"
        amount = float(row.get("amount", 0.0))
        raw_date = str(row.get("date", "")).strip()
        try:
            date = datetime.fromisoformat(raw_date).date().isoformat()
        except Exception:
            date = datetime.utcnow().date().isoformat()

        currency = str(row.get("currency", "INR")).strip().upper() or "INR"
        category = str(row.get("category", "other")).strip().lower()
        if category not in ALLOWED_CATEGORIES:
            category = "other"
        return {
            "merchant": merchant,
            "amount": amount,
            "date": date,
            "currency": currency,
            "category": category,
        }
    except Exception:
        return None


def parse_file(file_bytes: bytes, mime_type: str, user_id: str, supabase) -> list[dict]:
    storage_path = f"receipts/{user_id}/{uuid4()}.tmp"
    parsed: list[dict] = []
    try:
        supabase.storage.from_("receipts").upload(storage_path, file_bytes)

        prompt = PARSE_PROMPT + "\n\nSanitised text preview:\n" + _sanitised_hint(file_bytes)
        raw = call_vision(
            prompt=prompt,
            image_bytes=file_bytes,
            mime_type=mime_type or "application/octet-stream",
            provider="openai",
        )
        arr = _safe_json_array(raw)
        for item in arr:
            if isinstance(item, dict):
                norm = _normalize_txn(item)
                if norm:
                    parsed.append(norm)
    except Exception:
        parsed = []
    finally:
        try:
            supabase.storage.from_("receipts").remove([storage_path])
        except Exception:
            pass
    return parsed


def confirm_and_save(transactions: list, user_id: str, supabase) -> int:
    rows = [{**t, "user_id": user_id, "source": "ocr"} for t in transactions]
    if not rows:
        return 0
    supabase.table("transactions").insert(rows).execute()
    return len(rows)
