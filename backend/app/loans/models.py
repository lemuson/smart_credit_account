from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, FixedDecimal, UTCDateTime, new_id, now


class Loan(Base):
    __tablename__ = "loans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", use_alter=True, name="fk_loans_application_id_applications"),
        unique=True,
    )
    external_reference: Mapped[str | None] = mapped_column(String(100), unique=True)
    amount: Mapped[Decimal] = mapped_column(FixedDecimal(2))
    outstanding_balance: Mapped[Decimal] = mapped_column(FixedDecimal(2))
    monthly_payment: Mapped[Decimal] = mapped_column(FixedDecimal(2))
    term_months: Mapped[int]
    annual_rate: Mapped[Decimal] = mapped_column(FixedDecimal(2))
    status: Mapped[str] = mapped_column(String(20), default="active")
    overdue_days: Mapped[int] = mapped_column(default=0)
    company_snapshot: Mapped[dict] = mapped_column(JSON)
    financials_snapshot: Mapped[dict] = mapped_column(JSON)
    demonstration_only: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
