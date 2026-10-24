"""Trusted-local model bundle and strict inference schema checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .calibration import ProbabilityCalibrator
from .features import FEATURE_COLUMNS, prepare_catboost_features, validate_feature_frame


@dataclass
class CreditScoringModel:
    base_model: Any
    calibrator: ProbabilityCalibrator
    threshold: float
    training_version: str
    model_family: str = "catboost"

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        validated = validate_feature_frame(frame)
        model_input = (
            prepare_catboost_features(validated) if self.model_family == "catboost" else validated
        )
        base_probability = self.base_model.predict_proba(model_input)[:, 1]
        positive = self.calibrator.transform(base_probability)
        return np.column_stack([1.0 - positive, positive])

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(frame)[:, 1] >= self.threshold).astype(int)

    @property
    def feature_columns(self) -> list[str]:
        return list(FEATURE_COLUMNS)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_bundle(bundle: CreditScoringModel, path: str | Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    return sha256_file(path)


def load_trusted_bundle(
    path: str | Path,
    *,
    expected_sha256: str,
    trusted: bool = False,
) -> CreditScoringModel:
    if not trusted:
        raise ValueError("Refusing to deserialize joblib without trusted=True")
    path = Path(path).resolve()
    if sha256_file(path) != expected_sha256:
        raise ValueError("Model artifact checksum mismatch")
    loaded: Any = joblib.load(path)
    if not isinstance(loaded, CreditScoringModel):
        raise TypeError("Artifact is not a CreditScoringModel")
    if loaded.feature_columns != FEATURE_COLUMNS:
        raise ValueError("Saved model schema is incompatible")
    if loaded.model_family not in {"catboost", "logistic_regression"}:
        raise ValueError("Saved model family is unsupported")
    return loaded
