from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.exceptions import ToolNotAllowed, ToolValidationError
from app.schemas.messages import ChatRequest
from app.schemas.tools import ToolExecutionResult

ArgsT = TypeVar("ArgsT", bound=BaseModel)
ToolHandler = Callable[[ChatRequest, Any], Awaitable[dict[str, Any] | list[Any]]]


@dataclass(frozen=True, slots=True)
class ToolDefinition(Generic[ArgsT]):
    name: str
    description: str
    args_model: type[ArgsT]
    handler: ToolHandler

    def ollama_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition[Any]] = {}
        self._closers: list[Callable[[], Awaitable[None]]] = []
        self._executed_names: list[str] = []

    def register(self, definition: ToolDefinition[Any]) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool {definition.name!r} is already registered")
        self._tools[definition.name] = definition

    def add_closer(self, closer: Callable[[], Awaitable[None]]) -> None:
        self._closers.append(closer)

    async def close(self) -> None:
        for closer in reversed(self._closers):
            await closer()

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [tool.ollama_schema() for tool in self._tools.values()]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    @property
    def executed_names(self) -> tuple[str, ...]:
        return tuple(self._executed_names)

    async def execute(
        self, name: str, raw_arguments: dict[str, Any], request: ChatRequest
    ) -> ToolExecutionResult:
        definition = self._tools.get(name)
        if definition is None:
            raise ToolNotAllowed(f"Tool {name!r} is not in the allow-list")
        try:
            arguments = definition.args_model.model_validate(raw_arguments)
        except ValidationError as exc:
            raise ToolValidationError(str(exc)) from exc
        self._executed_names.append(name)
        data = await definition.handler(request, arguments)
        return ToolExecutionResult(name=name, ok=True, data=data)
