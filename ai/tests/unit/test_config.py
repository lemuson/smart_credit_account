from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.ollama_llm_model == "qwen2.5:7b-instruct"
    assert settings.rabbitmq_prefetch_count == 1


def test_chunk_overlap_must_be_smaller() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rag_chunk_size=500, rag_chunk_overlap=500)
