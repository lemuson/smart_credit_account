from sqlalchemy import select

from app.loans.models import Loan


class LoanDAO:
    def __init__(self, session):
        self.session = session

    def owned(self, loan_id, client_id):
        return self.session.scalar(
            select(Loan).where(Loan.id == str(loan_id), Loan.client_id == client_id)
        )

    def list(self, client_id, offset=0, limit=50):
        return self.session.scalars(
            select(Loan)
            .where(Loan.client_id == client_id)
            .order_by(Loan.created_at.desc(), Loan.id)
            .offset(offset)
            .limit(limit)
        ).all()

    def active(self, client_id):
        return self.session.scalars(
            select(Loan).where(Loan.client_id == client_id, Loan.status == "active")
        ).all()

    def create(self, **values):
        loan = Loan(**values)
        self.session.add(loan)
        self.session.flush()
        return loan
