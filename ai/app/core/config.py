from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "qwen2.5:7b-instruct"
    ollama_embedding_model: str = "qwen3-embedding:0.6b"
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_num_ctx: int = Field(default=8192, ge=1024)
    llm_timeout_seconds: float = Field(default=120, gt=0)
    llm_max_tool_rounds: int = Field(default=4, ge=1, le=10)

    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_prefetch_count: int = Field(default=1, ge=1)
    ai_worker_concurrency: int = Field(default=1, ge=1)
    rabbitmq_max_attempts: int = Field(default=3, ge=1, le=10)
    rabbitmq_retry_delay_ms: int = Field(default=5000, ge=100)

    backend_base_url: str = "http://localhost:8090"
    backend_service_token: SecretStr = SecretStr("development-service-token")
    backend_timeout_seconds: float = Field(default=10, gt=0)

    chroma_path: Path = Path("./data/chroma")
    chroma_collection: str = "credit_knowledge"
    knowledge_base_path: Path = Path("./knowledge_base")
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_max_distance: float = Field(default=0.65, ge=0, le=2)
    rag_chunk_size: int = Field(default=900, ge=200)
    rag_chunk_overlap: int = Field(default=150, ge=0)

    context_max_messages: int = Field(default=12, ge=1, le=100)
    context_max_chars: int = Field(default=16000, ge=1000)

    @field_validator("rag_chunk_overlap")
    @classmethod
    def validate_overlap(cls, value: int, info: object) -> int:
        data = getattr(info, "data", {})
        if value >= data.get("rag_chunk_size", 900):
            raise ValueError("rag_chunk_overlap must be smaller than rag_chunk_size")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
