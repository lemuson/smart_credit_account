"""Causally ordered synthetic application generator."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import GeneratorConfig
from .target import sample_approved, sigmoid


def _round_to(values: np.ndarray, quantum: float) -> np.ndarray:
    return np.rint(values / quantum) * quantum


def _sample_age(
    business_age: np.ndarray,
    config: dict,
    rng: np.random.Generator,
) -> np.ndarray:
    minimum_allowed = 18 + np.ceil(business_age / 12).astype(np.int64)
    age = np.zeros(len(business_age), dtype=np.int64)
    pending = np.arange(len(business_age))
    components = config["components"]
    weights = [part["weight"] for part in components]

    for _ in range(config["max_resamples"]):
        if len(pending) == 0:
            break
        selected = rng.choice(len(components), size=len(pending), p=weights)
        sampled = np.empty(len(pending), dtype=float)
        for component_index, component in enumerate(components):
            mask = selected == component_index
            sampled[mask] = rng.normal(component["mean"], component["std"], mask.sum())
        sampled = np.rint(sampled).astype(np.int64)
        valid = (
            (sampled >= config["minimum"])
            & (sampled <= config["maximum"])
            & (sampled >= minimum_allowed[pending])
        )
        age[pending[valid]] = sampled[valid]
        pending = pending[~valid]
    if len(pending):
        raise RuntimeError(f"Could not sample valid ages for {len(pending)} rows")
    return age


def _generate_batch(
    size: int,
    config: GeneratorConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    values = config.values
    stages = values["business_stages"]
    stage_index = rng.choice(len(stages), size=size, p=[stage["weight"] for stage in stages])
    stage_names = np.array([stage["name"] for stage in stages], dtype=object)[stage_index]

    business_age = np.empty(size, dtype=np.int64)
    for index, stage in enumerate(stages):
        mask = stage_index == index
        left, mode, right = stage["triangular"]
        business_age[mask] = np.rint(rng.triangular(left, mode, right, mask.sum())).astype(np.int64)

    age = _sample_age(business_age, values["age"], rng)

    revenue_config = values["annual_revenue"]
    log_revenue = (
        math.log(revenue_config["base"])
        + revenue_config["business_age_coefficient"] * np.log1p(business_age / 12.0)
        + revenue_config["noise_std"] * rng.normal(size=size)
    )
    revenue = _round_to(np.exp(log_revenue), revenue_config["rounding"])
    revenue = np.clip(revenue, revenue_config["minimum"], revenue_config["maximum"])

    history_config = values["credit_history"]
    categories = np.array(history_config["categories"], dtype=object)
    history = np.empty(size, dtype=object)
    for stage in stages:
        mask = stage_names == stage["name"]
        history[mask] = rng.choice(
            categories,
            size=mask.sum(),
            p=history_config["probabilities_by_stage"][stage["name"]],
        )

    ratio_config = values["requested_load_ratio"]
    ratio_parts = ratio_config["components"]
    ratio_part = rng.choice(len(ratio_parts), size=size, p=[part["weight"] for part in ratio_parts])
    requested_ratio = np.empty(size, dtype=float)
    for index, part in enumerate(ratio_parts):
        mask = ratio_part == index
        requested_ratio[mask] = rng.lognormal(
            mean=math.log(part["median"]), sigma=part["sigma"], size=mask.sum()
        )
    requested_ratio = np.clip(requested_ratio, ratio_config["minimum"], ratio_config["maximum"])

    loan_config = values["loan_amount"]
    loan = _round_to(revenue * requested_ratio, loan_config["rounding"])
    loan = np.clip(loan, loan_config["minimum"], loan_config["maximum"])
    leverage = loan / revenue

    term_config = values["loan_term"]
    raw_term = (
        term_config["intercept"]
        + term_config["loan_coefficient"] * np.log1p(loan / 1_000_000.0)
        + term_config["excess_leverage_coefficient"]
        * np.maximum(leverage - term_config["excess_leverage_threshold"], 0.0)
        + rng.normal(0.0, term_config["noise_std"], size=size)
    )
    allowed_terms = np.asarray(term_config["allowed_months"], dtype=np.int64)
    term = allowed_terms[np.abs(raw_term[:, None] - allowed_terms).argmin(axis=1)]

    collateral_config = values["collateral"]
    collateral_logit = (
        collateral_config["intercept"]
        + collateral_config["loan_coefficient"] * np.log1p(loan / 1_000_000.0)
        + collateral_config["business_age_coefficient"] * np.log1p(business_age / 36.0)
        + collateral_config["high_leverage_coefficient"]
        * (leverage > collateral_config["high_leverage_threshold"])
        + collateral_config["long_term_coefficient"]
        * (term >= collateral_config["long_term_threshold"])
    )
    collateral = rng.binomial(1, sigmoid(collateral_logit)).astype(bool)

    frame = pd.DataFrame(
        {
            "age": age,
            "annual_revenue": revenue.astype(float),
            "credit_history": pd.Categorical(history, categories=categories),
            "business_age_months": business_age,
            "loan_amount": loan.astype(float),
            "has_collateral": collateral,
            "loan_term_months": term.astype(np.int64),
        }
    )
    frame["approved"] = sample_approved(frame, values["target"], rng)
    return frame[values["columns"]]


def generate_dataset(
    config: GeneratorConfig,
    *,
    n_rows: int | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """Generate exactly n unique applications, deduplicated by input features."""
    target_rows = int(n_rows if n_rows is not None else config["n_rows"])
    selected_seed = int(seed if seed is not None else config["generation_seed"])
    if target_rows <= 0:
        raise ValueError("n_rows must be positive")

    rng = np.random.default_rng(selected_seed)
    feature_columns = config["feature_columns"]
    unique: pd.DataFrame | None = None
    batch_size = max(1_000, math.ceil(target_rows * 1.05))

    for attempt in range(1, int(config["max_generation_batches"]) + 1):
        missing = target_rows - (0 if unique is None else len(unique))
        if missing <= 0:
            break
        generated = _generate_batch(
            max(batch_size if attempt == 1 else 1_000, missing), config, rng
        )
        unique = generated if unique is None else pd.concat([unique, generated], ignore_index=True)
        unique = unique.drop_duplicates(subset=feature_columns, keep="first", ignore_index=True)
    if unique is None or len(unique) < target_rows:
        raise RuntimeError(
            f"Generated only {0 if unique is None else len(unique)} unique applications after "
            f"{config['max_generation_batches']} batches; requested {target_rows}"
        )

    result = unique.iloc[:target_rows].copy()
    result = result.astype(
        {
            "age": "int64",
            "annual_revenue": "float64",
            "business_age_months": "int64",
            "loan_amount": "float64",
            "has_collateral": "bool",
            "loan_term_months": "int64",
            "approved": "int64",
        }
    )
    result["credit_history"] = pd.Categorical(
        result["credit_history"], categories=config["credit_history"]["categories"]
    )
    return result.reset_index(drop=True)
