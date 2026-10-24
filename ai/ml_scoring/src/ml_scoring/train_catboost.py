"""Bounded CatBoost hyperparameter search and final fitting."""

from __future__ import annotations

from typing import Any

import pandas as pd
from catboost import CatBoostClassifier

from .evaluation import binary_metrics
from .features import prepare_catboost_features


def _model_parameters(
    candidate: dict[str, Any], config: dict[str, Any], seed: int
) -> dict[str, Any]:
    return {
        **candidate,
        "loss_function": config["loss_function"],
        "eval_metric": config["eval_metric"],
        "random_seed": seed,
        "thread_count": int(config["thread_count"]),
        "allow_writing_files": False,
        "verbose": False,
    }


def tune_catboost(
    train_x: pd.DataFrame,
    train_y: pd.Series,
    selection_x: pd.DataFrame,
    selection_y: pd.Series,
    config: dict[str, Any],
    *,
    seed: int,
    threshold: float,
) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
    train_prepared = prepare_catboost_features(train_x)
    selection_prepared = prepare_catboost_features(selection_x)
    experiments: list[dict[str, Any]] = []
    for index, candidate in enumerate(config["candidates"]):
        model = CatBoostClassifier(**_model_parameters(candidate, config, seed))
        model.fit(
            train_prepared,
            train_y,
            cat_features=["credit_history"],
            eval_set=(selection_prepared, selection_y),
            early_stopping_rounds=int(config["early_stopping_rounds"]),
            use_best_model=True,
        )
        probability = model.predict_proba(selection_prepared)[:, 1]
        metrics = binary_metrics(selection_y.to_numpy(), probability, threshold=threshold)
        best_iteration = int(model.get_best_iteration())
        if best_iteration < 0:
            best_iteration = int(candidate["iterations"]) - 1
        experiments.append(
            {
                "candidate_index": index,
                "parameters": dict(candidate),
                "best_iteration": best_iteration + 1,
                "selection_metrics": metrics,
            }
        )
    selected = max(
        experiments,
        key=lambda item: (
            item["selection_metrics"]["roc_auc"],
            -item["selection_metrics"]["log_loss"],
        ),
    )
    return selected["parameters"], int(selected["best_iteration"]), experiments


def fit_final_catboost(
    train_x: pd.DataFrame,
    train_y: pd.Series,
    parameters: dict[str, Any],
    iterations: int,
    config: dict[str, Any],
    *,
    seed: int,
) -> CatBoostClassifier:
    final_parameters = dict(parameters)
    final_parameters["iterations"] = iterations
    model = CatBoostClassifier(**_model_parameters(final_parameters, config, seed))
    model.fit(
        prepare_catboost_features(train_x),
        train_y,
        cat_features=["credit_history"],
    )
    return model
