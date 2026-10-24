#!/usr/bin/env python3
"""Build the reproducible explanation baseline from train only."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "src"))

from ml_scoring.features import FEATURE_COLUMNS  # noqa: E402
from ml_scoring.inference import load_trusted_bundle, sha256_file  # noqa: E402


def main() -> None:
    models_dir = ML_ROOT / "models"
    train_path = ML_ROOT / "data" / "synthetic_credit_train.csv"
    metrics_path = ML_ROOT / "reports" / "training_metrics.json"
    manifest_path = models_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    train_sha256 = sha256_file(train_path)
    if train_sha256 != metrics["dataset_sha256"]["train"]:
        raise ValueError("Train dataset checksum differs from the recorded training input")
    bundle_sha256 = manifest["artifacts"]["credit_scoring_model.joblib"]
    bundle = load_trusted_bundle(
        models_dir / "credit_scoring_model.joblib",
        expected_sha256=bundle_sha256,
        trusted=True,
    )
    if bundle.model_family != "logistic_regression":
        raise ValueError("Explanation reference can only be built for Logistic Regression")

    train = pd.read_csv(train_path)
    frame = train[FEATURE_COLUMNS]
    preprocessing = bundle.base_model.named_steps["preprocessing"]
    transformed = np.asarray(preprocessing.transform(frame), dtype=float)
    names = [str(name) for name in preprocessing.get_feature_names_out()]

    financial = preprocessing.named_transformers_["financial"]
    financial_means = financial.named_steps["scale"].mean_
    numerical = preprocessing.named_transformers_["numeric"]
    numerical_means = numerical.named_steps["scale"].mean_
    history_proportions = {
        category: float((frame["credit_history"] == category).mean())
        for category in ["good", "average", "bad", "none"]
    }
    original_reference_values = {
        "annual_revenue": float(math.expm1(financial_means[0])),
        "credit_history": history_proportions,
        "business_age_months": float(numerical_means[0]),
        "loan_amount": float(math.expm1(financial_means[1])),
        "has_collateral": float(frame["has_collateral"].astype(float).mean()),
        "loan_term_months": float(numerical_means[1]),
    }
    payload = {
        "schema_version": "1.0",
        "training_version": bundle.training_version,
        "model_bundle_sha256": bundle_sha256,
        "source": "synthetic_credit_train.csv",
        "source_sha256": train_sha256,
        "row_count": len(frame),
        "feature_columns": FEATURE_COLUMNS,
        "sklearn_version": sklearn.__version__,
        "baseline_method": "mean_in_transformed_train_space",
        "transformed_feature_names": names,
        "transformed_mean": transformed.mean(axis=0).tolist(),
        "original_reference_values": original_reference_values,
    }
    reference_path = models_dir / "explanation_reference.json"
    reference_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest["model_id"] = "synthetic-credit-logreg"
    manifest["model_version"] = bundle.training_version
    manifest["schema_version"] = "1.0"
    manifest["artifacts"][reference_path.name] = sha256_file(reference_path)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Explanation reference created from {len(frame)} train rows")


if __name__ == "__main__":
    main()

