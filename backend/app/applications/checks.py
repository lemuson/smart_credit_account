from app.database import now
from app.loans.dao import LoanDAO
from app.loans.obligations import credit_obligations
from app.profiles.service import ProfileService


def simulated_checks(application, session):
    """Детерминированные учебные источники; не обращаются в ФНС и БКИ."""
    suffix = int(application.company["inn"][-2:])
    adverse = suffix >= 90
    warning = 80 <= suffix <= 89
    loans = LoanDAO(session).active(application.client_id)
    obligations = credit_obligations(
        session,
        application.client_id,
        ProfileService(session).get(application.client_id).financials,
    )
    overdue = max([loan.overdue_days for loan in loans] + [90 if adverse else 0])
    return {
        "provider": "deterministic_demo_v1",
        "demonstration_only": True,
        "checked_at": now().isoformat(),
        "fns": {
            "status": "liquidation" if adverse else "active",
            "account_blocked": adverse,
            "tax_debt": "18500.00" if warning else "0.00",
            "registration_date": application.company["registration_date"],
            "director_match": True,
            "director_match_basis": "simulated; director identity not verified",
        },
        "bki": {
            "closed_loans": 2 if warning or adverse else 4,
            "current_overdue_days": overdue,
            "historical_overdue_days": 90 if adverse else 3 if warning else 0,
            "monthly_payments": obligations["total_monthly_payments"],
            "outstanding_debt": obligations["total_outstanding_debt"],
            **obligations,
            "source": "synthetic_fixture_and_local_loan_records",
        },
        # Сведения о других банках заявлены в профиле, а не сверяются с кредитами нашего банка.
        "discrepancies": [],
    }
