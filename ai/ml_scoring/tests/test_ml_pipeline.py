from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from ml_scoring.calibration import make_calibrator
from ml_scoring.evaluation import binary_metrics, expected_calibration_error
from ml_scoring.features import FEATURE_COLUMNS, get_xy, validate_feature_frame
from ml_scoring.inference import CreditScoringModel, load_trusted_bundle, save_bundle
from ml_scoring.train_baseline import fit_baseline
from ml_scoring.train_catboost import fit_final_catboost

BASELINE_CONFIG = {"C": 1.0, "max_iter": 500, "solver": "lbfgs"}
CATBOOST_CONFIG = {
    "loss_function": "Logloss",
    "eval_metric": "AUC",
    "thread_count": 1,
}
CATBOOST_PARAMETERS = {
    "iterations": 20,
    "depth": 3,
    "learning_rate": 0.1,
    "l2_leaf_reg": 3.0,
}


def test_feature_allow_list_excludes_age():
    assert FEATURE_COLUMNS == [
        "annual_revenue",
        "credit_history",
        "business_age_months",
        "loan_amount",
        "has_collateral",
        "loan_term_months",
    ]
    assert "age" not in FEATURE_COLUMNS


def test_preprocessing_handles_category_and_has_no_age(ml_fixture):
    train = ml_fixture.iloc[:500].copy()
    features, target = get_xy(train)
    model = fit_baseline(features, target, BASELINE_CONFIG, seed=42)
    transformed_names = set(model.named_steps["preprocessing"].get_feature_names_out())
    assert "age" not in transformed_names
    assert any(name.startswith("credit_history_") for name in transformed_names)
    assert model.predict_proba(features.iloc[:3]).shape == (3, 2)


def test_baseline_training_is_reproducible(ml_fixture):
    features, target = get_xy(ml_fixture.iloc[:500].copy())
    first = fit_baseline(features, target, BASELINE_CONFIG, seed=77)
    second = fit_baseline(features, target, BASELINE_CONFIG, seed=77)
    np.testing.assert_allclose(
        first.predict_proba(features)[:, 1], second.predict_proba(features)[:, 1]
    )


def test_metrics_and_ece_are_correctly_bounded():
    target = np.array([0, 0, 1, 1])
    probability = np.array([0.1, 0.4, 0.6, 0.9])
    metrics = binary_metrics(target, probability, threshold=0.5, n_bins=2)
    assert metrics["accuracy"] == 1.0
    assert metrics["confusion_matrix"] == [[2, 0], [0, 2]]
    assert 0 <= expected_calibration_error(target, probability, n_bins=2) <= 1


@pytest.mark.parametrize("method", ["uncalibrated", "sigmoid", "isotonic"])
def test_calibrators_return_valid_probabilities(method):
    probability = np.linspace(0.05, 0.95, 40)
    target = (probability + np.sin(np.arange(40)) * 0.1 >= 0.5).astype(int)
    calibrator = make_calibrator(method, seed=42).fit(probability, target)
    calibrated = calibrator.transform(probability)
    assert calibrated.shape == probability.shape
    assert np.all((calibrated >= 0) & (calibrated <= 1))


def _tiny_catboost_bundle(ml_fixture) -> CreditScoringModel:
    train = ml_fixture.iloc[:500].copy()
    features, target = get_xy(train)
    model = fit_final_catboost(
        features,
        target,
        CATBOOST_PARAMETERS,
        iterations=20,
        config=CATBOOST_CONFIG,
        seed=123,
    )
    return CreditScoringModel(
        base_model=model,
        calibrator=make_calibrator("uncalibrated", seed=123),
        threshold=0.5,
        training_version="test",
    )


def test_catboost_training_is_reproducible(ml_fixture):
    features, _ = get_xy(ml_fixture.iloc[:500].copy())
    first = _tiny_catboost_bundle(ml_fixture)
    second = _tiny_catboost_bundle(ml_fixture)
    np.testing.assert_allclose(
        first.predict_proba(features.iloc[:50])[:, 1],
        second.predict_proba(features.iloc[:50])[:, 1],
    )


def test_model_save_load_and_single_application_inference(ml_fixture, tmp_path):
    bundle = _tiny_catboost_bundle(ml_fixture)
    path = tmp_path / "model.joblib"
    digest = save_bundle(bundle, path)
    with pytest.raises(ValueError, match="trusted=True"):
        load_trusted_bundle(path, expected_sha256=digest)
    loaded = load_trusted_bundle(path, expected_sha256=digest, trusted=True)
    application = ml_fixture[FEATURE_COLUMNS].iloc[[550]].copy()
    probability = loaded.predict_proba(application)
    assert probability.shape == (1, 2)
    assert probability.sum() == pytest.approx(1.0)


def test_invalid_inference_input_is_rejected(ml_fixture):
    invalid = ml_fixture[FEATURE_COLUMNS].iloc[[0]].copy()
    invalid["loan_amount"] = -1.0
    with pytest.raises(ValueError, match="loan_amount"):
        validate_feature_frame(invalid)

    missing = ml_fixture[FEATURE_COLUMNS].iloc[[0]].drop(columns="credit_history")
    with pytest.raises(ValueError, match="Input columns"):
        validate_feature_frame(missing)


def test_unknown_credit_history_is_rejected(ml_fixture):
    invalid = ml_fixture[FEATURE_COLUMNS].iloc[[0]].copy()
    invalid["credit_history"] = pd.Series(["excellent"], index=invalid.index)
    with pytest.raises(ValueError, match="credit_history"):
        validate_feature_frame(invalid)
