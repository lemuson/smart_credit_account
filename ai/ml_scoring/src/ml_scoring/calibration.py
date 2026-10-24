"""Probability calibration fitted on predictions independent of base-model training."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


def _clip_probability(probability: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(probability, dtype=float), 1e-7, 1 - 1e-7)


class ProbabilityCalibrator(Protocol):
    method: str

    def fit(self, probability: np.ndarray, target: np.ndarray) -> ProbabilityCalibrator: ...

    def transform(self, probability: np.ndarray) -> np.ndarray: ...


@dataclass
class IdentityCalibrator:
    method: str = "uncalibrated"

    def fit(self, probability: np.ndarray, target: np.ndarray) -> IdentityCalibrator:
        return self

    def transform(self, probability: np.ndarray) -> np.ndarray:
        return _clip_probability(probability)


@dataclass
class SigmoidCalibrator:
    seed: int
    method: str = "sigmoid"

    def __post_init__(self) -> None:
        self.model = LogisticRegression(random_state=self.seed, max_iter=1_000)

    def fit(self, probability: np.ndarray, target: np.ndarray) -> SigmoidCalibrator:
        clipped = _clip_probability(probability)
        logit = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
        self.model.fit(logit, np.asarray(target, dtype=int))
        return self

    def transform(self, probability: np.ndarray) -> np.ndarray:
        clipped = _clip_probability(probability)
        logit = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
        return self.model.predict_proba(logit)[:, 1]


@dataclass
class IsotonicCalibrator:
    method: str = "isotonic"

    def __post_init__(self) -> None:
        self.model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)

    def fit(self, probability: np.ndarray, target: np.ndarray) -> IsotonicCalibrator:
        self.model.fit(_clip_probability(probability), np.asarray(target, dtype=int))
        return self

    def transform(self, probability: np.ndarray) -> np.ndarray:
        return _clip_probability(self.model.predict(_clip_probability(probability)))


def make_calibrator(method: str, seed: int) -> ProbabilityCalibrator:
    if method == "uncalibrated":
        return IdentityCalibrator()
    if method == "sigmoid":
        return SigmoidCalibrator(seed=seed)
    if method == "isotonic":
        return IsotonicCalibrator()
    raise ValueError(f"Unknown calibration method: {method}")
