from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetUserProfileArgs(ToolArguments):
    pass


class SearchCreditProductsArgs(ToolArguments):
    purpose: str | None = Field(default=None, max_length=200)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    term_months: int | None = Field(default=None, ge=1, le=240)


class GetProductDetailsArgs(ToolArguments):
    product_id: str = Field(min_length=1, max_length=100)


class GetApplicationStatusArgs(ToolArguments):
    application_id: UUID


class GetRequiredDocumentsArgs(ToolArguments):
    product_id: str = Field(min_length=1, max_length=100)


class ValidateApplicationArgs(ToolArguments):
    application_id: UUID


class GetScoringResultArgs(ToolArguments):
    assessment_id: UUID
    what_if_id: UUID | None = None


class ToolExecutionResult(BaseModel):
    name: str
    ok: bool
    data: dict[str, Any] | list[Any] | None = None
    error_code: str | None = None
    message: str | None = None


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None


class LLMReply(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "unknown"] = "unknown"
