"""Deterministic exact-size stratified dataset splitting."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import GeneratorConfig


def _hamilton_allocation(counts: np.ndarray, total: int, fraction: float) -> np.ndarray:
    ideal = counts.astype(float) * fraction
    allocation = np.floor(ideal).astype(int)
    remaining = total - int(allocation.sum())
    if remaining < 0 or remaining > len(counts):
        raise ValueError("Unable to allocate requested split size")
    order = np.argsort(-(ideal - allocation), kind="stable")
    allocation[order[:remaining]] += 1
    if np.any(allocation > counts):
        raise ValueError("Split allocation exceeds stratum size")
    return allocation


def stratified_split(
    frame: pd.DataFrame,
    config: GeneratorConfig,
    *,
    seed: int | None = None,
) -> dict[str, pd.DataFrame]:
    """Split by (approved, credit_history) while preserving exact requested sizes."""
    split_sizes = config["split"]
    if len(frame) != sum(split_sizes.values()):
        raise ValueError(
            f"Expected {sum(split_sizes.values())} rows for split, received {len(frame)}"
        )

    rng = np.random.default_rng(seed if seed is not None else config["split_seed"])
    groups = list(frame.groupby(["approved", "credit_history"], observed=True, sort=True))
    counts = np.array([len(group) for _, group in groups], dtype=int)
    train_fraction = split_sizes["train"] / len(frame)
    train_counts = _hamilton_allocation(counts, split_sizes["train"], train_fraction)
    remaining_counts = counts - train_counts
    validation_fraction = split_sizes["validation"] / (
        split_sizes["validation"] + split_sizes["test"]
    )
    validation_counts = _hamilton_allocation(
        remaining_counts, split_sizes["validation"], validation_fraction
    )

    indices: dict[str, list[int]] = {"train": [], "validation": [], "test": []}
    for (_, group), train_count, validation_count in zip(
        groups, train_counts, validation_counts, strict=True
    ):
        shuffled = rng.permutation(group.index.to_numpy())
        train_end = int(train_count)
        validation_end = train_end + int(validation_count)
        indices["train"].extend(shuffled[:train_end].tolist())
        indices["validation"].extend(shuffled[train_end:validation_end].tolist())
        indices["test"].extend(shuffled[validation_end:].tolist())

    result: dict[str, pd.DataFrame] = {}
    for name, selected_indices in indices.items():
        order = rng.permutation(np.asarray(selected_indices, dtype=int))
        result[name] = frame.loc[order].reset_index(drop=True)
        expected = split_sizes[name]
        if len(result[name]) != expected:
            raise RuntimeError(f"{name} split has {len(result[name])} rows; expected {expected}")
    return result


def assert_disjoint_splits(splits: dict[str, pd.DataFrame], feature_columns: list[str]) -> None:
    """Raise if an input-feature tuple appears in more than one split."""
    seen: set[tuple] = set()
    for name in ("train", "validation", "test"):
        current = set(splits[name][feature_columns].itertuples(index=False, name=None))
        overlap = seen & current
        if overlap:
            raise ValueError(f"Found {len(overlap)} feature duplicates crossing into {name}")
        seen.update(current)
