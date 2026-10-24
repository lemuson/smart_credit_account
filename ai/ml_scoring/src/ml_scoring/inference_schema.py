"""Typed contracts for local credit-scoring inference."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

import pandas as pd
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

from .features import FEATURE_COLUMNS

SCHEMA_VERSION = "1.0"
CreditHistory = Literal["good", "average", "bad", "none"]
LoanTerm = Literal[6, 12, 18, 24, 36, 48, 60]


class CreditApplication(BaseModel):
    """One application with strict types and no undeclared fields."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    annual_revenue: Annotated[StrictFloat, Field(gt=0)]
    credit_history: CreditHistory
    business_age_months: Annotated[StrictInt, Field(ge=0)]
    loan_amount: Annotated[StrictFloat, Field(gt=0)]
    has_collateral: StrictBool
    loan_term_months: LoanTerm
    age: Annotated[StrictInt, Field(ge=18, le=70)] | None = None

    @model_validator(mode="after")
    def validate_age_against_business_age(self) -> CreditApplication:
        if self.age is not None:
            minimum_age = 18 + math.ceil(self.business_age_months / 12)
            if self.age < minimum_age:
                raise ValueError(
                    "age is inconsistent with business_age_months: "
                    f"expected at least {minimum_age}"
                )
        return self

    def to_feature_frame(self) -> pd.DataFrame:
        values = self.model_dump(include=set(FEATURE_COLUMNS))
        return pd.DataFrame([[values[name] for name in FEATURE_COLUMNS]], columns=FEATURE_COLUMNS)


class ModelDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    model_version: str
    family: Literal["logistic_regression"]
    bundle_sha256: str


class ScoreValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: Literal["synthetic_model_score"] = "synthetic_model_score"
    probability: Annotated[float, Field(ge=0.0, le=1.0)]
    display_percent: Annotated[float, Field(ge=0.0, le=100.0)]


class FactorContribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str
    display_name: str
    input_value: Any
    baseline_value: Any
    logit_contribution: float
    direction: Literal["positive", "negative", "neutral"]
    rank: int


class ExplanationDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: Literal["exact_logit_decomposition"] = "exact_logit_decomposition"
    reference_version: str
    reference_sha256: str
    reference_source_sha256: str
    model_logit: float
    baseline_logit: float
    contribution_sum: float
    reconstructed_logit: float
    reconstruction_error: float
    probability_from_logit: float
    probability_error: float
    transformed_feature_count: int
    grouped_factor_count: int


class InferenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    model: ModelDescriptor
    demonstration_only: Literal[True] = True
    score: ScoreValue
    factors: list[FactorContribution]
    limitations_warning: str
    diagnostics: ExplanationDiagnostics
    recommendations: list[str] = Field(default_factory=list)


class WhatIfResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    simulation_only: Literal[True] = True
    changed_fields: list[str]
    original: InferenceResponse
    alternative: InferenceResponse
    delta_percentage_points: float
    limitations_warning: str
