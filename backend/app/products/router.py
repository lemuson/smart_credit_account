from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.auth.dependencies import Admin, CurrentUser
from app.common import DB
from app.products.schemas import ProductCreate, ProductRead, Purpose
from app.products.service import ProductService
from app.profiles.service import ProfileService

router = APIRouter(prefix="/credit-products", tags=["credit-products"])


@router.get("", response_model=list[ProductRead])
def list_products(
    db: DB, user: CurrentUser, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    return ProductService(db).dao.list(offset, limit)


@router.get("/search", response_model=list[ProductRead])
def search_products(
    request: Request,
    db: DB,
    user: CurrentUser,
    purpose: Purpose | None = None,
    amount: Decimal | None = Query(None, gt=0, max_digits=16, decimal_places=2),
    term_months: int | None = Query(None, ge=1, le=360),
):
    profile = (
        ProfileService(db).get(user.id) if getattr(request.state, "ai_delegated", False) else None
    )
    return ProductService(db).search(purpose, amount, term_months, profile)


@router.post("", response_model=ProductRead, status_code=201)
def create_product(data: ProductCreate, db: DB, user: Admin):
    return ProductService(db).create(data)


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: UUID, db: DB, user: CurrentUser):
    return ProductService(db).get(product_id)


@router.get("/{product_id}/required-documents")
def required_documents(product_id: UUID, db: DB, user: CurrentUser):
    return {
        "product_id": str(product_id),
        "required_documents": ProductService(db).get(product_id).required_documents,
    }


@router.put("/{product_id}", response_model=ProductRead)
def update_product(product_id: UUID, data: ProductCreate, db: DB, user: Admin):
    return ProductService(db).update(product_id, data)
