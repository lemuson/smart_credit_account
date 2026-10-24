from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Protocol

from ollama import AsyncClient, ResponseError

from app.core.config import Settings
from app.core.exceptions import DependencyUnavailable, ModelProtocolError
from app.schemas.tools import LLMReply, ToolCall


class LLMClient(Protocol):
    async def chat(
        self, messages: list[dict[str, Any]], tools: Sequence[dict[str, Any]] | None = None
    ) -> LLMReply: ...


class OllamaLLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncClient(
            host=settings.ollama_base_url,
            timeout=settings.llm_timeout_seconds,
        )

    async def close(self) -> None:
        await self.client.close()

    async def chat(
        self, messages: list[dict[str, Any]], tools: Sequence[dict[str, Any]] | None = None
    ) -> LLMReply:
        try:
            response = await asyncio.wait_for(
                self.client.chat(
                    model=self.settings.ollama_llm_model,
                    messages=messages,
                    tools=list(tools or []),
                    options={
                        "temperature": self.settings.llm_temperature,
                        "num_ctx": self.settings.llm_num_ctx,
                    },
                ),
                timeout=self.settings.llm_timeout_seconds,
            )
        except (TimeoutError, ConnectionError, ResponseError) as exc:
            raise DependencyUnavailable(f"Ollama request failed: {exc}") from exc

        message = response.message
        calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                calls.append(
                    ToolCall(
                        name=call.function.name,
                        arguments=dict(call.function.arguments or {}),
                    )
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise ModelProtocolError("Ollama returned an invalid tool call") from exc
        return LLMReply(
            content=message.content or "",
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
        )


class OllamaEmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncClient(
            host=settings.ollama_base_url,
            timeout=settings.llm_timeout_seconds,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await asyncio.wait_for(
                self.client.embed(model=self.settings.ollama_embedding_model, input=texts),
                timeout=self.settings.llm_timeout_seconds,
            )
        except (TimeoutError, ConnectionError, ResponseError) as exc:
            raise DependencyUnavailable(f"Ollama embedding request failed: {exc}") from exc
        return [list(vector) for vector in response.embeddings]

    async def close(self) -> None:
        await self.client.close()
