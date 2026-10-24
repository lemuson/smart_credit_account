from __future__ import annotations

from pathlib import Path

import pytest
from ml_scoring.inference_schema import CreditApplication, WhatIfResponse
from ml_scoring.local_inference import LocalInferenceService
from ml_scoring.what_if import compare_applications

ML_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def service() -> LocalInferenceService:
    return LocalInferenceService.from_artifact_directory(ML_ROOT / "models")


def test_what_if_recomputes_both_applications(service):
    original = CreditApplication(
        annual_revenue=5_000_000.0,
        credit_history="average",
        business_age_months=36,
        loan_amount=3_000_000.0,
        has_collateral=False,
        loan_term_months=24,
    )
    alternative = original.model_copy(update={"loan_amount": 1_500_000.0})
    comparison = compare_applications(service, original, alternative)
    assert comparison.simulation_only is True
    assert comparison.changed_fields == ["loan_amount"]
    expected_delta = (
        service.score(alternative).score.probability - service.score(original).score.probability
    ) * 100
    assert comparison.delta_percentage_points == pytest.approx(round(expected_delta, 4))
    assert comparison.original.score.probability != comparison.alternative.score.probability


def test_what_if_requires_a_changed_model_feature(service):
    application = CreditApplication(
        annual_revenue=5_000_000.0,
        credit_history="average",
        business_age_months=36,
        loan_amount=3_000_000.0,
        has_collateral=False,
        loan_term_months=24,
    )
    with pytest.raises(ValueError, match="changed model feature"):
        compare_applications(service, application, application)


def test_what_if_serialization_round_trip(service):
    original = CreditApplication(
        annual_revenue=5_000_000.0,
        credit_history="good",
        business_age_months=48,
        loan_amount=3_000_000.0,
        has_collateral=True,
        loan_term_months=24,
    )
    result = compare_applications(
        service, original, original.model_copy(update={"loan_amount": 1_500_000.0})
    )
    assert WhatIfResponse.model_validate_json(result.model_dump_json()) == result

