"""Hard, statistical, fairness, monotonicity and seed-stability checks."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from .config import GeneratorConfig
from .generator import generate_dataset
from .split import assert_disjoint_splits
from .target import latent_score, simulated_probability


@dataclass
class ValidationResult:
    hard_errors: list[str]
    warnings: list[str]
    metrics: dict[str, Any]

    @property
    def is_valid(self) -> bool:
        return not self.hard_errors

    def raise_for_errors(self) -> None:
        if self.hard_errors:
            raise ValueError("Hard dataset validation failed:\n- " + "\n- ".join(self.hard_errors))


def _outside(value: float, bounds: list[float]) -> bool:
    return not bounds[0] <= value <= bounds[1]


def validate_dataset(
    frame: pd.DataFrame,
    config: GeneratorConfig,
    *,
    expected_rows: int | None = None,
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    expected_columns = config["columns"]
    if list(frame.columns) != expected_columns:
        errors.append(f"Columns must be exactly {expected_columns}; got {list(frame.columns)}")
        return ValidationResult(errors, warnings, {})

    required_rows = config["n_rows"] if expected_rows is None else expected_rows
    if len(frame) != required_rows:
        errors.append(f"Expected {required_rows} rows; got {len(frame)}")
    if frame.isna().any().any():
        errors.append("Dataset contains missing values")
    numeric = frame.select_dtypes(include=[np.number])
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        errors.append("Dataset contains non-finite numeric values")

    for column in ("age", "business_age_months", "loan_term_months", "approved"):
        if not ptypes.is_integer_dtype(frame[column]):
            errors.append(f"{column} must use an integer dtype")
    for column in ("annual_revenue", "loan_amount"):
        if not ptypes.is_float_dtype(frame[column]):
            errors.append(f"{column} must use a floating-point dtype")
    if not ptypes.is_bool_dtype(frame["has_collateral"]):
        errors.append("has_collateral must use a bool dtype")
    if not (
        isinstance(frame["credit_history"].dtype, pd.CategoricalDtype)
        or ptypes.is_string_dtype(frame["credit_history"])
    ):
        errors.append("credit_history must use a categorical or string dtype")

    checks = {
        "age is within 18..70": frame["age"].between(18, 70).all(),
        "business_age_months is within 0..240": frame["business_age_months"].between(0, 240).all(),
        "business age is logically compatible with owner age": (
            frame["business_age_months"] <= (frame["age"] - 18) * 12
        ).all(),
        "annual_revenue is within configured bounds": frame["annual_revenue"]
        .between(config["annual_revenue"]["minimum"], config["annual_revenue"]["maximum"])
        .all(),
        "loan_amount is within configured bounds": frame["loan_amount"]
        .between(config["loan_amount"]["minimum"], config["loan_amount"]["maximum"])
        .all(),
        "loan_term_months is allowed": frame["loan_term_months"]
        .isin(config["loan_term"]["allowed_months"])
        .all(),
        "credit_history is allowed": frame["credit_history"]
        .isin(config["credit_history"]["categories"])
        .all(),
        "approved is binary": frame["approved"].isin([0, 1]).all(),
    }
    for description, passed in checks.items():
        if not passed:
            errors.append(description)

    if frame.duplicated().any():
        errors.append(f"Found {int(frame.duplicated().sum())} exact row duplicates")
    feature_duplicates = int(frame.duplicated(subset=config["feature_columns"]).sum())
    if feature_duplicates:
        errors.append(f"Found {feature_duplicates} duplicate input-feature tuples")

    leverage = frame["loan_amount"] / frame["annual_revenue"]
    max_leverage = float(leverage.max())
    if max_leverage > config["statistical_ranges"]["max_loan_to_revenue"]:
        errors.append(f"Maximum loan/revenue ratio is {max_leverage:.4f}, above 2.6")

    approval_rate = float(frame["approved"].mean())
    history_shares = {
        category: float((frame["credit_history"] == category).mean())
        for category in config["credit_history"]["categories"]
    }
    collateral_share = float(frame["has_collateral"].mean())
    metrics: dict[str, Any] = {
        "row_count": len(frame),
        "approval_rate": approval_rate,
        "class_counts": {
            str(key): int(value)
            for key, value in frame["approved"].value_counts().sort_index().items()
        },
        "credit_history_shares": history_shares,
        "collateral_share": collateral_share,
        "median_annual_revenue": float(frame["annual_revenue"].median()),
        "median_loan_amount": float(frame["loan_amount"].median()),
        "median_loan_to_revenue": float(leverage.median()),
        "max_loan_to_revenue": max_leverage,
    }
    ranges = config["statistical_ranges"]
    diagnostic_values = {
        "approval_rate": (approval_rate, ranges["approval_rate"]),
        "collateral_share": (collateral_share, ranges["collateral_share"]),
        "median_annual_revenue": (
            metrics["median_annual_revenue"],
            ranges["median_annual_revenue"],
        ),
        "median_loan_amount": (metrics["median_loan_amount"], ranges["median_loan_amount"]),
        "median_loan_to_revenue": (
            metrics["median_loan_to_revenue"],
            ranges["median_loan_to_revenue"],
        ),
    }
    diagnostic_values.update(
        {
            f"credit_history.{category}": (share, ranges["credit_history"][category])
            for category, share in history_shares.items()
        }
    )
    for name, (value, bounds) in diagnostic_values.items():
        if _outside(value, bounds):
            warnings.append(f"{name}={value:.6g} is outside diagnostic range {bounds}")

    history_rates = frame.groupby("credit_history", observed=True)["approved"].mean().to_dict()
    metrics["approval_by_credit_history"] = {str(k): float(v) for k, v in history_rates.items()}
    if not all(history_rates["good"] > history_rates[item] for item in ("average", "none", "bad")):
        warnings.append("good credit history does not have the highest approval rate")
    if history_rates["bad"] != min(history_rates.values()):
        warnings.append("bad credit history does not have the lowest approval rate")

    stage = pd.cut(
        frame["business_age_months"],
        bins=[-1, 11, 35, 83, 240],
        labels=["new", "developing", "stable", "mature"],
    )
    stage_rates = frame.groupby(stage, observed=True)["approved"].mean()
    metrics["approval_by_business_stage"] = {str(k): float(v) for k, v in stage_rates.items()}
    if not stage_rates.is_monotonic_increasing:
        warnings.append("Approval rate is not increasing across business-age stages")

    low_rate = float(frame.loc[leverage <= leverage.quantile(0.25), "approved"].mean())
    high_rate = float(frame.loc[leverage >= leverage.quantile(0.75), "approved"].mean())
    metrics["approval_low_leverage_quartile"] = low_rate
    metrics["approval_high_leverage_quartile"] = high_rate
    if high_rate >= low_rate:
        warnings.append(
            "High-leverage quartile is not approved less often than low-leverage quartile"
        )
    if not ((frame["has_collateral"] & (frame["approved"] == 0)).any()):
        warnings.append("No rejected applications with collateral")
    if not (((~frame["has_collateral"]) & (frame["approved"] == 1)).any()):
        warnings.append("No approved applications without collateral")
    return ValidationResult(errors, warnings, metrics)


def validate_splits(splits: dict[str, pd.DataFrame], config: GeneratorConfig) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    expected_names = {"train", "validation", "test"}
    if set(splits) != expected_names:
        errors.append(f"Split names must be {sorted(expected_names)}; got {sorted(splits)}")
        return ValidationResult(errors, warnings, {})

    for name, expected_size in config["split"].items():
        if len(splits[name]) != expected_size:
            errors.append(f"{name} has {len(splits[name])} rows; expected {expected_size}")
        if list(splits[name].columns) != config["columns"]:
            errors.append(f"{name} has an invalid schema")
        if splits[name].duplicated(subset=config["feature_columns"]).any():
            errors.append(f"{name} contains duplicate feature tuples")
    try:
        assert_disjoint_splits(splits, config["feature_columns"])
    except ValueError as exc:
        errors.append(str(exc))

    combined = pd.concat(splits.values(), ignore_index=True)
    overall_approval = float(combined["approved"].mean())
    overall_history = {
        category: float((combined["credit_history"] == category).mean())
        for category in config["credit_history"]["categories"]
    }
    metrics: dict[str, Any] = {}
    for name, frame in splits.items():
        approval = float(frame["approved"].mean())
        history = {
            category: float((frame["credit_history"] == category).mean())
            for category in config["credit_history"]["categories"]
        }
        terms = {int(value) for value in frame["loan_term_months"].unique()}
        missing_rare_terms = sorted({48, 60} - terms)
        if missing_rare_terms:
            warnings.append(f"{name} is missing rare terms {missing_rare_terms}")
        if abs(approval - overall_approval) > 0.01:
            warnings.append(f"{name} approval-rate delta exceeds 1 percentage point")
        for category, share in history.items():
            if abs(share - overall_history[category]) > 0.01:
                warnings.append(f"{name} {category} share delta exceeds 1 percentage point")
        metrics[name] = {
            "row_count": len(frame),
            "approval_rate": approval,
            "credit_history_shares": history,
            "loan_term_counts": {
                str(key): int(value)
                for key, value in frame["loan_term_months"].value_counts().sort_index().items()
            },
            "annual_revenue": {
                "median": float(frame["annual_revenue"].median()),
                "p10": float(frame["annual_revenue"].quantile(0.1)),
                "p90": float(frame["annual_revenue"].quantile(0.9)),
            },
            "loan_amount": {
                "median": float(frame["loan_amount"].median()),
                "p10": float(frame["loan_amount"].quantile(0.1)),
                "p90": float(frame["loan_amount"].quantile(0.9)),
            },
        }
    return ValidationResult(errors, warnings, metrics)


def fairness_audit(frame: pd.DataFrame, config: GeneratorConfig) -> dict[str, Any]:
    age_groups = pd.cut(
        frame["age"],
        bins=[17, 29, 39, 49, 59, 70],
        labels=["18-29", "30-39", "40-49", "50-59", "60-70"],
        include_lowest=True,
    )
    rates = frame.groupby(age_groups, observed=True)["approved"].agg(["count", "mean"])
    correlation = float(frame["age"].corr(frame["approved"]))

    minimum_age = 18 + np.ceil(frame["business_age_months"] / 12).astype(int)
    counterfactual = frame.copy()
    counterfactual["age"] = np.where(frame["age"] == minimum_age, 70, minimum_age)
    original_probability = simulated_probability(frame, config["target"])
    changed_probability = simulated_probability(counterfactual, config["target"])
    max_probability_change = float(np.max(np.abs(original_probability - changed_probability)))

    conditional = frame.assign(
        age_group=age_groups,
        business_band=pd.cut(frame["business_age_months"], [-1, 11, 35, 83, 240]),
        revenue_band=pd.qcut(frame["annual_revenue"], 4, duplicates="drop"),
    )
    comparable_columns = ["business_band", "revenue_band", "credit_history"]
    expected_within_stratum = conditional.groupby(comparable_columns, observed=True)[
        "approved"
    ].transform("mean")
    conditional = conditional.assign(
        approval_residual=conditional["approved"] - expected_within_stratum
    )
    adjusted_age = conditional.groupby("age_group", observed=True)["approval_residual"].agg(
        ["count", "mean"]
    )
    adjusted_gap = float(adjusted_age["mean"].max() - adjusted_age["mean"].min())

    return {
        "age_in_ml_feature_allow_list": "age" in config["ml_feature_allow_list"],
        "age_target_correlation": correlation,
        "correlation_alert": abs(correlation)
        > config["statistical_ranges"]["age_target_correlation_alert"],
        "approval_by_age_group": {
            str(index): {"count": int(row["count"]), "approval_rate": float(row["mean"])}
            for index, row in rates.iterrows()
        },
        "counterfactual_max_probability_change": max_probability_change,
        "conditional_strata_compared": int(
            conditional.groupby(comparable_columns, observed=True).ngroups
        ),
        "conditional_adjusted_age_group_residuals": {
            str(index): {"count": int(row["count"]), "mean_residual": float(row["mean"])}
            for index, row in adjusted_age.iterrows()
        },
        "conditional_adjusted_age_group_gap": adjusted_gap,
        "note": "Diagnostics cannot establish fairness or rule out indirect effects.",
    }


def monotonic_tests(config: GeneratorConfig) -> dict[str, Any]:
    base = pd.DataFrame(
        {
            "age": [42],
            "annual_revenue": [5_000_000.0],
            "credit_history": ["good"],
            "business_age_months": [36],
            "loan_amount": [1_500_000.0],
            "has_collateral": [False],
            "loan_term_months": [24],
        }
    )
    base_score = float(latent_score(base, config["target"])[0])

    def score_with(**updates: Any) -> float:
        changed = base.copy()
        for column, value in updates.items():
            changed[column] = value
        return float(latent_score(changed, config["target"])[0])

    history_scores = [score_with(credit_history=value) for value in ("good", "average", "bad")]
    results = {
        "larger_loan_does_not_raise_score": score_with(loan_amount=3_000_000.0) <= base_score,
        "worse_history_does_not_raise_score": all(
            left >= right for left, right in pairwise(history_scores)
        ),
        "collateral_does_not_lower_score": score_with(has_collateral=True) >= base_score,
        "older_business_does_not_lower_score": score_with(business_age_months=72) >= base_score,
        "age_does_not_change_score": score_with(age=60) == base_score,
        "term_24_score": base_score,
        "term_60_score": score_with(loan_term_months=60),
        "term_note": (
            "No global monotonicity assertion: payment load and long-term penalty compete."
        ),
    }
    results["all_required_passed"] = all(
        results[key]
        for key in (
            "larger_loan_does_not_raise_score",
            "worse_history_does_not_raise_score",
            "collateral_does_not_lower_score",
            "older_business_does_not_lower_score",
            "age_does_not_change_score",
        )
    )
    return results


def seed_stability(config: GeneratorConfig, base_frame: pd.DataFrame) -> dict[str, Any]:
    seeds = config["stability"]["additional_seeds"]

    def summary(frame: pd.DataFrame) -> dict[str, Any]:
        leverage = frame["loan_amount"] / frame["annual_revenue"]
        stage = pd.cut(
            frame["business_age_months"],
            [-1, 11, 35, 83, 240],
            labels=["new", "developing", "stable", "mature"],
        )
        return {
            "approval_rate": float(frame["approved"].mean()),
            "history_shares": {
                category: float((frame["credit_history"] == category).mean())
                for category in config["credit_history"]["categories"]
            },
            "collateral_share": float(frame["has_collateral"].mean()),
            "median_annual_revenue": float(frame["annual_revenue"].median()),
            "median_loan_amount": float(frame["loan_amount"].median()),
            "p90_annual_revenue": float(frame["annual_revenue"].quantile(0.9)),
            "p90_loan_amount": float(frame["loan_amount"].quantile(0.9)),
            "age_target_correlation": float(frame["age"].corr(frame["approved"])),
            "history_rates": {
                str(k): float(v)
                for k, v in frame.groupby("credit_history", observed=True)["approved"]
                .mean()
                .items()
            },
            "stage_rates": {
                str(k): float(v)
                for k, v in frame.groupby(stage, observed=True)["approved"].mean().items()
            },
            "median_leverage": float(leverage.median()),
        }

    base = summary(base_frame)
    runs: list[dict[str, Any]] = []
    failures: list[str] = []
    stability = config["stability"]
    for seed in seeds:
        current = summary(generate_dataset(config, seed=seed))
        current["seed"] = seed
        runs.append(current)
        if abs(current["approval_rate"] - base["approval_rate"]) > stability["max_rate_delta"]:
            failures.append(f"seed {seed}: approval-rate delta exceeds tolerance")
        if (
            abs(current["collateral_share"] - base["collateral_share"])
            > stability["max_rate_delta"]
        ):
            failures.append(f"seed {seed}: collateral-share delta exceeds tolerance")
        for category in config["credit_history"]["categories"]:
            if (
                abs(current["history_shares"][category] - base["history_shares"][category])
                > stability["max_rate_delta"]
            ):
                failures.append(f"seed {seed}: {category} share delta exceeds tolerance")
        for metric in ("median_annual_revenue", "median_loan_amount"):
            if abs(current[metric] / base[metric] - 1) > stability["max_median_relative_delta"]:
                failures.append(f"seed {seed}: {metric} relative delta exceeds tolerance")
        for metric in ("p90_annual_revenue", "p90_loan_amount"):
            if abs(current[metric] / base[metric] - 1) > stability["max_p90_relative_delta"]:
                failures.append(f"seed {seed}: {metric} relative delta exceeds tolerance")
        history_rates = current["history_rates"]
        if history_rates["good"] != max(history_rates.values()) or history_rates["bad"] != min(
            history_rates.values()
        ):
            failures.append(f"seed {seed}: credit-history direction changed")
        if list(current["stage_rates"].values()) != sorted(current["stage_rates"].values()):
            failures.append(f"seed {seed}: business-stage direction changed")
        if (
            abs(current["age_target_correlation"])
            > config["statistical_ranges"]["age_target_correlation_alert"]
        ):
            failures.append(f"seed {seed}: age correlation exceeded diagnostic threshold")
    return {"base": base, "runs": runs, "failures": failures, "passed": not failures}
