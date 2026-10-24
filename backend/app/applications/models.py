from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, FixedDecimal, UTCDateTime, new_id, now


class Status(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PRIMARY_REVIEW = "PRIMARY_REVIEW"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    AUTOMATIC_ANALYSIS = "AUTOMATIC_ANALYSIS"
    OFFER_READY = "OFFER_READY"
    REJECTED = "REJECTED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_DECLINED = "OFFER_DECLINED"
    SIGNING = "SIGNING"
    DISBURSED = "DISBURSED"


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("credit_products.id"))
    assigned_manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    source_loan_id: Mapped[str | None] = mapped_column(ForeignKey("loans.id"))
    purpose: Mapped[str] = mapped_column(String(50))
    amount: Mapped[Decimal] = mapped_column(FixedDecimal(2))
    term_months: Mapped[int]
    status: Mapped[str] = mapped_column(String(30), default=Status.DRAFT, index=True)
    company: Mapped[dict] = mapped_column(JSON, default=dict)
    financials: Mapped[dict] = mapped_column(JSON, default=dict)
    product_snapshot: Mapped[dict] = mapped_column(JSON)
    data_revision: Mapped[int] = mapped_column(default=1)
    version: Mapped[int] = mapped_column(default=1)
    decision: Mapped[dict | None] = mapped_column(JSON)
    offer: Mapped[dict | None] = mapped_column(JSON)
    contract: Mapped[dict | None] = mapped_column(JSON)
    signing_code_hash: Mapped[str | None] = mapped_column(String(255))
    signing_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    signing_attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now, onupdate=now)
    __mapper_args__ = {"version_id_col": version}


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class CheckRun(Base):
    __tablename__ = "check_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    data_revision: Mapped[int]
    results: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class Clarification(Base):
    __tablename__ = "clarifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str] = mapped_column(Text)
    required_fields: Mapped[list] = mapped_column(JSON)
    required_documents: Mapped[list] = mapped_column(JSON)
    response: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
