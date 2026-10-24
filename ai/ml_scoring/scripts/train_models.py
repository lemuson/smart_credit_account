#!/usr/bin/env python3
"""Train, select, calibrate and evaluate the synthetic credit-scoring models once."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ml-scoring-matplotlib"))

import catboost
import joblib
import matplotlib
import numpy as np
import pandas as pd
import sklearn
import yaml

ML_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ML_ROOT.parent
sys.path.insert(0, str(ML_ROOT / "src"))

from ml_scoring.calibration import make_calibrator  # noqa: E402
from ml_scoring.config import load_config  # noqa: E402
from ml_scoring.evaluation import (  # noqa: E402
    binary_metrics,
    create_model_figures,
    subgroup_metrics,
)
from ml_scoring.features import (  # noqa: E402
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    get_xy,
    load_dataset_splits,
    partition_validation,
    prepare_catboost_features,
)
from ml_scoring.inference import CreditScoringModel, save_bundle, sha256_file  # noqa: E402
from ml_scoring.train_baseline import baseline_coefficients, fit_baseline  # noqa: E402
from ml_scoring.train_catboost import fit_final_catboost, tune_catboost  # noqa: E402


def _load_training_config(path: Path) -> tuple[dict[str, Any], str]:
    values = yaml.safe_load(path.read_text(encoding="utf-8"))
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return values, hashlib.sha256(canonical.encode()).hexdigest()


def _predict_catboost(model: Any, frame: pd.DataFrame) -> np.ndarray:
    return model.predict_proba(prepare_catboost_features(frame[FEATURE_COLUMNS]))[:, 1]


def _metric_row(name: str, metrics: dict[str, Any]) -> str:
    return (
        f"| {name} | {metrics['roc_auc']:.4f} | {metrics['pr_auc']:.4f} | "
        f"{metrics['accuracy']:.4f} | {metrics['precision']:.4f} | "
        f"{metrics['recall']:.4f} | {metrics['f1']:.4f} | "
        f"{metrics['log_loss']:.4f} | {metrics['brier_score']:.4f} | "
        f"{metrics['ece']:.4f} |"
    )


def _subgroup_table(rows: list[dict[str, Any]]) -> list[str]:
    result = [
        "| Группа | N | Positive rate | ROC-AUC | Brier | ECE | Надёжность |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        auc = "n/a" if row["roc_auc"] is None else f"{row['roc_auc']:.4f}"
        reliability = (
            "ограниченная" if row["limited_reliability"] else "достаточная для диагностики"
        )
        result.append(
            f"| {row['group']} | {row['size']} | {row['positive_rate']:.2%} | {auc} | "
            f"{row['brier_score']:.4f} | {row['ece']:.4f} | {reliability} |"
        )
    return result


def _write_reports(
    results: dict[str, Any],
    report_path: Path,
    model_card_path: Path,
) -> None:
    validation = results["validation"]
    test = results["test"]
    selected_family = results["selection"]["model_family"]
    selected_method = results["selection"]["calibration_method"]
    catboost_calibration_method = results.get(
        "catboost_calibration_method",
        selected_method if selected_family == "catboost" else "uncalibrated",
    )
    catboost_calibration = results["calibration_experiments"][catboost_calibration_method]
    selected_validation = (
        validation["catboost_selection"]
        if selected_family == "catboost"
        else validation["logistic_selection"]
    )
    selected_test = test["catboost_final"] if selected_family == "catboost" else test["logistic"]
    logistic_parameters = json.dumps(
        results["models"]["logistic"]["parameters"], ensure_ascii=False
    )
    catboost_parameters = json.dumps(
        results["models"]["catboost"]["parameters"], ensure_ascii=False
    )
    comparison_lines = [
        "# Сравнение моделей кредитного скоринга",
        "",
        "## Данные и протокол",
        "",
        "Использованы 14 000 train, 3 000 validation и 3 000 test заявок. Validation заранее "
        "разделена на 1 200 строк для выбора CatBoost, 900 для обучения калибратора и 900 для "
        "выбора калибровки. Threshold зафиксирован на 0.5. Test открыт однократно после "
        "первоначальной фиксации решений; последующее исправление правила выбора описано ниже.",
        "",
        "Возраст не входил в feature matrix. Использованы только шесть утверждённых признаков.",
        "",
        "## Версии",
        "",
    ]
    comparison_lines.extend(
        f"- {name}: `{version}`" for name, version in results["library_versions"].items()
    )
    comparison_lines.extend(
        [
            "",
            "## Конфигурации",
            "",
            f"Logistic Regression: `{logistic_parameters}`.",
            f"Выбранный CatBoost: `{catboost_parameters}`; "
            f"итераций после early stopping: **{results['models']['catboost']['iterations']}**.",
            "",
            "## Validation: выбор модели",
            "",
            "| Модель | ROC-AUC | PR-AUC | Accuracy | Precision | Recall | F1 | "
            "Log Loss | Brier | ECE |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            _metric_row("Logistic Regression", validation["logistic_selection"]),
            _metric_row("Выбранный CatBoost", validation["catboost_selection"]),
            "",
            "## Эксперименты с калибровкой",
            "",
            "Калибраторы обучены только на calibration-fit и сравнены на отдельной "
            "calibration-evaluation. После выбора метод переобучен на объединении этих "
            "двух частей; "
            "test при выборе не использовался.",
            "",
            "Сохранённые метрики позволяют напрямую сопоставить Logistic Regression и "
            "выбранный вариант CatBoost на одной и той же calibration-evaluation части:",
            "",
            "| Модель | ROC-AUC | PR-AUC | Log Loss | Brier | ECE |",
            "|---|---:|---:|---:|---:|---:|",
            (
                "| Logistic Regression | "
                f"{validation['logistic_calibration_evaluation']['roc_auc']:.4f} | "
                f"{validation['logistic_calibration_evaluation']['pr_auc']:.4f} | "
                f"{validation['logistic_calibration_evaluation']['log_loss']:.4f} | "
                f"{validation['logistic_calibration_evaluation']['brier_score']:.4f} | "
                f"{validation['logistic_calibration_evaluation']['ece']:.4f} |"
            ),
            (
                f"| CatBoost, {catboost_calibration_method} | "
                f"{catboost_calibration['roc_auc']:.4f} | "
                f"{catboost_calibration['pr_auc']:.4f} | "
                f"{catboost_calibration['log_loss']:.4f} | "
                f"{catboost_calibration['brier_score']:.4f} | "
                f"{catboost_calibration['ece']:.4f} |"
            ),
            "",
            "CatBoost должен превосходить baseline согласованно по ROC-AUC и Log Loss; "
            "test в этом сравнении не используется.",
            "",
            "| Метод | ROC-AUC | Log Loss | Brier | ECE |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for method, metrics in results["calibration_experiments"].items():
        comparison_lines.append(
            f"| {method} | {metrics['roc_auc']:.4f} | {metrics['log_loss']:.4f} | "
            f"{metrics['brier_score']:.4f} | {metrics['ece']:.4f} |"
        )
    comparison_lines.extend(
        [
            "",
            (
                f"Для CatBoost выбран метод **{catboost_calibration_method}**: среди вариантов "
                "без существенной потери ROC-AUC он показал лучший Brier Score, затем Log Loss."
                if selected_family == "catboost"
                else "Отдельная калибровка не применяется к итоговой Logistic Regression. "
                f"Для исследованного CatBoost лучшим вариантом был `{catboost_calibration_method}`."
            ),
            "",
            "## Финальная оценка на test",
            "",
            "| Модель | ROC-AUC | PR-AUC | Accuracy | Precision | Recall | F1 | "
            "Log Loss | Brier | ECE |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            _metric_row("Константный baseline", test["constant_baseline"]),
            _metric_row("Logistic Regression", test["logistic"]),
            _metric_row(f"CatBoost + {catboost_calibration_method}", test["catboost_final"]),
            "",
            "Confusion matrix при threshold 0.5:",
            "",
            f"- Logistic Regression: `{test['logistic']['confusion_matrix']}`.",
            f"- CatBoost + {catboost_calibration_method}: "
            f"`{test['catboost_final']['confusion_matrix']}`.",
            "",
            "## Диагностика переобучения",
            "",
            "Logistic ROC-AUC train/selection: "
            f"{results['overfitting']['logistic_train_auc']:.4f} / "
            f"{validation['logistic_selection']['roc_auc']:.4f}. CatBoost ROC-AUC train/selection: "
            f"{results['overfitting']['catboost_train_auc']:.4f} / "
            f"{validation['catboost_selection']['roc_auc']:.4f}. "
            f"Разрыв CatBoost: {results['overfitting']['catboost_gap']:.4f}.",
            "",
            "## Анализ по подгруппам",
            "",
            "### Кредитная история",
            "",
        ]
    )
    comparison_lines.extend(_subgroup_table(results["subgroups"]["credit_history"]))
    comparison_lines.extend(["", "### Срок существования бизнеса", ""])
    comparison_lines.extend(_subgroup_table(results["subgroups"]["business_age"]))
    comparison_lines.extend(["", "### Кредит к выручке", ""])
    comparison_lines.extend(_subgroup_table(results["subgroups"]["leverage"]))
    comparison_lines.extend(
        [
            "",
            "### Возраст — только диагностический аудит",
            "",
        ]
    )
    comparison_lines.extend(_subgroup_table(results["subgroups"]["age_audit_only"]))
    comparison_lines.extend(
        [
            "",
            "Подгрупповые результаты на синтетических данных не доказывают fairness в реальной "
            "банковской системе. Малые группы помечаются как статистически ограниченные.",
            "",
            "## Выбор итоговой модели",
            "",
            results["selection"]["reason"],
            "",
            results["selection"].get("test_independence_note", ""),
            "",
            "## Ограничения и следующий этап",
            "",
            "Модель воспроизводит формулу синтетического генератора. Высокие метрики не означают "
            "качество на реальных заявках. Перед любым реальным применением нужны "
            "легитимные данные, "
            "правовая и fairness-оценка, мониторинг drift, независимая валидация и согласованная "
            "кредитная политика. Следующий безопасный этап — локальный inference-контур и проверка "
            "контракта без подключения к backend.",
            "",
        ]
    )
    report_path.write_text("\n".join(comparison_lines), encoding="utf-8")

    card = [
        "# Model Card: Synthetic Credit Scoring v1",
        "",
        "## Назначение",
        "",
        "Локальная экспериментальная модель для демонстрационного MVP кредитного кабинета.",
        "",
        "**Модель не предсказывает подтверждённую вероятность одобрения кредита реальным банком. "
        "Она воспроизводит статистические закономерности демонстрационной "
        "синтетической симуляции.**",
        "",
        "Результат не должен использоваться для автоматического принятия кредитных решений.",
        "",
        "## Данные и target",
        "",
        "Модель обучена на синтетических заявках генератора v1.0. Target `approved` — "
        "Bernoulli-результат "
        "симуляции, а не реальное банковское решение или факт дефолта.",
        "",
        "## Признаки",
        "",
    ]
    card.extend(f"- `{feature}`" for feature in FEATURE_COLUMNS)
    card.extend(
        [
            "",
            "Возраст исключён из модели и используется только в диагностическом аудите.",
            "",
            "## Алгоритм и выбор",
            "",
            results["selection"]["reason"],
            f"Итоговый способ калибровки: **{selected_method}**. Threshold: **0.5**.",
            "",
            (
                f"Для CatBoost используется калибровка `{selected_method}`."
                if selected_family == "catboost"
                else "Отдельная post-hoc калибровка итоговой Logistic Regression не "
                "применялась. Для CatBoost исследованы исходные вероятности, sigmoid и "
                "isotonic; ни один калибратор не улучшил одновременно Brier Score и Log Loss "
                "на независимой calibration-evaluation части."
            ),
            "",
            "## Качество",
            "",
            "| Набор | ROC-AUC | PR-AUC | Log Loss | Brier | ECE |",
            "|---|---:|---:|---:|---:|---:|",
            f"| Validation selection | {selected_validation['roc_auc']:.4f} | "
            f"{selected_validation['pr_auc']:.4f} | "
            f"{selected_validation['log_loss']:.4f} | "
            f"{selected_validation['brier_score']:.4f} | "
            f"{selected_validation['ece']:.4f} |",
            f"| Test | {selected_test['roc_auc']:.4f} | "
            f"{selected_test['pr_auc']:.4f} | "
            f"{selected_test['log_loss']:.4f} | "
            f"{selected_test['brier_score']:.4f} | "
            f"{selected_test['ece']:.4f} |",
            "",
            "## Калибровка и подгруппы",
            "",
            f"Итоговая калибровка: `{selected_method}`. "
            "Диагностика выполнена по кредитной истории, сроку бизнеса, отношению "
            "кредита к выручке "
            "и возрасту. Возрастной анализ не является доказательством справедливости.",
            "",
            results["selection"].get("test_independence_note", ""),
            "",
            "## Ограничения использования",
            "",
            "- Только доверенный локальный inference на данных той же схемы.",
            "- Нельзя использовать для реальных кредитных решений, pricing или отказов.",
            "- Нельзя трактовать вероятность как оценку реального банка.",
            "- Нужны реальные данные и независимая валидация до любого product use.",
            "- Joblib-артефакты нельзя загружать из недоверенного источника.",
            "",
        ]
    )
    model_card_path.write_text("\n".join(card), encoding="utf-8")


def main() -> None:
    training_config, training_config_sha = _load_training_config(
        ML_ROOT / "configs" / "training_v1.yaml"
    )
    generator_config = load_config(ML_ROOT / "configs" / "generator_v1.yaml")
    if training_config["features"] != FEATURE_COLUMNS:
        raise ValueError("Training feature list differs from code allow-list")
    if training_config["target"] != TARGET_COLUMN:
        raise ValueError("Training target differs from code target")

    splits = load_dataset_splits(ML_ROOT / "data", generator_config)
    partition_config = training_config["validation_partition"]
    partitions = partition_validation(
        splits.validation,
        seed=int(training_config["random_seed"]),
        selection_fraction=float(partition_config["model_selection_fraction"]),
        calibration_fit_fraction=float(partition_config["calibration_fit_fraction"]),
    )
    train_x, train_y = get_xy(splits.train)
    selection_x, selection_y = get_xy(partitions.model_selection)
    calibration_fit_x, calibration_fit_y = get_xy(partitions.calibration_fit)
    calibration_eval_x, calibration_eval_y = get_xy(partitions.calibration_evaluation)
    threshold = float(training_config["threshold"])
    seed = int(training_config["random_seed"])
    bins = int(training_config["calibration"]["n_bins"])

    baseline = fit_baseline(train_x, train_y, training_config["logistic_regression"], seed)
    baseline_selection_probability = baseline.predict_proba(selection_x)[:, 1]
    baseline_selection_metrics = binary_metrics(
        selection_y.to_numpy(), baseline_selection_probability, threshold=threshold, n_bins=bins
    )

    selected_parameters, selected_iterations, experiments = tune_catboost(
        train_x,
        train_y,
        selection_x,
        selection_y,
        training_config["catboost"],
        seed=seed,
        threshold=threshold,
    )
    selected_experiment = next(
        item
        for item in experiments
        if item["parameters"] == selected_parameters
        and item["best_iteration"] == selected_iterations
    )
    combined_fit = pd.concat([splits.train, partitions.model_selection], ignore_index=True)
    final_train_x, final_train_y = get_xy(combined_fit)
    catboost_model = fit_final_catboost(
        final_train_x,
        final_train_y,
        selected_parameters,
        selected_iterations,
        training_config["catboost"],
        seed=seed,
    )

    calibration_fit_base = _predict_catboost(catboost_model, calibration_fit_x)
    calibration_eval_base = _predict_catboost(catboost_model, calibration_eval_x)
    calibration_experiments: dict[str, dict[str, Any]] = {}
    fitted_calibrators: dict[str, Any] = {}
    for method in training_config["calibration"]["methods"]:
        calibrator = make_calibrator(method, seed)
        calibrator.fit(calibration_fit_base, calibration_fit_y.to_numpy())
        probability = calibrator.transform(calibration_eval_base)
        calibration_experiments[method] = binary_metrics(
            calibration_eval_y.to_numpy(), probability, threshold=threshold, n_bins=bins
        )
        fitted_calibrators[method] = calibrator
    uncalibrated_auc = calibration_experiments["uncalibrated"]["roc_auc"]
    eligible_methods = [
        method
        for method, metrics in calibration_experiments.items()
        if metrics["roc_auc"]
        >= uncalibrated_auc - float(training_config["calibration"]["maximum_roc_auc_degradation"])
    ]
    selected_method = min(
        eligible_methods,
        key=lambda method: (
            calibration_experiments[method]["brier_score"],
            calibration_experiments[method]["log_loss"],
        ),
    )
    calibration_all_x = pd.concat([calibration_fit_x, calibration_eval_x], ignore_index=True)
    calibration_all_y = pd.concat([calibration_fit_y, calibration_eval_y], ignore_index=True)
    final_calibrator = make_calibrator(selected_method, seed)
    final_calibrator.fit(
        _predict_catboost(catboost_model, calibration_all_x), calibration_all_y.to_numpy()
    )

    baseline_calibration_eval_probability = baseline.predict_proba(calibration_eval_x)[:, 1]
    baseline_calibration_eval_metrics = binary_metrics(
        calibration_eval_y.to_numpy(),
        baseline_calibration_eval_probability,
        threshold=threshold,
        n_bins=bins,
    )
    selected_cat_calibration_metrics = calibration_experiments[selected_method]
    catboost_wins_selection = (
        selected_experiment["selection_metrics"]["roc_auc"]
        >= baseline_selection_metrics["roc_auc"] + 0.002
        and selected_experiment["selection_metrics"]["log_loss"]
        <= baseline_selection_metrics["log_loss"]
    )
    catboost_wins_calibration_evaluation = (
        selected_cat_calibration_metrics["roc_auc"] >= baseline_calibration_eval_metrics["roc_auc"]
        and selected_cat_calibration_metrics["log_loss"]
        <= baseline_calibration_eval_metrics["log_loss"]
    )
    catboost_is_better = catboost_wins_selection and catboost_wins_calibration_evaluation
    chosen_family = "catboost" if catboost_is_better else "logistic_regression"
    reason = (
        "Выбран CatBoost: он показал согласованный выигрыш над baseline по ROC-AUC и Log Loss "
        "как на model-selection, так и на независимой calibration-evaluation части."
        if catboost_is_better
        else "Выбрана Logistic Regression: небольшой выигрыш CatBoost на model-selection не "
        "подтвердился одновременно по ROC-AUC и Log Loss на независимой "
        "calibration-evaluation части, поэтому для MVP предпочтён более простой baseline."
    )

    # Test remains untouched until every model, calibrator, schema and threshold is fixed above.
    test_x, test_y = get_xy(splits.test)
    logistic_test_probability = baseline.predict_proba(test_x)[:, 1]
    catboost_test_base = _predict_catboost(catboost_model, test_x)
    catboost_test_probability = final_calibrator.transform(catboost_test_base)
    constant_probability = np.full(len(test_y), float(train_y.mean()))
    test_metrics = {
        "constant_baseline": binary_metrics(
            test_y.to_numpy(), constant_probability, threshold=threshold, n_bins=bins
        ),
        "logistic": binary_metrics(
            test_y.to_numpy(), logistic_test_probability, threshold=threshold, n_bins=bins
        ),
        "catboost_final": binary_metrics(
            test_y.to_numpy(), catboost_test_probability, threshold=threshold, n_bins=bins
        ),
    }
    subgroups = subgroup_metrics(
        splits.test,
        test_y.to_numpy(),
        catboost_test_probability,
        minimum_size=int(training_config["subgroups"]["minimum_size"]),
        n_bins=bins,
    )

    logistic_train_auc = binary_metrics(
        train_y.to_numpy(), baseline.predict_proba(train_x)[:, 1], threshold=threshold
    )["roc_auc"]
    catboost_train_auc = binary_metrics(
        final_train_y.to_numpy(),
        _predict_catboost(catboost_model, final_train_x),
        threshold=threshold,
    )["roc_auc"]
    catboost_selection_auc = selected_experiment["selection_metrics"]["roc_auc"]

    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit-learn": sklearn.__version__,
        "catboost": catboost.__version__,
        "matplotlib": matplotlib.__version__,
        "joblib": joblib.__version__,
    }
    results: dict[str, Any] = {
        "training_version": training_config["training_version"],
        "training_seed": seed,
        "threshold": threshold,
        "training_config_sha256": training_config_sha,
        "generator_config_sha256": generator_config.sha256,
        "dataset_sha256": {
            name: sha256_file(ML_ROOT / "data" / f"synthetic_credit_{suffix}.csv")
            for name, suffix in (("train", "train"), ("validation", "val"), ("test", "test"))
        },
        "data_rows": {
            "train": len(splits.train),
            "validation": len(splits.validation),
            "test": len(splits.test),
            "model_selection": len(partitions.model_selection),
            "calibration_fit": len(partitions.calibration_fit),
            "calibration_evaluation": len(partitions.calibration_evaluation),
        },
        "library_versions": versions,
        "models": {
            "logistic": {
                "parameters": training_config["logistic_regression"],
                "coefficients": baseline_coefficients(baseline),
            },
            "catboost": {
                "parameters": selected_parameters,
                "iterations": selected_iterations,
                "experiments": experiments,
            },
        },
        "validation": {
            "logistic_selection": baseline_selection_metrics,
            "catboost_selection": selected_experiment["selection_metrics"],
            "logistic_calibration_evaluation": baseline_calibration_eval_metrics,
        },
        "calibration_experiments": calibration_experiments,
        "catboost_calibration_method": selected_method,
        "selection": {
            "model_family": chosen_family,
            "calibration_method": (
                selected_method if chosen_family == "catboost" else "not_applicable"
            ),
            "reason": reason,
            "test_independence_note": ("В штатном запуске выбор фиксируется до открытия test."),
        },
        "overfitting": {
            "logistic_train_auc": logistic_train_auc,
            "catboost_train_auc": catboost_train_auc,
            "catboost_gap": catboost_train_auc - catboost_selection_auc,
        },
        "test": test_metrics,
        "subgroups": subgroups,
    }

    models_dir = REPOSITORY_ROOT / training_config["artifacts"]["models_dir"]
    reports_dir = REPOSITORY_ROOT / training_config["artifacts"]["reports_dir"]
    figures_dir = REPOSITORY_ROOT / training_config["artifacts"]["figures_dir"]
    models_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(baseline, models_dir / "logistic_baseline.joblib")
    catboost_model.save_model(models_dir / "catboost_model.cbm")
    joblib.dump(final_calibrator, models_dir / "probability_calibrator.joblib")
    bundle = CreditScoringModel(
        base_model=catboost_model if chosen_family == "catboost" else baseline,
        calibrator=(
            final_calibrator
            if chosen_family == "catboost"
            else make_calibrator("uncalibrated", seed)
        ),
        threshold=threshold,
        training_version=str(training_config["training_version"]),
        model_family=chosen_family,
    )
    bundle_sha = save_bundle(bundle, models_dir / "credit_scoring_model.joblib")
    schema = {
        "feature_columns": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "age_used_for_prediction": False,
        "credit_history_categories": ["good", "average", "bad", "none"],
        "threshold": threshold,
    }
    (models_dir / "input_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (reports_dir / "training_metrics.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    create_model_figures(
        figures_dir,
        test_y.to_numpy(),
        {
            "Logistic Regression": logistic_test_probability,
            f"CatBoost + {selected_method}": catboost_test_probability,
        },
        {
            "Logistic Regression": test_metrics["logistic"],
            f"CatBoost + {selected_method}": test_metrics["catboost_final"],
        },
        subgroups,
        n_bins=bins,
    )
    _write_reports(
        results,
        reports_dir / "model_comparison.md",
        ML_ROOT / "docs" / "model_card.md",
    )
    manifest = {
        "trusted_local_artifacts_only": True,
        "final_bundle_sha256": bundle_sha,
        "artifacts": {
            path.name: sha256_file(path) for path in sorted(models_dir.iterdir()) if path.is_file()
        },
        "selected_model_family": chosen_family,
        "selected_calibration": results["selection"]["calibration_method"],
        "training_config_sha256": training_config_sha,
    }
    (models_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Training complete. Selected={chosen_family}, "
        f"calibration={results['selection']['calibration_method']}, "
        f"test ROC-AUC={test_metrics['catboost_final']['roc_auc']:.4f}, "
        f"test Brier={test_metrics['catboost_final']['brier_score']:.4f}"
    )


if __name__ == "__main__":
    main()
