from calendar import monthrange
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from app.risk.schemas import RiskRules

CENT = Decimal("0.01")
POLICY_VERSION = "demo-rules-1.0"


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def monthly_payment(amount, annual_rate, months):
    rate = Decimal(annual_rate) / 1200
    if not rate:
        return money(Decimal(amount) / months)
    power = (1 + rate) ** months
    return money(Decimal(amount) * rate * power / (power - 1))


def add_months(day, months):
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def schedule(amount, annual_rate, months, start_date):
    payment = monthly_payment(amount, annual_rate, months)
    balance = money(amount)
    rows = []
    for number in range(1, months + 1):
        interest = money(balance * Decimal(annual_rate) / 1200)
        principal = min(balance, money(payment - interest)) if number < months else balance
        balance = money(balance - principal)
        rows.append(
            {
                "number": number,
                "due_date": add_months(start_date, number).isoformat(),
                "payment": str(money(principal + interest)),
                "principal": str(principal),
                "interest": str(interest),
                "balance": str(balance),
            }
        )
    return rows


def business_age(registration_date, today):
    return (
        (today.year - registration_date.year) * 12
        + today.month
        - registration_date.month
        - (today.day < registration_date.day)
    )


def analyze(application, checks, today, policy=None, policy_version=POLICY_VERSION):
    policy = policy or RiskRules()
    weights = policy.weights
    f = application.financials
    p = application.product_snapshot
    fns, bki = checks["fns"], checks["bki"]
    amount = application.amount
    revenue = Decimal(f["annual_revenue"])
    monthly_revenue = revenue / 12
    profit = monthly_revenue - Decimal(f["monthly_expenses"])
    debt_payment = max(Decimal(f["monthly_debt_payments"]), Decimal(bki["monthly_payments"]))
    age = business_age(date.fromisoformat(application.company["registration_date"]), today)
    margin = profit / monthly_revenue
    score = weights.base
    factors = []

    def factor(code, points):
        nonlocal score
        score += points
        factors.append({"code": code, "points": points})

    factor(
        "BUSINESS_AGE",
        weights.age_established
        if age >= 36
        else weights.age_medium
        if age >= 12
        else weights.age_young,
    )
    ratio = revenue / amount
    factor(
        "REVENUE_TO_LOAN",
        weights.revenue_high
        if ratio >= 5
        else weights.revenue_medium
        if ratio >= 2
        else weights.revenue_low,
    )
    factor(
        "PROFIT_MARGIN",
        weights.margin_high
        if margin >= Decimal("0.15")
        else weights.margin_medium
        if margin >= Decimal("0.05")
        else weights.margin_low,
    )
    historical = max(bki["historical_overdue_days"], f["overdue_days"])
    if bki["closed_loans"] >= 3 and historical == 0 and bki["current_overdue_days"] == 0:
        factor("CREDIT_DISCIPLINE", weights.history_clean)
    elif 0 < historical <= 10:
        factor("CREDIT_DISCIPLINE", weights.history_minor_delay)
    elif historical >= 30:
        factor("CREDIT_DISCIPLINE", weights.history_overdue)
    else:
        factor("CREDIT_DISCIPLINE", 0)
    factor(
        "TAX_DISCIPLINE", weights.tax_clean if Decimal(fns["tax_debt"]) == 0 else weights.tax_debt
    )
    score = max(300, min(850, score))
    risk = (
        "CATEGORY_A"
        if score >= policy.category_a_min
        else "CATEGORY_B"
        if score >= policy.category_b_min
        else "CATEGORY_C"
        if score >= policy.category_c_min
        else "REJECT_D"
    )
    reasons = []
    rules = [
        (
            age < max(policy.min_business_age_months, p["min_business_age_months"]),
            "BUSINESS_TOO_YOUNG",
        ),
        (fns["status"] != "active", "COMPANY_NOT_ACTIVE"),
        (fns["account_blocked"], "ACCOUNTS_BLOCKED"),
        (
            max(bki["current_overdue_days"], f["overdue_days"]) > policy.max_current_overdue_days,
            "CURRENT_OVERDUE",
        ),
        (bki["historical_overdue_days"] >= policy.historical_default_days, "HISTORICAL_DEFAULT"),
        (revenue < Decimal(p["min_annual_revenue"]), "INSUFFICIENT_REVENUE"),
        (p["collateral_required"] and not f["has_collateral"], "COLLATERAL_REQUIRED"),
        (profit <= 0, "NON_POSITIVE_PROFIT"),
        (score < policy.category_c_min, "LOW_SCORE"),
    ]
    reasons.extend(code for condition, code in rules if condition)
    rate = Decimal(p["annual_rate"]) + (
        Decimal(0)
        if score >= policy.category_a_min
        else policy.category_b_surcharge
        if score >= policy.category_b_min
        else policy.category_c_surcharge
    )
    approved_amount = money(
        amount * (policy.category_c_limit_factor if risk == "CATEGORY_C" else 1)
    )
    max_burden = min(policy.max_burden, Decimal(p["max_debt_burden"]))
    burden = None
    adjusted = approved_amount != amount
    if profit > 0:
        payment = monthly_payment(approved_amount, rate, application.term_months)
        burden = (debt_payment + payment) / profit
        # Надбавка начисляется один раз; после неё ПДН проверяется повторно.
        if burden > policy.yellow_burden:
            rate += policy.yellow_surcharge
            payment = monthly_payment(approved_amount, rate, application.term_months)
            burden = (debt_payment + payment) / profit
        if burden > max_burden:
            if score >= policy.category_a_min:
                target = min(policy.reduced_limit_target, max_burden)
                available = profit * target - debt_payment
                unit_payment = (
                    monthly_payment(Decimal("1000000"), rate, application.term_months) / 1000000
                )
                approved_amount = max(
                    Decimal(0), min(approved_amount, available / unit_payment)
                ).quantize(CENT, rounding=ROUND_DOWN)
                # Расчёт лимита уточняется бинарным поиском с точным округлением платежа.
                low, high = 0, int(approved_amount * 100)
                while low < high:
                    mid = (low + high + 1) // 2
                    test_burden = (
                        debt_payment
                        + monthly_payment(Decimal(mid) / 100, rate, application.term_months)
                    ) / profit
                    if test_burden <= target:
                        low = mid
                    else:
                        high = mid - 1
                approved_amount = Decimal(low) / 100
                adjusted = True
                burden = (
                    debt_payment + monthly_payment(approved_amount, rate, application.term_months)
                ) / profit
            else:
                reasons.append("DEBT_BURDEN_EXCEEDED")
    if approved_amount < Decimal(p["min_amount"]):
        reasons.append("APPROVED_AMOUNT_BELOW_MINIMUM")
    if burden is not None and burden > max_burden:
        reasons.append("DEBT_BURDEN_EXCEEDED")
    result = {
        "policy_version": policy_version,
        "policy_snapshot": policy.model_dump(mode="json"),
        "demonstration_only": True,
        "outcome": "REJECT" if reasons else "APPROVE",
        "score": score,
        "risk_category": risk,
        "reasons": sorted(set(reasons)),
        "factors": factors,
        "metrics": {
            "business_age_months": age,
            "monthly_net_profit": str(money(profit)),
            "profit_margin": str(margin.quantize(Decimal("0.0001"))),
            "debt_burden": str(burden.quantize(Decimal("0.0001"))) if burden is not None else None,
        },
        "limit_adjusted": adjusted,
    }
    offer = None
    if not reasons:
        rows = schedule(approved_amount, rate, application.term_months, today)
        offer = {
            "amount": str(money(approved_amount)),
            "requested_amount": str(amount),
            "annual_rate": str(rate),
            "term_months": application.term_months,
            "monthly_payment": str(monthly_payment(approved_amount, rate, application.term_months)),
            "total_payment": str(sum((Decimal(row["payment"]) for row in rows), Decimal(0))),
            "schedule": rows,
            "demonstration_only": True,
        }
    return result, offer
