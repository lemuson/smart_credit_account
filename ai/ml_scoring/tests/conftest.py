from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "src"))

from ml_scoring.config import load_config  # noqa: E402
from ml_scoring.generator import generate_dataset  # noqa: E402


@pytest.fixture(scope="session")
def config():
    return load_config(ML_ROOT / "configs" / "generator_v1.yaml")


@pytest.fixture(scope="session")
def full_dataset(config):
    return generate_dataset(config)


@pytest.fixture(scope="session")
def ml_fixture(config):
    return generate_dataset(config, n_rows=600, seed=99117)
