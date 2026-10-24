from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from app.common import Schema


class Purpose(StrEnum):
    WORKING_CAPITAL = "working_capital"
    EQUIPMENT = "equipment"
    EXPANSION = "expansion"
    REFINANCING = "refinancing"


class DocumentKind(StrEnum):
    REGISTRATION = "registration"
    FINANCIAL_STATEMENTS = "financial_statements"
    BANK_STATEMENT = "bank_statement"
    COLLATERAL = "collateral"


class ProductCreate(Schema):
    name: str = Field(min_length=2, max_length=200)
    purposes: list[Purpose] = Field(min_length=1, max_length=4)
    min_amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    max_amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    min_term_months: int = Field(ge=1, le=360)
    max_term_months: int = Field(ge=1, le=360)
    annual_rate: Decimal = Field(ge=0, le=100, decimal_places=2)
    min_business_age_months: int = Field(ge=0, le=1200)
    min_annual_revenue: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    max_debt_burden: Decimal = Field(gt=0, le=1, decimal_places=4)
    collateral_required: bool = False
    required_documents: list[DocumentKind] = Field(min_length=1, max_length=4)
    active: bool = True

    @model_validator(mode="after")
    def valid_ranges(self):
        if self.max_amount < self.min_amount or self.max_term_months < self.min_term_months:
            raise ValueError("maximum must be >= minimum")
        if self.collateral_required and DocumentKind.COLLATERAL not in self.required_documents:
            raise ValueError("collateral document is required for collateral products")
        if len(set(self.required_documents)) != len(self.required_documents):
            raise ValueError("duplicate document kinds")
        return self


class ProductRead(ProductCreate):
    id: str
    demonstration_only: bool
