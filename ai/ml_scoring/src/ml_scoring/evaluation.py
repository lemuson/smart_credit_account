"""Metrics, calibration diagnostics, subgroup analysis and model plots."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ml-scoring-matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)


def expected_calibration_error(
    target: np.ndarray, probability: np.ndarray, *, n_bins: int = 10
) -> float:
    target = np.asarray(target, dtype=int)
    probability = np.clip(np.asarray(probability, dtype=float), 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_index = np.minimum(np.digitize(probability, edges[1:-1], right=False), n_bins - 1)
    error = 0.0
    for index in range(n_bins):
        mask = bin_index == index
        if mask.any():
            error += float(mask.mean()) * abs(float(target[mask].mean() - probability[mask].mean()))
    return float(error)


def binary_metrics(
    target: np.ndarray,
    probability: np.ndarray,
    *,
    threshold: float = 0.5,
    n_bins: int = 10,
) -> dict[str, Any]:
    target = np.asarray(target, dtype=int)
    probability = np.clip(np.asarray(probability, dtype=float), 1e-7, 1 - 1e-7)
    prediction = (probability >= threshold).astype(int)
    matrix = confusion_matrix(target, prediction, labels=[0, 1])
    return {
        "roc_auc": float(roc_auc_score(target, probability)),
        "pr_auc": float(average_precision_score(target, probability)),
        "accuracy": float(accuracy_score(target, prediction)),
        "precision": float(precision_score(target, prediction, zero_division=0)),
        "recall": float(recall_score(target, prediction, zero_division=0)),
        "f1": float(f1_score(target, prediction, zero_division=0)),
        "log_loss": float(log_loss(target, probability, labels=[0, 1])),
        "brier_score": float(brier_score_loss(target, probability)),
        "ece": expected_calibration_error(target, probability, n_bins=n_bins),
        "threshold": float(threshold),
        "confusion_matrix": matrix.astype(int).tolist(),
    }


def subgroup_metrics(
    audit_frame: pd.DataFrame,
    target: np.ndarray,
    probability: np.ndarray,
    *,
    minimum_size: int,
    n_bins: int,
) -> dict[str, list[dict[str, Any]]]:
    working = audit_frame.copy()
    working["_target"] = np.asarray(target, dtype=int)
    working["_probability"] = np.asarray(probability, dtype=float)
    working["business_age_group"] = pd.cut(
        working["business_age_months"],
        [-1, 11, 35, 83, 240],
        labels=["0-11", "12-35", "36-83", "84-240"],
    )
    leverage = working["loan_amount"] / working["annual_revenue"]
    working["leverage_group"] = pd.cut(
        leverage,
        [-np.inf, 0.2, 0.35, 0.6, 1.0, np.inf],
        labels=["<=0.20", "0.20-0.35", "0.35-0.60", "0.60-1.00", ">1.00"],
    )
    working["age_group"] = pd.cut(
        working["age"],
        [17, 29, 39, 49, 59, 70],
        labels=["18-29", "30-39", "40-49", "50-59", "60-70"],
    )
    dimensions = {
        "credit_history": "credit_history",
        "business_age": "business_age_group",
        "leverage": "leverage_group",
        "age_audit_only": "age_group",
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for output_name, column in dimensions.items():
        rows: list[dict[str, Any]] = []
        for group, subset in working.groupby(column, observed=True):
            row: dict[str, Any] = {
                "group": str(group),
                "size": len(subset),
                "positive_rate": float(subset["_target"].mean()),
                "limited_reliability": len(subset) < minimum_size,
                "brier_score": float(brier_score_loss(subset["_target"], subset["_probability"])),
                "ece": expected_calibration_error(
                    subset["_target"].to_numpy(),
                    subset["_probability"].to_numpy(),
                    n_bins=n_bins,
                ),
            }
            if len(subset) >= minimum_size and subset["_target"].nunique() == 2:
                row["roc_auc"] = float(roc_auc_score(subset["_target"], subset["_probability"]))
            else:
                row["roc_auc"] = None
            rows.append(row)
        result[output_name] = rows
    return result


def create_model_figures(
    output_dir: Path,
    target: np.ndarray,
    probabilities: dict[str, np.ndarray],
    metrics: dict[str, dict[str, Any]],
    subgroup_results: dict[str, list[dict[str, Any]]],
    *,
    n_bins: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    colors = ["#555555", "#EF3124", "#7A1FA2", "#1976D2"]

    plt.figure(figsize=(7, 5))
    for (label, probability), color in zip(probabilities.items(), colors, strict=False):
        false_positive, true_positive, _ = roc_curve(target, probability)
        plt.plot(
            false_positive,
            true_positive,
            label=f"{label} ({metrics[label]['roc_auc']:.3f})",
            color=color,
        )
    plt.plot([0, 1], [0, 1], "--", color="#999999", label="Случайный baseline")
    plt.xlabel("False positive rate")
    plt.ylabel("True positive rate")
    plt.title("ROC-кривые на test")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "01_roc_curve.png", dpi=150)
    plt.close()

    plt.figure(figsize=(7, 5))
    for (label, probability), color in zip(probabilities.items(), colors, strict=False):
        precision, recall, _ = precision_recall_curve(target, probability)
        plt.plot(recall, precision, label=f"{label} ({metrics[label]['pr_auc']:.3f})", color=color)
    plt.axhline(float(np.mean(target)), linestyle="--", color="#999999", label="Доля positive")
    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.title("Precision–Recall на test")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "02_precision_recall_curve.png", dpi=150)
    plt.close()

    plt.figure(figsize=(7, 5))
    for (label, probability), color in zip(probabilities.items(), colors, strict=False):
        observed, predicted = calibration_curve(
            target, probability, n_bins=n_bins, strategy="quantile"
        )
        plt.plot(predicted, observed, marker="o", label=label, color=color)
    plt.plot([0, 1], [0, 1], "--", color="#999999", label="Идеальная калибровка")
    plt.xlabel("Средняя прогнозная вероятность", labelpad=12)
    plt.ylabel("Фактическая доля positive")
    plt.title("Калибровочные кривые на test")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "03_calibration_curve.png", dpi=150)
    plt.close()

    plt.figure(figsize=(7, 5))
    for (label, probability), color in zip(probabilities.items(), colors, strict=False):
        plt.hist(probability, bins=30, alpha=0.45, density=True, label=label, color=color)
    plt.xlabel("Прогнозная вероятность")
    plt.ylabel("Плотность")
    plt.title("Распределение прогнозных вероятностей")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "04_probability_distribution.png", dpi=150)
    plt.close()

    labels = list(probabilities)
    fig, axes = plt.subplots(1, len(labels), figsize=(5 * len(labels), 4))
    if len(labels) == 1:
        axes = [axes]
    for axis, label in zip(axes, labels, strict=True):
        matrix = np.asarray(metrics[label]["confusion_matrix"])
        image = axis.imshow(matrix, cmap="Reds")
        for row in range(2):
            for column in range(2):
                axis.text(column, row, str(matrix[row, column]), ha="center", va="center")
        axis.set_title(label)
        axis.set_xlabel("Predicted")
        axis.set_ylabel("Actual")
        axis.set_xticks([0, 1])
        axis.set_yticks([0, 1])
        fig.colorbar(image, ax=axis, fraction=0.046)
    fig.suptitle("Confusion matrix, threshold 0.5")
    fig.tight_layout()
    fig.savefig(output_dir / "05_confusion_matrices.png", dpi=150)
    plt.close(fig)

    metric_names = ["roc_auc", "pr_auc", "f1", "brier_score", "log_loss"]
    x = np.arange(len(metric_names))
    width = 0.8 / len(labels)
    plt.figure(figsize=(9, 5))
    for index, (label, color) in enumerate(zip(labels, colors, strict=False)):
        values = [metrics[label][name] for name in metric_names]
        plt.bar(x + index * width, values, width=width, label=label, color=color)
    plt.xticks(x + width * (len(labels) - 1) / 2, metric_names, rotation=20)
    plt.title("Сравнение основных метрик на test")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "06_metric_comparison.png", dpi=150)
    plt.close()

    history = subgroup_results["credit_history"]
    groups = [row["group"] for row in history]
    auc = [row["roc_auc"] for row in history]
    brier = [row["brier_score"] for row in history]
    positions = np.arange(len(groups))
    fig, axis = plt.subplots(figsize=(8, 5))
    axis.bar(positions - 0.18, auc, width=0.36, label="ROC-AUC", color="#EF3124")
    axis.bar(positions + 0.18, brier, width=0.36, label="Brier", color="#555555")
    axis.set_xticks(positions, groups)
    axis.set_title("Метрики по кредитной истории")
    axis.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "07_subgroup_credit_history.png", dpi=150)
    plt.close(fig)
