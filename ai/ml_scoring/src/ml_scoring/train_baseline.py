"""Logistic Regression baseline with leakage-safe preprocessing."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler


def _log1p(values: np.ndarray) -> np.ndarray:
    return np.log1p(values.astype(float))


def build_baseline(config: dict[str, Any], seed: int) -> Pipeline:
    financial = Pipeline(
        [
            ("validate", SimpleImputer(strategy="median")),
            ("log1p", FunctionTransformer(_log1p, feature_names_out="one-to-one")),
            ("scale", StandardScaler()),
        ]
    )
    numerical = Pipeline(
        [("validate", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
    )
    preprocessing = ColumnTransformer(
        [
            ("financial", financial, ["annual_revenue", "loan_amount"]),
            ("numeric", numerical, ["business_age_months", "loan_term_months"]),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                ["credit_history"],
            ),
            ("boolean", "passthrough", ["has_collateral"]),
        ],
        verbose_feature_names_out=False,
    )
    model = LogisticRegression(
        C=float(config["C"]),
        max_iter=int(config["max_iter"]),
        solver=str(config["solver"]),
        random_state=seed,
    )
    return Pipeline([("preprocessing", preprocessing), ("model", model)])


def baseline_coefficients(pipeline: Pipeline) -> list[dict[str, float | str]]:
    names = pipeline.named_steps["preprocessing"].get_feature_names_out()
    coefficients = pipeline.named_steps["model"].coef_[0]
    return [
        {"feature": str(name), "coefficient": float(value)}
        for name, value in zip(names, coefficients, strict=True)
    ]


def fit_baseline(
    train_x: pd.DataFrame,
    train_y: pd.Series,
    config: dict[str, Any],
    seed: int,
) -> Pipeline:
    pipeline = build_baseline(config, seed)
    pipeline.fit(train_x, train_y)
    return pipeline
