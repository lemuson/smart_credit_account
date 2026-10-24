#!/usr/bin/env python3
"""Validate generated CSV files, run EDA and write the quality report."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ml-scoring-matplotlib"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(PROJECT_DIR / "src"))

from ml_scoring.config import load_config  # noqa: E402
from ml_scoring.split import assert_disjoint_splits  # noqa: E402
from ml_scoring.validation import (  # noqa: E402
    fairness_audit,
    monotonic_tests,
    seed_stability,
    validate_dataset,
    validate_splits,
)

COLORS = {"primary": "#EF3124", "secondary": "#333333", "muted": "#B8B8B8"}


def _read_csv(path: Path, categories: list[str]) -> pd.DataFrame:
    frame = pd.read_csv(
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
    frame["credit_history"] = pd.Categorical(frame["credit_history"], categories=categories)
    return frame


def _save_current(path: Path) -> None:
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()


def _bar(series: pd.Series, title: str, ylabel: str, path: Path) -> None:
    plt.figure(figsize=(7, 4.5))
    series.plot(kind="bar", color=COLORS["primary"])
    plt.title(title)
    plt.ylabel(ylabel)
    plt.xticks(rotation=0)
    _save_current(path)


def create_figures(frame: pd.DataFrame, figures_dir: Path) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)

    for column, title, filename in (
        ("annual_revenue", "Распределение годовой выручки", "01_annual_revenue.png"),
        ("loan_amount", "Распределение суммы кредита", "02_loan_amount.png"),
    ):
        values = frame[column]
        positive = values[values > 0]
        bins = np.logspace(np.log10(positive.min()), np.log10(positive.max()), 45)
        plt.figure(figsize=(7, 4.5))
        plt.hist(positive, bins=bins, color=COLORS["primary"], alpha=0.85)
        plt.xscale("log")
        plt.title(title)
        plt.xlabel("Рубли, логарифмическая шкала")
        plt.ylabel("Количество заявок")
        _save_current(figures_dir / filename)

    for column, title, filename, bins in (
        (
            "business_age_months",
            "Срок существования бизнеса",
            "03_business_age.png",
            40,
        ),
        ("age", "Возраст предпринимателей", "04_age.png", range(18, 72, 2)),
    ):
        plt.figure(figsize=(7, 4.5))
        plt.hist(frame[column], bins=bins, color=COLORS["primary"], alpha=0.85)
        plt.title(title)
        plt.ylabel("Количество заявок")
        _save_current(figures_dir / filename)

    _bar(
        frame["credit_history"].value_counts(sort=False),
        "Категории кредитной истории",
        "Количество заявок",
        figures_dir / "05_credit_history.png",
    )
    _bar(
        frame["has_collateral"].map({False: "Нет", True: "Есть"}).value_counts(),
        "Наличие залога",
        "Количество заявок",
        figures_dir / "06_collateral.png",
    )
    _bar(
        frame["loan_term_months"].value_counts().sort_index(),
        "Сроки кредитования",
        "Количество заявок",
        figures_dir / "07_loan_term.png",
    )
    _bar(
        frame["approved"].map({0: "Отклонено", 1: "Одобрено"}).value_counts(),
        "Баланс целевой переменной",
        "Количество заявок",
        figures_dir / "08_target_balance.png",
    )

    numerical = frame[
        [
            "age",
            "annual_revenue",
            "business_age_months",
            "loan_amount",
            "has_collateral",
            "loan_term_months",
            "approved",
        ]
    ].astype(float)
    correlation = numerical.corr()
    plt.figure(figsize=(8, 6.5))
    image = plt.imshow(correlation, vmin=-1, vmax=1, cmap="coolwarm")
    plt.colorbar(image, label="Корреляция")
    plt.xticks(range(len(correlation)), correlation.columns, rotation=45, ha="right")
    plt.yticks(range(len(correlation)), correlation.columns)
    plt.title("Корреляционная матрица")
    _save_current(figures_dir / "09_correlation_matrix.png")

    _bar(
        frame.groupby("credit_history", observed=True)["approved"].mean(),
        "Approval rate по кредитной истории",
        "Доля approved = 1",
        figures_dir / "10_approval_by_history.png",
    )
    business_bins = pd.cut(
        frame["business_age_months"],
        [-1, 11, 35, 83, 240],
        labels=["0–11", "12–35", "36–83", "84–240"],
    )
    _bar(
        frame.groupby(business_bins, observed=True)["approved"].mean(),
        "Approval rate по сроку работы бизнеса",
        "Доля approved = 1",
        figures_dir / "11_approval_by_business_age.png",
    )
    leverage = frame["loan_amount"] / frame["annual_revenue"]
    leverage_bins = pd.cut(
        leverage,
        [-np.inf, 0.2, 0.35, 0.6, 1.0, np.inf],
        labels=["≤0.20", "0.20–0.35", "0.35–0.60", "0.60–1.00", ">1.00"],
    )
    _bar(
        frame.groupby(leverage_bins, observed=True)["approved"].mean(),
        "Approval rate по отношению кредита к выручке",
        "Доля approved = 1",
        figures_dir / "12_approval_by_leverage.png",
    )
    age_bins = pd.cut(
        frame["age"],
        [17, 29, 39, 49, 59, 70],
        labels=["18–29", "30–39", "40–49", "50–59", "60–70"],
    )
    _bar(
        frame.groupby(age_bins, observed=True)["approved"].mean(),
        "Approval rate по возрастным группам",
        "Доля approved = 1",
        figures_dir / "13_approval_by_age.png",
    )


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def write_report(
    frame: pd.DataFrame,
    validation: Any,
    split_validation: Any,
    fairness: dict[str, Any],
    monotonic: dict[str, Any],
    stability: dict[str, Any],
    output: Path,
) -> None:
    numeric_columns = [
        "age",
        "annual_revenue",
        "business_age_months",
        "loan_amount",
        "loan_term_months",
        "approved",
    ]
    summary = frame[numeric_columns].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9, 0.99]).T
    summary = summary[["min", "max", "mean", "50%", "10%", "25%", "75%", "90%", "99%"]]
    history = frame["credit_history"].value_counts(sort=False)
    term_counts = frame["loan_term_months"].value_counts().sort_index()

    lines = [
        "# Отчёт о валидации синтетического кредитного датасета",
        "",
        "## Итог",
        "",
        f"Сформировано **{len(frame):,}** уникальных заявок. "
        f"Доля `approved = 1` — **{frame['approved'].mean():.2%}**. "
        f"Hard validation: **{'PASS' if validation.is_valid else 'FAIL'}**. "
        f"Проверка устойчивости: **{'PASS' if stability['passed'] else 'FAIL'}**.",
        "",
        (
            "Датасет является демонстрационным и не отражает кредитную политику "
            "или реальные данные банка."
        ),
        "",
        "## Числовые распределения",
        "",
        "| Признак | Min | Max | Mean | Median | P10 | P25 | P75 | P90 | P99 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in summary.iterrows():
        lines.append("| " + name + " | " + " | ".join(_fmt(value) for value in row) + " |")

    lines.extend(
        [
            "",
            "## Категориальные распределения",
            "",
            "| Credit history | Количество | Доля | Approval rate |",
            "|---|---:|---:|---:|",
        ]
    )
    history_approval = frame.groupby("credit_history", observed=True)["approved"].mean()
    for category, count in history.items():
        lines.append(
            f"| {category} | {count} | {count / len(frame):.2%} | "
            f"{history_approval[category]:.2%} |"
        )
    lines.extend(
        [
            "",
            f"Доля заявок с залогом: **{frame['has_collateral'].mean():.2%}**.",
            "",
            "| Срок, мес. | Количество | Доля |",
            "|---:|---:|---:|",
        ]
    )
    for term, count in term_counts.items():
        lines.append(f"| {term} | {count} | {count / len(frame):.2%} |")

    lines.extend(
        [
            "",
            "## Качество разбиения",
            "",
            "| Выборка | Строк | Approval | Revenue median | Revenue P90 | "
            "Loan median | Loan P90 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, values in split_validation.metrics.items():
        lines.append(
            f"| {name} | {values['row_count']} | {values['approval_rate']:.2%} | "
            f"{values['annual_revenue']['median']:,.0f} | "
            f"{values['annual_revenue']['p90']:,.0f} | "
            f"{values['loan_amount']['median']:,.0f} | "
            f"{values['loan_amount']['p90']:,.0f} |"
        )
    lines.append(
        "Пересечений feature-наборов между выборками нет; сроки 48 и 60 месяцев "
        "присутствуют в каждой выборке."
    )

    lines.extend(
        [
            "",
            "## Корреляции и fairness-аудит",
            "",
            f"Корреляция возраста и target: **{fairness['age_target_correlation']:.4f}**. "
            f"Диагностический порог превышен: **{fairness['correlation_alert']}**.",
            f"Максимальное изменение вероятности в контрфактическом тесте возраста: "
            f"**{fairness['counterfactual_max_probability_change']:.3g}**.",
            (
                "Возраст присутствует в ML allow-list: "
                f"**{fairness['age_in_ml_feature_allow_list']}**."
            ),
            f"Условно сопоставлено страт: **{fairness['conditional_strata_compared']}**; "
            f"разрыв скорректированных средних между возрастными группами: "
            f"**{fairness['conditional_adjusted_age_group_gap']:.2%}**.",
            "",
            "| Возрастная группа | Количество | Approval rate |",
            "|---|---:|---:|",
        ]
    )
    for group, values in fairness["approval_by_age_group"].items():
        lines.append(f"| {group} | {values['count']} | {values['approval_rate']:.2%} |")
    lines.extend(
        [
            "",
            "Отсутствие возраста в score и низкая корреляция не доказывают справедливость: "
            "сохраняется косвенная связь возраста со сроком существования бизнеса.",
            "",
            "## Monotonic perturbation tests",
            "",
        ]
    )
    for key, value in monotonic.items():
        if key in {"term_24_score", "term_60_score", "term_note", "all_required_passed"}:
            continue
        lines.append(f"- `{key}`: {'PASS' if value else 'FAIL'}")
    lines.append(
        f"- Итог обязательных проверок: {'PASS' if monotonic['all_required_passed'] else 'FAIL'}"
    )
    lines.append(f"- Срок кредита: {monotonic['term_note']}")

    lines.extend(["", "## Устойчивость по seed", ""])
    lines.append("| Seed | Approval | Collateral | Revenue median | Loan median | Age corr |")
    lines.append("|---:|---:|---:|---:|---:|---:|")
    base = stability["base"]
    lines.append(
        f"| base | {base['approval_rate']:.2%} | {base['collateral_share']:.2%} | "
        f"{base['median_annual_revenue']:,.0f} | {base['median_loan_amount']:,.0f} | "
        f"{base['age_target_correlation']:.4f} |"
    )
    for run in stability["runs"]:
        lines.append(
            f"| {run['seed']} | {run['approval_rate']:.2%} | {run['collateral_share']:.2%} | "
            f"{run['median_annual_revenue']:,.0f} | {run['median_loan_amount']:,.0f} | "
            f"{run['age_target_correlation']:.4f} |"
        )

    lines.extend(["", "## Проверки и отклонения", ""])
    if validation.hard_errors:
        lines.extend(f"- FAIL (hard): {item}" for item in validation.hard_errors)
    else:
        lines.append("- PASS: схема, типы, диапазоны, уникальность и отсутствие leakage-полей.")
    if validation.warnings:
        lines.extend(f"- WARNING: {item}" for item in validation.warnings)
    else:
        lines.append(
            "- PASS: все статистические показатели находятся в диагностических диапазонах."
        )
    if split_validation.hard_errors:
        lines.extend(f"- FAIL (split): {item}" for item in split_validation.hard_errors)
    elif split_validation.warnings:
        lines.extend(f"- WARNING (split): {item}" for item in split_validation.warnings)
    else:
        lines.append("- PASS: размеры, стратификация, редкие сроки и непересечение splits.")
    if stability["failures"]:
        lines.extend(f"- FAIL (stability): {item}" for item in stability["failures"])
    else:
        lines.append("- PASS: пять дополнительных seeds уложились в допуски устойчивости.")

    lines.extend(
        [
            "",
            "## Интерпретация EDA",
            "",
            "Выручка и сумма кредита имеют ожидаемую правостороннюю асимметрию. "
            "Approval rate выше при хорошей кредитной истории и большем сроке работы бизнеса, "
            "а при высокой доле кредита к выручке снижается. Оба класса сохраняются в крупных "
            "группах. Редкие сроки 48 и 60 месяцев присутствуют в данных.",
            "",
            "## Ограничения",
            "",
            "Данные полностью синтетические. В них отсутствуют отрасль, регион, прибыль, "
            "существующие обязательства, цель кредита и стоимость залога. Формула target "
            "задаёт искусственный мир, поэтому будущие ML-метрики не переносятся "
            "на реальные заявки. Clipping создаёт накопления на границах, а независимость "
            "строк упрощает реальную структуру клиентов.",
            "",
            "## Заключение",
            "",
            (
                "Датасет готов к следующему этапу экспериментального обучения: hard validation, "
                "monotonic tests и проверки устойчивости пройдены. Test следует оставить закрытым."
                if validation.is_valid and monotonic["all_required_passed"] and stability["passed"]
                else "Переходить к обучению пока нельзя: устраните проваленные проверки выше."
            ),
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    config = load_config(PROJECT_DIR / "configs" / "generator_v1.yaml")
    paths = {
        "train": PROJECT_DIR / "data" / "synthetic_credit_train.csv",
        "validation": PROJECT_DIR / "data" / "synthetic_credit_val.csv",
        "test": PROJECT_DIR / "data" / "synthetic_credit_test.csv",
    }
    splits = {
        name: _read_csv(path, config["credit_history"]["categories"])
        for name, path in paths.items()
    }
    assert_disjoint_splits(splits, config["feature_columns"])
    frame = pd.concat(splits.values(), ignore_index=True)
    frame["credit_history"] = pd.Categorical(
        frame["credit_history"], categories=config["credit_history"]["categories"]
    )
    validation = validate_dataset(frame, config)
    validation.raise_for_errors()
    split_validation = validate_splits(splits, config)
    split_validation.raise_for_errors()
    fairness = fairness_audit(frame, config)
    monotonic = monotonic_tests(config)
    stability = seed_stability(config, frame)
    create_figures(frame, PROJECT_DIR / "reports" / "figures")
    write_report(
        frame,
        validation,
        split_validation,
        fairness,
        monotonic,
        stability,
        PROJECT_DIR / "docs" / "dataset_validation.md",
    )
    report_data = {
        "validation": {
            "hard_errors": validation.hard_errors,
            "warnings": validation.warnings,
            "metrics": validation.metrics,
        },
        "split_validation": {
            "hard_errors": split_validation.hard_errors,
            "warnings": split_validation.warnings,
            "metrics": split_validation.metrics,
        },
        "fairness": fairness,
        "monotonic": monotonic,
        "stability": stability,
    }
    (PROJECT_DIR / "reports" / "validation_results.json").write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"EDA complete: {len(list((PROJECT_DIR / 'reports' / 'figures').glob('*.png')))} "
        f"figures; hard errors={len(validation.hard_errors)}; "
        f"warnings={len(validation.warnings)}; stability failures={len(stability['failures'])}"
    )


if __name__ == "__main__":
    main()
