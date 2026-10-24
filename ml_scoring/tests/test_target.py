from __future__ import annotations

import math

import pandas as pd
import pytest
from ml_scoring.target import latent_score, simulated_probability
from ml_scoring.validation import monotonic_tests


def _application() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [40],
            "annual_revenue": [5_000_000.0],
            "credit_history": ["average"],
            "business_age_months": [36],
            "loan_amount": [1_500_000.0],
            "has_collateral": [False],
            "loan_term_months": [24],
        }
    )


def test_probability_is_sigmoid_of_score(config):
    frame = _application()
    score = latent_score(frame, config["target"])[0]
    probability = simulated_probability(frame, config["target"])[0]
    assert 0 < probability < 1
    assert probability == pytest.approx(1 / (1 + math.exp(-score)))


def test_required_monotonic_directions(config):
    result = monotonic_tests(config)
    assert result["all_required_passed"]


def test_age_is_counterfactually_invariant(config):
    young = _application()
    older = young.copy()
    older["age"] = 65
    assert latent_score(young, config["target"])[0] == latent_score(older, config["target"])[0]
