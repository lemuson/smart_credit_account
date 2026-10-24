#!/usr/bin/env python3
"""Correct final family selection from saved validation metrics without reopening test CSV."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "src"))
sys.path.insert(0, str(ML_ROOT / "scripts"))

from ml_scoring.calibration import make_calibrator  # noqa: E402
from ml_scoring.inference import CreditScoringModel, save_bundle, sha256_file  # noqa: E402
from train_models import _write_reports  # noqa: E402


def main() -> None:
    reports_dir = ML_ROOT / "reports"
    models_dir = ML_ROOT / "models"
    metrics_path = reports_dir / "training_metrics.json"
    results = json.loads(metrics_path.read_text(encoding="utf-8"))

    logistic_selection = results["validation"]["logistic_selection"]
    catboost_selection = results["validation"]["catboost_selection"]
    logistic_calibration = results["validation"]["logistic_calibration_evaluation"]
    selected_method = results["selection"]["calibration_method"]
    results["catboost_calibration_method"] = selected_method
    catboost_calibration = results["calibration_experiments"][selected_method]
    catboost_wins_both = (
        catboost_selection["roc_auc"] >= logistic_selection["roc_auc"] + 0.002
        and catboost_selection["log_loss"] <= logistic_selection["log_loss"]
        and catboost_calibration["roc_auc"] >= logistic_calibration["roc_auc"]
        and catboost_calibration["log_loss"] <= logistic_calibration["log_loss"]
    )
    if catboost_wins_both:
        raise RuntimeError("Saved validation metrics do not require a selection correction")

    reason = (
        "Выбрана Logistic Regression: небольшой выигрыш CatBoost на model-selection не "
        "подтвердился одновременно по ROC-AUC и Log Loss на независимой "
        "calibration-evaluation части, поэтому для MVP предпочтён более простой baseline."
    )
    results["selection"] = {
        "model_family": "logistic_regression",
        "calibration_method": "not_applicable",
        "reason": reason,
        "test_independence_note": (
            "Первоначальный test был открыт один раз до исправления правила выбора. Исправление "
            "использовало только ранее сохранённые validation-метрики; test CSV повторно не "
            "читался и test-прогнозы не пересчитывались. Поэтому holdout-результат сохранён, но "
            "его нельзя называть полностью независимым относительно финальной маркировки артефакта."
        ),
    }
    results["selection_correction"] = {
        "reason": "The initial rule accepted a mixed validation result as a CatBoost win.",
        "test_csv_reopened": False,
        "test_predictions_recomputed": False,
    }
    metrics_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    baseline = joblib.load(models_dir / "logistic_baseline.joblib")
    calibrator = make_calibrator("uncalibrated", int(results["training_seed"]))
    joblib.dump(calibrator, models_dir / "probability_calibrator.joblib")
    bundle = CreditScoringModel(
        base_model=baseline,
        calibrator=calibrator,
        threshold=float(results["threshold"]),
        training_version=str(results["training_version"]),
        model_family="logistic_regression",
    )
    bundle_sha = save_bundle(bundle, models_dir / "credit_scoring_model.joblib")
    _write_reports(
        results,
        reports_dir / "model_comparison.md",
        ML_ROOT / "docs" / "model_card.md",
    )

    manifest = {
        "trusted_local_artifacts_only": True,
        "final_bundle_sha256": bundle_sha,
        "artifacts": {
            path.name: sha256_file(path)
            for path in sorted(models_dir.iterdir())
            if path.is_file() and path.name != "manifest.json"
        },
        "selected_model_family": "logistic_regression",
        "selected_calibration": "not_applicable",
        "training_config_sha256": results["training_config_sha256"],
        "selection_correction_after_test": True,
        "test_csv_reopened": False,
    }
    (models_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Finalized Logistic Regression from validation metrics without reopening test CSV")


if __name__ == "__main__":
    main()
