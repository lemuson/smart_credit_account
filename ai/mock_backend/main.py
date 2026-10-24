from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from mock_backend.data import APPLICATIONS, PRODUCTS, PROFILES

app = FastAPI(
    title="AI Service Mock Main Backend",
    version="1.0.0",
    description="Synthetic read-only API for AI Service development. No real bank data.",
)


class Identity:
    def __init__(self, user_id: UUID, organization_id: UUID) -> None:
        self.user_id = user_id
        self.organization_id = organization_id


async def require_identity(
    authorization: Annotated[str | None, Header()] = None,
    x_service_token: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[UUID | None, Header()] = None,
    x_organization_id: Annotated[UUID | None, Header()] = None,
) -> Identity:
    if authorization != "Bearer demo-user-token" or x_service_token != "development-service-token":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid demo credentials")
    if x_user_id is None or x_organization_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Trusted identity headers are required")
    profile = PROFILES.get(x_user_id)
    if profile is None or profile["organization_id"] != str(x_organization_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Identity does not match organization")
    return Identity(x_user_id, x_organization_id)


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/profile", tags=["profile"])
async def profile(identity: Annotated[Identity, Depends(require_identity)]) -> dict:
    return PROFILES[identity.user_id]


@app.get("/api/v1/credit-products/search", tags=["products"])
async def search_products(
    identity: Annotated[Identity, Depends(require_identity)],
    purpose: str | None = Query(default=None, max_length=200),
    amount: Decimal | None = Query(default=None, gt=0),
    term_months: int | None = Query(default=None, ge=1, le=240),
) -> dict[str, list[dict]]:
    profile_data = PROFILES[identity.user_id]
    items = []
    for product in PRODUCTS.values():
        reasons: list[str] = []
        if profile_data["legal_form"] not in product["legal_forms"]:
            reasons.append("Не поддерживается организационно-правовая форма")
        if profile_data["business_age_months"] < product["min_business_age_months"]:
            reasons.append("Недостаточный срок ведения бизнеса")
        if amount is not None and not (
            Decimal(product["min_amount"]) <= amount <= Decimal(product["max_amount"])
        ):
            reasons.append("Запрошенная сумма вне диапазона продукта")
        if term_months is not None and not (
            product["min_term_months"] <= term_months <= product["max_term_months"]
        ):
            reasons.append("Запрошенный срок вне диапазона продукта")
        purpose_match = purpose is None or any(
            word in purpose.casefold() or purpose.casefold() in word for word in product["purpose"]
        )
        if purpose is not None and not purpose_match:
            reasons.append("Цель не соответствует назначению продукта")
        if not reasons:
            items.append(
                {
                    "product_id": product["product_id"],
                    "name": product["name"],
                    "annual_rate_percent": product["annual_rate_percent"],
                    "min_amount": product["min_amount"],
                    "max_amount": product["max_amount"],
                    "min_term_months": product["min_term_months"],
                    "max_term_months": product["max_term_months"],
                    "match_reasons": ["Соответствует заданным формальным параметрам"],
                    "is_demo": True,
                }
            )
    return {"items": items}


@app.get("/api/v1/credit-products/{product_id}", tags=["products"])
async def product_details(
    product_id: str, _: Annotated[Identity, Depends(require_identity)]
) -> dict:
    product = PRODUCTS.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


@app.get("/api/v1/credit-products/{product_id}/required-documents", tags=["products"])
async def required_documents(
    product_id: str, _: Annotated[Identity, Depends(require_identity)]
) -> dict[str, list[dict]]:
    product = PRODUCTS.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return {"items": product["required_documents"]}


def owned_application(application_id: UUID, identity: Identity) -> dict:
    application = APPLICATIONS.get(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if application["organization_id"] != str(identity.organization_id):
        # 404 avoids confirming that another organization's record exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return application


@app.get("/api/v1/applications/{application_id}/status", tags=["applications"])
async def application_status(
    application_id: UUID, identity: Annotated[Identity, Depends(require_identity)]
) -> dict:
    application = owned_application(application_id, identity)
    return {
        key: application[key]
        for key in ("application_id", "status", "status_label", "next_action", "is_demo")
    }


@app.post("/api/v1/applications/{application_id}/validate", tags=["applications"])
async def validate_application(
    application_id: UUID, identity: Annotated[Identity, Depends(require_identity)]
) -> dict:
    application = owned_application(application_id, identity)
    product = PRODUCTS[application["product_id"]]
    issues = []
    if application["fields"].get("term_months") is None:
        issues.append(
            {
                "code": "missing_term_months",
                "field": "term_months",
                "message": "Укажите срок кредита",
            }
        )
    required = {item["code"] for item in product["required_documents"] if item["required"]}
    for code in sorted(required - set(application["documents"])):
        issues.append(
            {
                "code": "missing_document",
                "field": "documents",
                "message": f"Не загружен обязательный документ: {code}",
            }
        )
    return {
        "application_id": str(application_id),
        "valid": not issues,
        "issues": issues,
        "decision": None,
        "is_demo": True,
    }
