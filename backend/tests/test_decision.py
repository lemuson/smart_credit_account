from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import company, financials

from app.applications.decision import analyze, business_age, monthly_payment, schedule


def snapshot(**overrides):
    return SimpleNamespace(
        amount=Decimal("1000000"),
        term_months=24,
        company=company(),
        financials=financials(),
        product_snapshot={
            "min_business_age_months": 6,
            "min_annual_revenue": "300000",
            "collateral_required": False,
            "annual_rate": "18",
            "max_debt_burden": "0.70",
            "min_amount": "100000",
        },
        **overrides,
    )


def checks(**overrides):
    return {
        "fns": {"status": "active", "account_blocked": False, "tax_debt": "0"},
        "bki": {
            "closed_loans": 4,
            "historical_overdue_days": 0,
            "current_overdue_days": 0,
            "monthly_payments": "0",
        },
        **overrides,
    }


@pytest.mark.parametrize("rate", ["0", "18", "100"])
@pytest.mark.parametrize("months", [1, 6, 24, 360])
def test_schedule_exact_principal_and_rounding(rate, months):
    rows = schedule(Decimal("123456.78"), Decimal(rate), months, date(2024, 1, 31))
    assert rows[0]["due_date"] == "2024-02-29"
    assert rows[-1]["balance"] == "0.00"
    assert sum(Decimal(row["principal"]) for row in rows) == Decimal("123456.78")
    assert all(Decimal(row["principal"]) >= 0 and Decimal(row["interest"]) >= 0 for row in rows)
    assert all(
        Decimal(row["payment"]) == Decimal(row["principal"]) + Decimal(row["interest"])
        for row in rows
    )


def test_zero_interest_and_calendar_age():
    assert monthly_payment(Decimal("120000"), Decimal(0), 12) == Decimal("10000")
    assert business_age(date(2026, 4, 25), date(2026, 10, 24)) == 5
    assert business_age(date(2026, 4, 24), date(2026, 10, 24)) == 6


def test_high_score_reduces_limit_to_65_percent():
    app = snapshot()
    app.financials = financials(monthly_expenses="1950000")
    decision, offer = analyze(app, checks(), date(2026, 10, 24))
    assert decision["score"] == 700  # Low margin moves this borrower to category B.
    assert offer is None and "DEBT_BURDEN_EXCEEDED" in decision["reasons"]
    app.financials = financials(monthly_debt_payments="1450000")
    decision, offer = analyze(app, checks(), date(2026, 10, 24))
    assert decision["score"] == 830
    assert offer is None  # Existing payment alone exceeds the target.
    app.financials = financials(monthly_debt_payments="950000")
    decision, offer = analyze(app, checks(), date(2026, 10, 24))
    # Requested payment is still below 70%, so this is the yellow zone with rate surcharge.
    assert offer and Decimal(offer["annual_rate"]) == Decimal("19.5")
    app.financials = financials(annual_revenue="12000000", monthly_debt_payments="310000")
    decision, offer = analyze(app, checks(), date(2026, 10, 24))
    assert offer and decision["limit_adjusted"]
    assert Decimal(offer["amount"]) < Decimal("1000000")
    assert Decimal(decision["metrics"]["debt_burden"]) <= Decimal("0.65")


def test_category_c_limit_and_rate():
    app = snapshot()
    app.company["registration_date"] = "2026-01-01"
    external = checks()
    external["bki"]["closed_loans"] = 0
    external["fns"]["tax_debt"] = "18500"
    decision, offer = analyze(app, external, date(2026, 10, 24))
    assert decision["score"] == 580
    assert decision["risk_category"] == "CATEGORY_C"
    assert offer["amount"] == "700000.00" and offer["annual_rate"] == "21.5"


@pytest.mark.parametrize("age,expected", [("2026-05-01", True), ("2026-04-24", False)])
def test_six_month_stop_boundary(age, expected):
    app = snapshot()
    app.company["registration_date"] = age
    decision, _ = analyze(app, checks(), date(2026, 10, 24))
    assert ("BUSINESS_TOO_YOUNG" in decision["reasons"]) == expected


def test_negative_profit_and_collateral_stop():
    app = snapshot()
    app.financials = financials(monthly_expenses="2500000")
    app.product_snapshot["collateral_required"] = True
    decision, offer = analyze(app, checks(), date(2026, 10, 24))
    assert offer is None and {"NON_POSITIVE_PROFIT", "COLLATERAL_REQUIRED"} <= set(
        decision["reasons"]
    )


def test_score_690_requires_acceptable_debt_burden():
    app = snapshot()
    app.financials = financials(annual_revenue="3000000", monthly_expenses="50000")
    external = checks()
    external["bki"]["closed_loans"] = 0
    decision, offer = analyze(app, external, date(2026, 10, 24))
    assert decision["score"] == 690
    assert offer and decision["outcome"] == "APPROVE"
    app.financials["monthly_debt_payments"] = "200000"
    decision, offer = analyze(app, external, date(2026, 10, 24))
    assert decision["score"] == 690
    assert offer is None and decision["reasons"] == ["DEBT_BURDEN_EXCEEDED"]
