"""Latent target model defined in dataset_design.md section 13."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


def sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(values, dtype=float)))


def latent_score(frame: pd.DataFrame, target_config: Mapping[str, Any]) -> np.ndarray:
    """Calculate score from approved application-time fields; age is intentionally unused."""
    revenue = frame["annual_revenue"].to_numpy(dtype=float)
    business_age = frame["business_age_months"].to_numpy(dtype=float)
    loan = frame["loan_amount"].to_numpy(dtype=float)
    term = frame["loan_term_months"].to_numpy(dtype=float)
    collateral = frame["has_collateral"].to_numpy(dtype=bool).astype(float)
    history = frame["credit_history"].astype("string").to_numpy()

    leverage = loan / revenue
    payment_load = 12.0 * leverage / term
    high_load = np.clip(
        (leverage - target_config["high_load_start"]) / target_config["high_load_width"],
        0.0,
        1.0,
    )
    history_effect = np.array(
        [target_config["history_effects"][str(value)] for value in history], dtype=float
    )

    return (
        target_config["intercept"]
        + history_effect
        + target_config["revenue_coefficient"]
        * np.tanh(
            np.log(revenue / target_config["revenue_reference"]) / target_config["revenue_scale"]
        )
        + target_config["business_age_coefficient"]
        * np.tanh(
            (business_age - target_config["business_age_center"])
            / target_config["business_age_scale"]
        )
        + target_config["leverage_coefficient"]
        * np.tanh(np.log(leverage / target_config["leverage_reference"]))
        + target_config["payment_load_coefficient"]
        * np.tanh(np.log(payment_load / target_config["payment_load_reference"]))
        + target_config["collateral_coefficient"] * collateral
        + target_config["long_term_coefficient"] * (term >= target_config["long_term_threshold"])
        + target_config["collateral_high_load_interaction"] * collateral * high_load
        + target_config["bad_history_high_load_interaction"] * (history == "bad") * high_load
        + target_config["new_business_high_load_interaction"]
        * (business_age < target_config["new_business_threshold"])
        * high_load
    )


def simulated_probability(frame: pd.DataFrame, target_config: Mapping[str, Any]) -> np.ndarray:
    return sigmoid(latent_score(frame, target_config))


def sample_approved(
    frame: pd.DataFrame,
    target_config: Mapping[str, Any],
    rng: np.random.Generator,
) -> np.ndarray:
    probability = simulated_probability(frame, target_config)
    return rng.binomial(1, probability).astype(np.int64)
