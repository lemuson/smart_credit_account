from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field, model_validator

from app.applications.models import Status
from app.common import Schema
from app.products.schemas import DocumentKind, Purpose
from app.profiles.schemas import Company, Financials


class ApplicationCreate(Schema):
    product_id: UUID
    purpose: Purpose
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    term_months: int = Field(ge=1, le=360)
    source_loan_id: UUID | None = None


class ApplicationUpdate(Schema):
    expected_version: int = Field(ge=1)
    company: Company | None = None
    financials: Financials | None = None
    purpose: Purpose | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=2)
    term_months: int | None = Field(default=None, ge=1, le=360)

    @model_validator(mode="after")
    def no_explicit_null(self):
        for field in self.model_fields_set - {"expected_version"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class VersionAction(Schema):
    expected_version: int = Field(ge=1)


class Submit(VersionAction):
    confirmed: bool


class ClarificationCreate(VersionAction):
    comment: str = Field(min_length=3, max_length=4000)
    required_fields: list[str] = Field(default_factory=list, max_length=30)
    required_documents: list[DocumentKind] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def known_fields(self):
        allowed = {f"company.{f}" for f in Company.model_fields} | {
            f"financials.{f}" for f in Financials.model_fields
        }
        if not set(self.required_fields) <= allowed:
            raise ValueError("unknown required field")
        return self


class ClarificationReply(VersionAction):
    response: str = Field(min_length=3, max_length=4000)
    confirmed: bool


class ReviewAction(VersionAction):
    comment: str = Field(min_length=3, max_length=4000)


class Sign(VersionAction):
    code: str = Field(pattern=r"^\d{6}$")
    contract_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ApplicationRead(Schema):
    id: str
    client_id: str
    product_id: str
    assigned_manager_id: str | None
    source_loan_id: str | None
    purpose: Purpose
    amount: Decimal
    term_months: int
    status: Status
    company: dict
    financials: dict
    product_snapshot: dict
    data_revision: int
    version: int
    decision: dict | None
    offer: dict | None
    contract: dict | None
    created_at: datetime
    updated_at: datetime


class DocumentRead(Schema):
    id: str
    kind: str
    filename: str
    content_type: str
    sha256: str
    size: int
    created_at: datetime


class CheckRead(Schema):
    id: str
    data_revision: int
    results: dict
    created_at: datetime


class ClarificationRead(Schema):
    id: str
    comment: str
    required_fields: list[str]
    required_documents: list[str]
    response: str | None
    responded_at: datetime | None
    created_at: datetime


class AuditRead(Schema):
    id: str
    actor_id: str | None
    action: str
    from_status: Status | None
    to_status: Status
    details: dict
    created_at: datetime


class ValidationRead(Schema):
    application_id: str
    product_id: str
    valid: bool
    errors: list[dict]
    data_revision: int


class Dossier(ApplicationRead):
    documents: list[DocumentRead]
    checks: list[CheckRead]
    clarifications: list[ClarificationRead]
    history: list[AuditRead]
