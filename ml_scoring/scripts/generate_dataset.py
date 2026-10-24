#!/usr/bin/env python3
"""Generate, validate, split and save the version-1 synthetic dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from ml_scoring.config import load_config  # noqa: E402
from ml_scoring.generator import generate_dataset  # noqa: E402
from ml_scoring.split import assert_disjoint_splits, stratified_split  # noqa: E402
from ml_scoring.validation import validate_dataset, validate_splits  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_DIR / "configs" / "generator_v1.yaml",
    )
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    frame = generate_dataset(config)
    validation = validate_dataset(frame, config)
    validation.raise_for_errors()

    splits = stratified_split(frame, config)
    assert_disjoint_splits(splits, config["feature_columns"])
    split_validation = validate_splits(splits, config)
    split_validation.raise_for_errors()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    filenames = {
        "train": "synthetic_credit_train.csv",
        "validation": "synthetic_credit_val.csv",
        "test": "synthetic_credit_test.csv",
    }
    for name, split_frame in splits.items():
        split_frame.to_csv(args.output_dir / filenames[name], index=False, float_format="%.1f")

    metadata = {
        "generator_version": config.version,
        "generation_seed": config["generation_seed"],
        "split_seed": config["split_seed"],
        "config_sha256": config.sha256,
        "config": config.values,
        "row_count": len(frame),
        "class_counts": validation.metrics["class_counts"],
        "approval_rate": validation.metrics["approval_rate"],
        "split_row_counts": {name: len(value) for name, value in splits.items()},
        "hard_validation_errors": validation.hard_errors,
        "statistical_warnings": validation.warnings,
        "split_validation": {
            "hard_errors": split_validation.hard_errors,
            "warnings": split_validation.warnings,
            "metrics": split_validation.metrics,
        },
    }
    (args.output_dir / "generator_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Generated {len(frame)} rows; approval rate "
        f"{validation.metrics['approval_rate']:.2%}; config SHA-256 {config.sha256}"
    )
    if validation.warnings:
        print("Statistical warnings:")
        for warning in validation.warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
