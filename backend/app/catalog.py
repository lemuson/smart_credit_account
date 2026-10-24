from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field

from app.applications.decision import monthly_payment, schedule
from app.auth.dependencies import CurrentUser
from app.common import DB, Schema, fail
from app.products.schemas import ProductRead, Purpose
from app.products.service import ProductService

router = APIRouter(prefix="/catalog", tags=["catalog"])


class Preview(Schema):
    product_id: UUID
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    term_months: int = Field(ge=1, le=360)


@router.get("/products", response_model=list[ProductRead])
def catalog(
    db: DB,
    user: CurrentUser,
    purpose: Purpose | None = None,
    amount: Decimal | None = Query(None, gt=0, max_digits=16, decimal_places=2),
    term_months: int | None = Query(None, ge=1, le=360),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    service = ProductService(db)
    if purpose is not None and amount is not None and term_months is not None:
        return service.search(purpose, amount, term_months)[offset : offset + limit]
    if any(value is not None for value in (purpose, amount, term_months)):
        fail(422, "ALL_SEARCH_PARAMETERS_REQUIRED")
    return service.dao.list(offset, limit)


@router.post("/calculate-preview")
def preview(data: Preview, db: DB, user: CurrentUser):
    product = ProductService(db).get(data.product_id)
    if (
        not product.active
        or not product.min_amount <= data.amount <= product.max_amount
        or not product.min_term_months <= data.term_months <= product.max_term_months
    ):
        fail(422, "PRODUCT_PARAMETERS_OUT_OF_RANGE")
    return {
        "demonstration_only": True,
        "amount": str(data.amount),
        "annual_rate": str(product.annual_rate),
        "monthly_payment": str(monthly_payment(data.amount, product.annual_rate, data.term_months)),
        "schedule": schedule(data.amount, product.annual_rate, data.term_months, date.today()),
    }
