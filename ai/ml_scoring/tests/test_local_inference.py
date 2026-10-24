from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from ml_scoring.features import FEATURE_COLUMNS
from ml_scoring.inference import sha256_file
from ml_scoring.inference_schema import CreditApplication, InferenceResponse
from ml_scoring.local_inference import LocalInferenceService, UnsupportedInputRangeError
from pydantic import ValidationError

ML_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def service() -> LocalInferenceService:
    return LocalInferenceService.from_artifact_directory(ML_ROOT / "models")


@pytest.fixture
def application() -> CreditApplication:
    return CreditApplication(
        annual_revenue=5_000_000.0,
        credit_history="good",
        business_age_months=48,
        loan_amount=3_000_000.0,
        has_collateral=True,
        loan_term_months=24,
        age=40,
    )


def test_approved_model_loads_with_manifest_integrity(service):
    manifest = json.loads((ML_ROOT / "models" / "manifest.json").read_text(encoding="utf-8"))
    bundle_path = ML_ROOT / "models" / "credit_scoring_model.joblib"
    assert service.bundle.model_family == "logistic_regression"
    assert sha256_file(bundle_path) == manifest["final_bundle_sha256"]
    assert service.bundle.feature_columns == FEATURE_COLUMNS


def test_tampered_artifact_is_rejected_before_use(tmp_path):
    copied_models = tmp_path / "models"
    shutil.copytree(ML_ROOT / "models", copied_models)
    schema_path = copied_models / "input_schema.json"
    schema_path.write_text(schema_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match=r"checksum mismatch: input_schema\.json"):
        LocalInferenceService.from_artifact_directory(copied_models)


def test_schema_is_strict_and_age_is_not_a_model_feature(application):
    assert "age" not in application.to_feature_frame().columns
    assert list(application.to_feature_frame().columns) == FEATURE_COLUMNS
    with pytest.raises(ValidationError):
        CreditApplication.model_validate(
            {**application.model_dump(), "has_collateral": 1}
        )
    with pytest.raises(ValidationError):
        CreditApplication.model_validate(
            {**application.model_dump(), "unexpected": 1}
        )


def test_predict_proba_is_bounded_and_deterministic(service, application):
    first = service.score(application)
    second = service.score(application)
    assert 0.0 <= first.score.probability <= 1.0
    assert first == second
    direct = service.bundle.predict_proba(application.to_feature_frame())[0, 1]
    assert first.score.probability == pytest.approx(direct, abs=1e-15)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("annual_revenue", 300_000.0),
        ("annual_revenue", 120_000_000.0),
        ("business_age_months", 0),
        ("business_age_months", 240),
        ("loan_amount", 100_000.0),
        ("loan_amount", 30_000_000.0),
        ("loan_term_months", 6),
        ("loan_term_months", 60),
    ],
)
def test_supported_boundary_values(service, application, field, value):
    values = application.model_dump()
    values["age"] = None
    values[field] = value
    response = service.score(CreditApplication.model_validate(values))
    assert 0.0 <= response.score.probability <= 1.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("annual_revenue", 299_999.0),
        ("annual_revenue", 120_000_001.0),
        ("business_age_months", 241),
        ("loan_amount", 99_999.0),
        ("loan_amount", 30_000_001.0),
    ],
)
def test_unsupported_ranges_do_not_return_a_score(service, application, field, value):
    values = application.model_dump()
    values["age"] = None
    values[field] = value
    with pytest.raises(UnsupportedInputRangeError) as captured:
        service.score(CreditApplication.model_validate(values))
    assert captured.value.issues[0]["field"] == field


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("annual_revenue", float("nan")),
        ("loan_amount", float("inf")),
        ("loan_term_months", 15),
        ("credit_history", "excellent"),
    ],
)
def test_invalid_values_fail_formal_validation(application, field, value):
    values = application.model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        CreditApplication.model_validate(values)


def test_response_serialization_is_stable(service, application):
    response = service.score(application)
    encoded = response.model_dump_json()
    restored = InferenceResponse.model_validate_json(encoded)
    assert restored == response
    assert restored.demonstration_only is True
    assert restored.recommendations == []


def test_probability_array_is_well_formed(service, application):
    probabilities = service.bundle.predict_proba(application.to_feature_frame())
    assert probabilities.shape == (1, 2)
    np.testing.assert_allclose(probabilities.sum(axis=1), [1.0])
