OLD_SLABS = [(250000, 0), (500000, 0.05), (1000000, 0.20), (float("inf"), 0.30)]
NEW_SLABS = [
    (300000, 0),
    (700000, 0.05),
    (1000000, 0.10),
    (1200000, 0.15),
    (1500000, 0.20),
    (float("inf"), 0.30),
]


def calc_tax(income: float, slabs: list) -> float:
    tax, prev = 0.0, 0.0
    income = max(0.0, float(income or 0.0))
    for limit, rate in slabs:
        if income <= prev:
            break
        taxable = min(income, limit) - prev
        tax += taxable * rate
        prev = limit
    return tax * 1.04  # 4% cess


def compare_regimes(gross_income, deductions) -> dict:
    gross_income = max(0.0, float(gross_income or 0.0))
    s80c = min(float(deductions.get("s80c_invested", 0) or 0.0), 150000)
    s_nps = min(float(deductions.get("s_nps_invested", 0) or 0.0), 50000)
    s80d = float(deductions.get("s80d_total", 0) or 0.0)

    old_taxable = max(0.0, gross_income - 75000 - s80c - s_nps - s80d)
    new_taxable = max(0.0, gross_income - 75000)  # standard deduction only

    old_tax = calc_tax(old_taxable, OLD_SLABS)
    new_tax = calc_tax(new_taxable, NEW_SLABS)
    winner = "old" if old_tax < new_tax else "new"

    return {
        "old_tax": old_tax,
        "new_tax": new_tax,
        "recommended": winner,
        "saving": abs(old_tax - new_tax),
    }
