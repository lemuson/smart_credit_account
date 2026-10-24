from __future__ import annotations

import pandas as pd
from ml_scoring.validation import fairness_audit, validate_dataset


def test_full_dataset_passes_hard_and_statistical_validation(full_dataset, config):
    result = validate_dataset(full_dataset, config)
    assert result.hard_errors == []
    assert result.warnings == []


def test_validation_detects_leakage_column(full_dataset, config):
    invalid = full_dataset.copy()
    invalid["score"] = 0.0
    result = validate_dataset(invalid, config)
    assert result.hard_errors
    assert "Columns must be exactly" in result.hard_errors[0]


def test_validation_detects_duplicate_features(full_dataset, config):
    invalid = full_dataset.copy()
    invalid.iloc[1] = invalid.iloc[0]
    result = validate_dataset(invalid, config)
    assert any("duplicate input-feature" in error for error in result.hard_errors)


def test_age_fairness_audit(full_dataset, config):
    audit = fairness_audit(full_dataset, config)
    assert audit["age_in_ml_feature_allow_list"] is False
    assert audit["counterfactual_max_probability_change"] == 0.0
    assert abs(audit["age_target_correlation"]) <= 0.05
    assert audit["conditional_strata_compared"] > 0


def test_csv_round_trip_preserves_schema(full_dataset, config, tmp_path):
    path = tmp_path / "dataset.csv"
    full_dataset.to_csv(path, index=False, float_format="%.1f")
    loaded = pd.read_csv(
        path,
        dtype={
            "age": "int64",
            "annual_revenue": "float64",
            "credit_history": "string",
            "business_age_months": "int64",
            "loan_amount": "float64",
            "has_collateral": "bool",
            "loan_term_months": "int64",
            "approved": "int64",
        },
    )
    loaded["credit_history"] = pd.Categorical(
        loaded["credit_history"], categories=config["credit_history"]["categories"]
    )
    pd.testing.assert_frame_equal(full_dataset.reset_index(drop=True), loaded)
