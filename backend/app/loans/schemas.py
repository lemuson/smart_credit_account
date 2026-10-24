from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.common import Schema
from app.profiles.schemas import Company, Financials


class LoanImport(Schema):
    client_id: UUID
    external_reference: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    outstanding_balance: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    monthly_payment: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    term_months: int = Field(ge=1, le=360)
    annual_rate: Decimal = Field(ge=0, le=100, decimal_places=2)
    status: Literal["active", "closed"]
    overdue_days: int = Field(ge=0, le=3650)
    company_snapshot: Company
    financials_snapshot: Financials

    @model_validator(mode="after")
    def balances(self):
        if self.outstanding_balance > self.amount:
            raise ValueError("balance exceeds principal")
        if self.status == "closed" and (
            self.outstanding_balance or self.monthly_payment or self.overdue_days
        ):
            raise ValueError("closed loan must have zero balance, payment and overdue days")
        if self.status == "active" and (not self.monthly_payment or not self.outstanding_balance):
            raise ValueError("active loan needs positive balance and payment")
        return self


class LoanRead(Schema):
    id: str
    client_id: str
    application_id: str | None
    external_reference: str | None
    amount: Decimal
    outstanding_balance: Decimal
    monthly_payment: Decimal
    term_months: int
    annual_rate: Decimal
    status: str
    overdue_days: int
    company_snapshot: dict
    financials_snapshot: dict
    demonstration_only: bool
    created_at: datetime
