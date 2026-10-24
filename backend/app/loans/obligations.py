from decimal import Decimal

from app.loans.dao import LoanDAO

EXTERNAL_FIELDS = ("monthly_debt_payments", "outstanding_debt")


def credit_obligations(session, client_id, financials):
    loans = LoanDAO(session).active(client_id)
    bank_payment = sum((loan.monthly_payment for loan in loans), Decimal(0))
    bank_debt = sum((loan.outstanding_balance for loan in loans), Decimal(0))
    external_payment = Decimal(financials.get("monthly_debt_payments") or "0")
    external_debt = Decimal(financials.get("outstanding_debt") or "0")
    return {
        "bank_monthly_payments": str(bank_payment),
        "external_monthly_payments": str(external_payment),
        "total_monthly_payments": str(bank_payment + external_payment),
        "bank_outstanding_debt": str(bank_debt),
        "external_outstanding_debt": str(external_debt),
        "total_outstanding_debt": str(bank_debt + external_debt),
    }
