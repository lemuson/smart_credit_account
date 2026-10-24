from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SafeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class TrustedContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    roles: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(
        default_factory=lambda: ["entrepreneur"], max_length=16
    )
    authorization: Annotated[str, StringConstraints(min_length=1, max_length=2048)]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    conversation_id: UUID
    user_id: UUID
    organization_id: UUID
    message: SafeText
    history: list[HistoryMessage] = Field(default_factory=list, max_length=50)
    application_id: UUID | None = None
    trusted_context: TrustedContext
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("created_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value


class AnswerSource(BaseModel):
    document_id: str
    source: str
    chunk_id: str
    document_version: str
    excerpt: str | None = None


class SuggestedAction(BaseModel):
    code: str
    label: str
    application_id: UUID | None = None


class ChatResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    conversation_id: UUID
    status: Literal["completed", "needs_clarification", "failed"]
    answer: str
    sources: list[AnswerSource] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    error_code: str | None = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model: str | None = None
