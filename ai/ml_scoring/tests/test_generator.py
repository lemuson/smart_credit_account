from __future__ import annotations

import pandas as pd
from ml_scoring.generator import generate_dataset


def test_generator_returns_only_public_columns(config):
    frame = generate_dataset(config, n_rows=1_000)
    assert list(frame.columns) == config["columns"]
    assert len(frame) == 1_000
    assert not frame.duplicated(subset=config["feature_columns"]).any()


def test_feature_ranges_and_relationships(full_dataset, config):
    frame = full_dataset
    assert frame["age"].between(18, 70).all()
    assert frame["business_age_months"].between(0, 240).all()
    assert (frame["business_age_months"] <= (frame["age"] - 18) * 12).all()
    assert frame["annual_revenue"].between(300_000, 120_000_000).all()
    assert frame["loan_amount"].between(100_000, 30_000_000).all()
    assert set(frame["loan_term_months"]) <= set(config["loan_term"]["allowed_months"])
    assert set(frame["credit_history"].astype(str)) == set(config["credit_history"]["categories"])


def test_same_seed_is_identical_and_different_seed_changes_rows(config):
    first = generate_dataset(config, n_rows=500, seed=123)
    second = generate_dataset(config, n_rows=500, seed=123)
    other = generate_dataset(config, n_rows=500, seed=124)
    pd.testing.assert_frame_equal(first, second)
    assert not first.equals(other)
