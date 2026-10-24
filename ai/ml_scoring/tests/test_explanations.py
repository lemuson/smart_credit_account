from __future__ import annotations

from pathlib import Path

import pytest
from ml_scoring.inference_schema import CreditApplication
from ml_scoring.local_inference import LocalInferenceService

ML_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def service() -> LocalInferenceService:
    return LocalInferenceService.from_artifact_directory(ML_ROOT / "models")


@pytest.mark.parametrize(
    "application",
    [
        CreditApplication(
            annual_revenue=2_000_000.0,
            credit_history="bad",
            business_age_months=8,
            loan_amount=2_500_000.0,
            has_collateral=False,
            loan_term_months=12,
        ),
        CreditApplication(
            annual_revenue=12_000_000.0,
            credit_history="good",
            business_age_months=96,
            loan_amount=1_500_000.0,
            has_collateral=True,
            loan_term_months=36,
        ),
    ],
)
def test_explanation_exactly_reconstructs_logit_and_probability(service, application):
    diagnostics = service.score(application).diagnostics
    assert diagnostics.model_logit == pytest.approx(diagnostics.reconstructed_logit, abs=1e-12)
    assert diagnostics.reconstruction_error < 1e-12
    assert diagnostics.probability_error < 1e-12
    assert diagnostics.grouped_factor_count == 6
    assert diagnostics.transformed_feature_count == 9


def test_credit_history_one_hot_is_grouped_for_user(service):
    application = CreditApplication(
        annual_revenue=5_000_000.0,
        credit_history="average",
        business_age_months=36,
        loan_amount=1_500_000.0,
        has_collateral=False,
        loan_term_months=24,
    )
    factors = service.score(application).factors
    assert len(factors) == 6
    assert sum(factor.feature == "credit_history" for factor in factors) == 1
    assert not any("credit_history_" in factor.feature for factor in factors)
    assert {factor.direction for factor in factors} <= {"positive", "negative", "neutral"}


def test_reference_comes_from_train_and_matches_model(service):
    assert service.reference.model_bundle_sha256 == service.bundle_sha256
    assert service.reference.source_sha256
    assert len(service.reference.transformed_feature_names) == 9

