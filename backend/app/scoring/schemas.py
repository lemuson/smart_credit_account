from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, model_validator

from app.common import Schema


class AssessmentCreate(Schema):
    application_id: UUID
    expected_application_version: StrictInt | None = Field(default=None, ge=1)


def changes_json_schema(schema):
    schema["minProperties"] = 1
    for field in schema["properties"].values():
        choices = field.pop("anyOf", None)
        if choices:
            field.update(next(choice for choice in choices if choice.get("type") != "null"))
        field.pop("default", None)
    schema["properties"]["loan_term_months"]["enum"] = [6, 12, 18, 24, 36, 48, 60]


class WhatIfChanges(Schema):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, json_schema_extra=changes_json_schema
    )
    annual_revenue: Annotated[StrictFloat, Field(gt=0)] | None = None
    credit_history: Literal["good", "average", "bad", "none"] | None = None
    business_age_months: Annotated[StrictInt, Field(ge=0)] | None = None
    loan_amount: Annotated[StrictFloat, Field(gt=0)] | None = None
    has_collateral: StrictBool | None = None
    loan_term_months: StrictInt | None = None

    @model_validator(mode="after")
    def valid_changes(self):
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("Provide at least one non-null feature")
        if "loan_term_months" in self.model_fields_set and self.loan_term_months not in {
            6,
            12,
            18,
            24,
            36,
            48,
            60,
        }:
            raise ValueError("Unsupported loan term")
        return self


class WhatIfCreate(Schema):
    changes: WhatIfChanges


class Score(Schema):
    name: Literal["synthetic_model_score"]
    value: float = Field(ge=0, le=1)
    display_percent: float = Field(ge=0, le=100)


class ModelDescriptor(Schema):
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    family: Literal["logistic_regression"]
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


Feature = Literal[
    "annual_revenue",
    "credit_history",
    "business_age_months",
    "loan_amount",
    "has_collateral",
    "loan_term_months",
]


class Factor(Schema):
    feature: Feature
    display_name: str = Field(min_length=1)
    input_value: float | int | bool | str
    baseline_value: float | dict[str, float]
    logit_contribution: float
    direction: Literal["positive", "negative", "neutral"]
    rank: int = Field(ge=1, le=6)


class Baseline(Schema):
    method: Literal["mean_in_transformed_train_space"]
    logit: float
    reference_version: str
    reference_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Consistency(Schema):
    model_logit: float
    contribution_sum: float
    reconstructed_logit: float
    reconstruction_error: float = Field(ge=0)


class Explanation(Schema):
    baseline: Baseline
    factors: list[Factor] = Field(min_length=6, max_length=6)
    consistency: Consistency


class ScoringSnapshot(Schema):
    score: Score
    factors: list[Factor] = Field(min_length=6, max_length=6)


class WhatIfResponse(Schema):
    what_if_id: UUID
    assessment_id: UUID
    schema_version: Literal["1.0"]
    simulation_only: Literal[True]
    changed_fields: list[Feature] = Field(min_length=1)
    original: ScoringSnapshot
    alternative: ScoringSnapshot
    delta_percentage_points: float
    limitations_warning: str = Field(min_length=1)
    calculated_at: datetime


class AssessmentResponse(Schema):
    assessment_id: UUID
    application_id: UUID
    application_version: int = Field(ge=1)
    schema_version: Literal["1.0"]
    status: Literal["completed"]
    model: ModelDescriptor
    demonstration_only: Literal[True]
    score: Score
    explanation: Explanation
    limitations_warning: str = Field(min_length=1)
    calculated_at: datetime
    selected_what_if: WhatIfResponse | None


class Problem(Schema):
    type: str
    title: str
    status: int = Field(ge=400, le=599)
    code: str = Field(pattern=r"^[A-Z0-9_]+$")
    detail: str
    instance: str
    request_id: UUID
    errors: list[dict]
