"""Dataset loading, feature allow-list enforcement and schema validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .config import GeneratorConfig
from .validation import validate_splits

FEATURE_COLUMNS = [
    "annual_revenue",
    "credit_history",
    "business_age_months",
    "loan_amount",
    "has_collateral",
    "loan_term_months",
]
TARGET_COLUMN = "approved"
AUDIT_COLUMN = "age"
CREDIT_HISTORY_CATEGORIES = ["good", "average", "bad", "none"]


@dataclass(frozen=True)
class DatasetSplits:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame

    def as_dict(self) -> dict[str, pd.DataFrame]:
        return {"train": self.train, "validation": self.validation, "test": self.test}


@dataclass(frozen=True)
class ValidationPartitions:
    model_selection: pd.DataFrame
    calibration_fit: pd.DataFrame
    calibration_evaluation: pd.DataFrame


def _read_dataset(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Required dataset file does not exist: {path}")
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
    frame["credit_history"] = pd.Categorical(
        frame["credit_history"], categories=CREDIT_HISTORY_CATEGORIES
    )
    return frame


def load_dataset_splits(data_dir: str | Path, generator_config: GeneratorConfig) -> DatasetSplits:
    data_dir = Path(data_dir)
    splits = DatasetSplits(
        train=_read_dataset(data_dir / "synthetic_credit_train.csv"),
        validation=_read_dataset(data_dir / "synthetic_credit_val.csv"),
        test=_read_dataset(data_dir / "synthetic_credit_test.csv"),
    )
    if FEATURE_COLUMNS != generator_config["ml_feature_allow_list"]:
        raise ValueError("Code feature allow-list differs from generator configuration")
    result = validate_splits(splits.as_dict(), generator_config)
    result.raise_for_errors()
    validate_training_frame(pd.concat(splits.as_dict().values(), ignore_index=True))
    return splits


def validate_training_frame(frame: pd.DataFrame) -> None:
    required = {AUDIT_COLUMN, TARGET_COLUMN, *FEATURE_COLUMNS}
    if set(frame.columns) != required:
        raise ValueError(f"Training dataset columns must be exactly {sorted(required)}")
    if frame.isna().any().any():
        raise ValueError("Training dataset contains missing values")
    numeric = frame.select_dtypes(include=[np.number])
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("Training dataset contains infinite numeric values")
    if not frame["credit_history"].isin(CREDIT_HISTORY_CATEGORIES).all():
        raise ValueError("Training dataset contains unsupported credit_history")
    if not frame[TARGET_COLUMN].isin([0, 1]).all():
        raise ValueError("Target must contain only 0 and 1")
    validate_feature_frame(frame[FEATURE_COLUMNS])


def validate_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if list(frame.columns) != FEATURE_COLUMNS:
        raise ValueError(f"Input columns must be exactly {FEATURE_COLUMNS}")
    if frame.isna().any().any():
        raise ValueError("Input contains missing values")
    checks = {
        "annual_revenue": frame["annual_revenue"].between(300_000, 120_000_000).all(),
        "business_age_months": frame["business_age_months"].between(0, 240).all(),
        "loan_amount": frame["loan_amount"].between(100_000, 30_000_000).all(),
        "loan_term_months": frame["loan_term_months"].isin([6, 12, 18, 24, 36, 48, 60]).all(),
        "credit_history": frame["credit_history"].isin(CREDIT_HISTORY_CATEGORIES).all(),
        "has_collateral": frame["has_collateral"].isin([True, False, 0, 1]).all(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"Invalid feature values in: {', '.join(failed)}")
    numeric = frame[["annual_revenue", "business_age_months", "loan_amount", "loan_term_months"]]
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("Input contains infinite numeric values")
    return frame.copy()


def get_xy(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    validate_training_frame(frame)
    features = frame[FEATURE_COLUMNS].copy()
    if AUDIT_COLUMN in features.columns:
        raise AssertionError("age leaked into feature matrix")
    return features, frame[TARGET_COLUMN].astype(int).copy()


def prepare_catboost_features(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = validate_feature_frame(frame).copy()
    prepared["credit_history"] = prepared["credit_history"].astype("string").astype(str)
    prepared["has_collateral"] = prepared["has_collateral"].astype(int)
    return prepared


def partition_validation(
    validation: pd.DataFrame,
    *,
    seed: int,
    selection_fraction: float,
    calibration_fit_fraction: float,
) -> ValidationPartitions:
    stratify = (
        validation[TARGET_COLUMN].astype(str) + "|" + validation["credit_history"].astype(str)
    )
    selection, calibration_pool = train_test_split(
        validation,
        train_size=selection_fraction,
        random_state=seed,
        stratify=stratify,
    )
    fit_fraction_of_pool = calibration_fit_fraction / (1.0 - selection_fraction)
    pool_stratify = (
        calibration_pool[TARGET_COLUMN].astype(str)
        + "|"
        + calibration_pool["credit_history"].astype(str)
    )
    calibration_fit, calibration_evaluation = train_test_split(
        calibration_pool,
        train_size=fit_fraction_of_pool,
        random_state=seed + 1,
        stratify=pool_stratify,
    )
    return ValidationPartitions(
        model_selection=selection.reset_index(drop=True),
        calibration_fit=calibration_fit.reset_index(drop=True),
        calibration_evaluation=calibration_evaluation.reset_index(drop=True),
    )
