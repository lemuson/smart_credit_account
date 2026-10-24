from uuid import UUID

from fastapi import APIRouter, Query

from app.auth.dependencies import Client, Manager
from app.common import DB
from app.loans.schemas import LoanImport, LoanRead
from app.loans.service import LoanService

router = APIRouter(tags=["loans"])


@router.get("/client/loans", response_model=list[LoanRead])
def list_loans(
    db: DB, user: Client, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    return LoanService(db).dao.list(user.id, offset, limit)


@router.get("/client/loans/{loan_id}", response_model=LoanRead)
def get_loan(loan_id: UUID, db: DB, user: Client):
    return LoanService(db).get(loan_id, user.id)


@router.post("/bank/loans/import", response_model=LoanRead, status_code=201)
def import_loan(data: LoanImport, db: DB, user: Manager):
    return LoanService(db).import_loan(data)
