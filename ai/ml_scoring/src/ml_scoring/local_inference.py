"""Reusable local inference service with artifact integrity and exact explanations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .explanations import (
    ExplanationReference,
    explain_logistic_prediction,
    load_explanation_reference,
)
from .features import CREDIT_HISTORY_CATEGORIES, FEATURE_COLUMNS
from .inference import CreditScoringModel, load_trusted_bundle, sha256_file
from .inference_schema import (
    CreditApplication,
    InferenceResponse,
    ModelDescriptor,
    ScoreValue,
)

MODEL_ID = "synthetic-credit-logreg"
LIMITATIONS_WARNING = (
    "Демонстрационная ML-оценка обучена на синтетических данных и не является банковской "
    "вероятностью одобрения, кредитным решением или гарантией результата. Факторы описывают "
    "поведение модели относительно train-baseline и не доказывают причинную связь."
)


class UnsupportedInputRangeError(ValueError):
    """Input is formally valid but outside the generator-supported domain."""

    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self.issues = issues
        super().__init__("Input is outside the supported synthetic-data range")


def _range_issues(application: CreditApplication) -> list[dict[str, Any]]:
    ranges = {
        "annual_revenue": (300_000.0, 120_000_000.0),
        "business_age_months": (0, 240),
        "loan_amount": (100_000.0, 30_000_000.0),
    }
    issues: list[dict[str, Any]] = []
    for field, (minimum, maximum) in ranges.items():
        value = getattr(application, field)
        if not minimum <= value <= maximum:
            issues.append(
                {
                    "field": field,
                    "value": value,
                    "supported_minimum": minimum,
                    "supported_maximum": maximum,
                    "message": "value is outside the generator-supported range",
                }
            )
    return issues


@dataclass(frozen=True)
class LocalInferenceService:
    bundle: CreditScoringModel
    reference: ExplanationReference
    bundle_sha256: str
    reference_sha256: str

    @classmethod
    def from_artifact_directory(cls, models_dir: str | Path) -> LocalInferenceService:
        models_dir = Path(models_dir).resolve()
        manifest = json.loads((models_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("trusted_local_artifacts_only") is not True:
            raise ValueError("Manifest does not mark artifacts as trusted-local-only")
        if manifest.get("selected_model_family") != "logistic_regression":
            raise ValueError("Local explanation service requires the approved Logistic Regression")

        artifacts = manifest.get("artifacts", {})
        bundle_name = "credit_scoring_model.joblib"
        schema_name = "input_schema.json"
        reference_name = "explanation_reference.json"
        for name in (bundle_name, schema_name, reference_name):
            if name not in artifacts:
                raise ValueError(f"Manifest has no checksum for required artifact: {name}")
            if sha256_file(models_dir / name) != artifacts[name]:
                raise ValueError(f"Artifact checksum mismatch: {name}")

        schema = json.loads((models_dir / schema_name).read_text(encoding="utf-8"))
        if schema.get("feature_columns") != FEATURE_COLUMNS:
            raise ValueError("Input schema feature order is incompatible")
        if schema.get("age_used_for_prediction") is not False:
            raise ValueError("Input schema incorrectly enables age for prediction")
        if schema.get("credit_history_categories") != CREDIT_HISTORY_CATEGORIES:
            raise ValueError("Input schema credit_history categories are incompatible")

        bundle_sha256 = artifacts[bundle_name]
        bundle = load_trusted_bundle(
            models_dir / bundle_name,
            expected_sha256=bundle_sha256,
            trusted=True,
        )
        if bundle.model_family != "logistic_regression":
            raise ValueError("Final bundle is not Logistic Regression")
        if getattr(bundle.calibrator, "method", None) != "uncalibrated":
            raise ValueError("Exact logit explanation requires an uncalibrated final model")
        reference = load_explanation_reference(
            models_dir / reference_name,
            expected_sha256=artifacts[reference_name],
            expected_model_sha256=bundle_sha256,
        )
        return cls(
            bundle=bundle,
            reference=reference,
            bundle_sha256=bundle_sha256,
            reference_sha256=artifacts[reference_name],
        )

    def score(self, application: CreditApplication | dict[str, Any]) -> InferenceResponse:
        raw_application = (
            application.model_dump()
            if isinstance(application, CreditApplication)
            else application
        )
        application = CreditApplication.model_validate(raw_application)
        issues = _range_issues(application)
        if issues:
            raise UnsupportedInputRangeError(issues)
        frame = application.to_feature_frame()
        probability = float(self.bundle.predict_proba(frame)[0, 1])
        explanation = explain_logistic_prediction(
            self.bundle.base_model,
            frame,
            probability,
            self.reference,
            reference_sha256=self.reference_sha256,
        )
        if explanation.diagnostics.reconstruction_error > 1e-10:
            raise ArithmeticError("Explanation does not reconstruct the model logit")
        if explanation.diagnostics.probability_error > 1e-10:
            raise ArithmeticError("Explanation probability differs from model predict_proba")
        return InferenceResponse(
            model=ModelDescriptor(
                model_id=MODEL_ID,
                model_version=self.bundle.training_version,
                family="logistic_regression",
                bundle_sha256=self.bundle_sha256,
            ),
            score=ScoreValue(
                probability=probability,
                display_percent=round(probability * 100.0, 2),
            ),
            factors=explanation.factors,
            limitations_warning=LIMITATIONS_WARNING,
            diagnostics=explanation.diagnostics,
            recommendations=[],
        )


def validation_error_payload(error: ValidationError) -> dict[str, Any]:
    return {
        "status": "invalid_input",
        "errors": [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()
        ],
    }
