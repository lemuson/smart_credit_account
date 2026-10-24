"""Exact coefficient-based explanations for the saved Logistic Regression pipeline."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.pipeline import Pipeline

from .features import FEATURE_COLUMNS
from .inference import sha256_file
from .inference_schema import ExplanationDiagnostics, FactorContribution

REFERENCE_SCHEMA_VERSION = "1.0"
DISPLAY_NAMES = {
    "annual_revenue": "Годовая выручка",
    "credit_history": "Кредитная история",
    "business_age_months": "Срок работы бизнеса",
    "loan_amount": "Сумма кредита",
    "has_collateral": "Наличие залога",
    "loan_term_months": "Срок кредита",
}


@dataclass(frozen=True)
class ExplanationReference:
    schema_version: str
    model_bundle_sha256: str
    source_sha256: str
    transformed_feature_names: tuple[str, ...]
    transformed_mean: np.ndarray
    original_reference_values: dict[str, Any]


@dataclass(frozen=True)
class ExactExplanation:
    factors: list[FactorContribution]
    diagnostics: ExplanationDiagnostics


def _group_for_transformed_name(name: str) -> str:
    if name.startswith("credit_history_"):
        return "credit_history"
    if name in FEATURE_COLUMNS:
        return name
    raise ValueError(f"Unsupported transformed feature in explanation: {name}")


def load_explanation_reference(
    path: str | Path,
    *,
    expected_sha256: str,
    expected_model_sha256: str,
) -> ExplanationReference:
    path = Path(path)
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError("Explanation reference checksum mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != REFERENCE_SCHEMA_VERSION:
        raise ValueError("Unsupported explanation reference schema version")
    if payload.get("model_bundle_sha256") != expected_model_sha256:
        raise ValueError("Explanation reference belongs to another model bundle")
    trained_sklearn = str(payload.get("sklearn_version", ""))
    if trained_sklearn.split(".")[:2] != sklearn.__version__.split(".")[:2]:
        raise ValueError(
            f"Incompatible scikit-learn version: reference={trained_sklearn}, "
            f"runtime={sklearn.__version__}"
        )
    names = tuple(payload["transformed_feature_names"])
    means = np.asarray(payload["transformed_mean"], dtype=float)
    if len(names) != len(means) or not np.isfinite(means).all():
        raise ValueError("Invalid transformed baseline in explanation reference")
    return ExplanationReference(
        schema_version=payload["schema_version"],
        model_bundle_sha256=payload["model_bundle_sha256"],
        source_sha256=payload["source_sha256"],
        transformed_feature_names=names,
        transformed_mean=means,
        original_reference_values=payload["original_reference_values"],
    )


def explain_logistic_prediction(
    pipeline: Pipeline,
    frame: pd.DataFrame,
    probability: float,
    reference: ExplanationReference,
    *,
    reference_sha256: str,
) -> ExactExplanation:
    if len(frame) != 1:
        raise ValueError("Exact explanation supports exactly one application")
    preprocessing = pipeline.named_steps.get("preprocessing")
    model = pipeline.named_steps.get("model")
    if preprocessing is None or model is None or not hasattr(model, "coef_"):
        raise TypeError("Saved model is not the expected Logistic Regression pipeline")

    names = tuple(str(name) for name in preprocessing.get_feature_names_out())
    if names != reference.transformed_feature_names:
        raise ValueError("Transformed feature schema differs from explanation reference")
    transformed = np.asarray(preprocessing.transform(frame), dtype=float)[0]
    coefficients = np.asarray(model.coef_, dtype=float)[0]
    intercept = float(np.asarray(model.intercept_, dtype=float)[0])
    if (
        transformed.shape != coefficients.shape
        or transformed.shape != reference.transformed_mean.shape
    ):
        raise ValueError("Logistic Regression dimensions are inconsistent")

    raw_contributions = coefficients * (transformed - reference.transformed_mean)
    baseline_logit = intercept + float(np.dot(coefficients, reference.transformed_mean))
    model_logit = intercept + float(np.dot(coefficients, transformed))
    grouped = {feature: 0.0 for feature in FEATURE_COLUMNS}
    for name, contribution in zip(names, raw_contributions, strict=True):
        grouped[_group_for_transformed_name(name)] += float(contribution)

    contribution_sum = float(sum(grouped.values()))
    reconstructed_logit = baseline_logit + contribution_sum
    probability_from_logit = 1.0 / (1.0 + math.exp(-model_logit))
    rows: list[FactorContribution] = []
    values = frame.iloc[0].to_dict()
    order = sorted(FEATURE_COLUMNS, key=lambda feature: abs(grouped[feature]), reverse=True)
    for rank, feature in enumerate(order, start=1):
        contribution = grouped[feature]
        direction = "neutral"
        if contribution > 1e-12:
            direction = "positive"
        elif contribution < -1e-12:
            direction = "negative"
        rows.append(
            FactorContribution(
                feature=feature,
                display_name=DISPLAY_NAMES[feature],
                input_value=values[feature],
                baseline_value=reference.original_reference_values[feature],
                logit_contribution=contribution,
                direction=direction,
                rank=rank,
            )
        )

    diagnostics = ExplanationDiagnostics(
        reference_version=reference.schema_version,
        reference_sha256=reference_sha256,
        reference_source_sha256=reference.source_sha256,
        model_logit=model_logit,
        baseline_logit=baseline_logit,
        contribution_sum=contribution_sum,
        reconstructed_logit=reconstructed_logit,
        reconstruction_error=abs(model_logit - reconstructed_logit),
        probability_from_logit=probability_from_logit,
        probability_error=abs(probability - probability_from_logit),
        transformed_feature_count=len(names),
        grouped_factor_count=len(grouped),
    )
    return ExactExplanation(factors=rows, diagnostics=diagnostics)
