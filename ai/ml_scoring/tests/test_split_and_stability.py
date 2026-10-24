from __future__ import annotations

from ml_scoring.split import assert_disjoint_splits, stratified_split
from ml_scoring.validation import seed_stability, validate_splits


def test_split_sizes_stratification_and_disjointness(full_dataset, config):
    splits = stratified_split(full_dataset, config)
    assert {name: len(frame) for name, frame in splits.items()} == {
        "train": 14_000,
        "validation": 3_000,
        "test": 3_000,
    }
    assert_disjoint_splits(splits, config["feature_columns"])
    overall = full_dataset.groupby(["approved", "credit_history"], observed=True).size() / len(
        full_dataset
    )
    for frame in splits.values():
        current = frame.groupby(["approved", "credit_history"], observed=True).size() / len(frame)
        assert (current.sub(overall).abs() < 0.01).all()
        assert {48, 60} <= set(frame["loan_term_months"])
    validation = validate_splits(splits, config)
    assert validation.hard_errors == []
    assert validation.warnings == []


def test_seed_stability(full_dataset, config):
    result = seed_stability(config, full_dataset)
    assert len(result["runs"]) == 5
    assert result["failures"] == []
