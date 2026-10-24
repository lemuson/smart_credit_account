from sqlalchemy import select

from app.auth.dao import UserDAO
from app.auth.models import Role
from app.common import fail
from app.loans.dao import LoanDAO
from app.loans.models import Loan


class LoanService:
    def __init__(self, session):
        self.session = session
        self.dao = LoanDAO(session)

    def get(self, loan_id, client_id):
        loan = self.dao.owned(loan_id, client_id)
        if not loan:
            fail(404, "LOAN_NOT_FOUND")
        return loan

    def import_loan(self, data):
        user = UserDAO(self.session).get(str(data.client_id))
        if not user or user.role != Role.CLIENT:
            fail(404, "CLIENT_NOT_FOUND")
        if self.session.scalar(
            select(Loan).where(Loan.external_reference == data.external_reference)
        ):
            fail(409, "LOAN_ALREADY_IMPORTED")
        values = data.model_dump()
        values["client_id"] = str(data.client_id)
        values["company_snapshot"] = data.company_snapshot.model_dump(mode="json")
        values["financials_snapshot"] = data.financials_snapshot.model_dump(mode="json")
        return self.dao.create(**values)
