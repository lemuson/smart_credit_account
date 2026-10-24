from __future__ import annotations

from typing import Any

import pytest

from app.core.exceptions import ToolNotAllowed, ToolValidationError
from app.schemas.messages import ChatRequest
from app.schemas.tools import GetProductDetailsArgs
from app.tools.banking_tools import _purpose_is_grounded
from app.tools.registry import ToolDefinition, ToolRegistry


@pytest.mark.asyncio
async def test_registry_validates_and_executes(chat_request: ChatRequest) -> None:
    async def handler(_: ChatRequest, args: GetProductDetailsArgs) -> dict[str, Any]:
        return {"product_id": args.product_id}

    registry = ToolRegistry()
    registry.register(ToolDefinition("details", "details", GetProductDetailsArgs, handler))
    result = await registry.execute("details", {"product_id": "demo-1"}, chat_request)
    assert result.ok is True
    assert result.data == {"product_id": "demo-1"}


@pytest.mark.asyncio
async def test_registry_rejects_unknown_tool(chat_request: ChatRequest) -> None:
    with pytest.raises(ToolNotAllowed):
        await ToolRegistry().execute("shell", {}, chat_request)


@pytest.mark.asyncio
async def test_registry_rejects_extra_arguments(chat_request: ChatRequest) -> None:
    async def handler(_: ChatRequest, args: GetProductDetailsArgs) -> dict[str, Any]:
        return args.model_dump()

    registry = ToolRegistry()
    registry.register(ToolDefinition("details", "details", GetProductDetailsArgs, handler))
    with pytest.raises(ToolValidationError):
        await registry.execute(
            "details", {"product_id": "demo-1", "user_id": "attacker"}, chat_request
        )


def test_tool_purpose_must_be_grounded_in_user_message() -> None:
    assert _purpose_is_grounded("Нужны деньги на покупку оборудования", "покупка оборудования")
    assert not _purpose_is_grounded("Нужны 2 млн на 24 месяца", "покупка оборудования")
    assert _purpose_is_grounded("Нужны 2 млн", None)
