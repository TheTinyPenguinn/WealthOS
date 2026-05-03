TOOLS = [
    {
        "name": "get_financial_snapshot",
        "description": "Get user live position: liquid NW, monthly burn, surplus, runway",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "simulate_loan",
        "description": "Simulate loan impact on cash flow and runway",
        "parameters": {
            "type": "object",
            "properties": {
                "principal": {"type": "number", "description": "Loan amount INR"},
                "apr": {"type": "number", "description": "Annual rate e.g. 0.09"},
                "tenure_months": {"type": "integer"},
            },
            "required": ["principal", "apr", "tenure_months"],
        },
    },
    {
        "name": "compare_tax_regimes",
        "description": "Old vs new regime comparison. Returns which saves more and by how much.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_capital_gains_summary",
        "description": "LTCG and STCG totals for current FY with tax owed",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_tax_harvesting_alerts",
        "description": "List of tax-loss harvesting + STCG-to-LTCG opportunities",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_insurance_audit",
        "description": "Life + health coverage adequacy + endowment trap detection",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_surplus_allocation",
        "description": "Recommended monthly surplus split: EF, debt, goals, investments",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_80c_gap",
        "description": "Remaining 80C + NPS 80CCD(1B) capacity and potential tax saving",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]
