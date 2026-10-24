from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from app.common import Schema

Money = Decimal


class Company(Schema):
    name: str = Field(min_length=1, max_length=250)
    inn: str = Field(pattern=r"^(\d{10}|\d{12})$")
    registration_date: date
    address: str = Field(min_length=3, max_length=500)
    industry: str = Field(min_length=2, max_length=100)

    @field_validator("registration_date")
    @classmethod
    def not_future(cls, value):
        if value > date.today():
            raise ValueError("registration_date cannot be in the future")
        return value

    @field_validator("inn")
    @classmethod
    def valid_inn(cls, value):
        def digit(weights):
            return str(sum(int(n) * w for n, w in zip(value, weights, strict=False)) % 11 % 10)

        if len(value) == 10:
            valid = value[-1] == digit([2, 4, 10, 3, 5, 9, 4, 6, 8])
        else:
            valid = value[-2] == digit([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) and value[-1] == digit(
                [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
            )
        if not valid or len(set(value)) == 1:
            raise ValueError("invalid INN checksum")
        return value


class Financials(Schema):
    annual_revenue: Money = Field(gt=0, max_digits=16, decimal_places=2)
    monthly_expenses: Money = Field(ge=0, max_digits=16, decimal_places=2)
    monthly_debt_payments: Money = Field(ge=0, max_digits=16, decimal_places=2)
    outstanding_debt: Money = Field(ge=0, max_digits=16, decimal_places=2)
    credit_history: Literal["good", "average", "bad", "none"]
    overdue_days: int = Field(ge=0, le=3650)
    has_collateral: bool


class ExternalLiabilities(Schema):
    monthly_debt_payments: Money = Field(ge=0, max_digits=16, decimal_places=2)
    outstanding_debt: Money = Field(ge=0, max_digits=16, decimal_places=2)


class ProfileUpdate(Schema):
    company: Company
    financials: Financials | None = None
    external_liabilities: ExternalLiabilities | None = None


class ProfileRead(Schema):
    id: str
    user_id: str
    company: dict
    financials: dict
    updated_at: datetime
    version: int
    credit_obligations: dict[str, str] = Field(default_factory=dict)
