from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, FixedDecimal, UTCDateTime, new_id, now


class Product(Base):
    __tablename__ = "credit_products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    purposes: Mapped[list] = mapped_column(JSON)
    min_amount: Mapped[Decimal] = mapped_column(FixedDecimal(2))
    max_amount: Mapped[Decimal] = mapped_column(FixedDecimal(2))
    min_term_months: Mapped[int]
    max_term_months: Mapped[int]
    annual_rate: Mapped[Decimal] = mapped_column(FixedDecimal(2))
    min_business_age_months: Mapped[int]
    min_annual_revenue: Mapped[Decimal] = mapped_column(FixedDecimal(2))
    max_debt_burden: Mapped[Decimal] = mapped_column(FixedDecimal(4))
    collateral_required: Mapped[bool]
    required_documents: Mapped[list] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)
    demonstration_only: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
