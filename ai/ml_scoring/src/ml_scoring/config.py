"""Versioned generator configuration loading and validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class GeneratorConfig:
    """Loaded YAML configuration with a canonical content hash."""

    values: dict[str, Any]
    source: Path
    sha256: str

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    @property
    def version(self) -> str:
        return str(self.values["generator_version"])


def _validate_config(values: dict[str, Any]) -> None:
    required = {
        "generator_version",
        "n_rows",
        "generation_seed",
        "split_seed",
        "columns",
        "feature_columns",
        "ml_feature_allow_list",
        "business_stages",
        "age",
        "annual_revenue",
        "credit_history",
        "requested_load_ratio",
        "loan_amount",
        "loan_term",
        "collateral",
        "target",
        "split",
        "statistical_ranges",
        "stability",
    }
    missing = sorted(required - values.keys())
    if missing:
        raise ValueError(f"Missing configuration sections: {', '.join(missing)}")

    if sum(stage["weight"] for stage in values["business_stages"]) != 1.0:
        raise ValueError("Business-stage weights must sum to 1.0")
    if sum(part["weight"] for part in values["age"]["components"]) != 1.0:
        raise ValueError("Age mixture weights must sum to 1.0")
    if sum(part["weight"] for part in values["requested_load_ratio"]["components"]) != 1.0:
        raise ValueError("Requested-load mixture weights must sum to 1.0")
    if sum(values["split"].values()) != values["n_rows"]:
        raise ValueError("Split sizes must sum to n_rows")


def load_config(path: str | Path) -> GeneratorConfig:
    source = Path(path).resolve()
    values = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("Generator configuration must be a YAML mapping")
    _validate_config(values)
    canonical = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return GeneratorConfig(values=values, source=source, sha256=digest)
