"""Synthetic credit dataset generator for the MVP scoring prototype."""

from .config import GeneratorConfig, load_config
from .generator import generate_dataset

__all__ = ["GeneratorConfig", "generate_dataset", "load_config"]
__version__ = "1.0"
