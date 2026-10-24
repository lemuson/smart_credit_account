from __future__ import annotations

import json
from typing import Any

from app.agent.orchestrator import ChatOrchestrator
from app.core.config import Settings
from app.schemas.messages import ChatRequest
from app.schemas.tools import GetProductDetailsArgs, LLMReply, SearchCreditProductsArgs, ToolCall
from app.tools.registry import ToolDefinition, ToolRegistry


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[list[dict[str, Any]]] = []

    async def chat(self, messages: list[dict[str, Any]], tools=None) -> LLMReply:
        self.calls += 1
        self.messages.append(messages.copy())
        if self.calls == 1:
            return LLMReply(
                tool_calls=[ToolCall(name="details", arguments={"product_id": "demo"})],
                finish_reason="tool_calls",
            )
        return LLMReply(content="Подходит демонстрационный продукт.", finish_reason="stop")


async def test_orchestrator_executes_real_tool_loop(chat_request: ChatRequest) -> None:
    executed: list[str] = []

    async def handler(_: ChatRequest, args: GetProductDetailsArgs):
        executed.append(args.product_id)
        return {"name": "Демо"}

    registry = ToolRegistry()
    registry.register(ToolDefinition("details", "details", GetProductDetailsArgs, handler))
    llm = FakeLLM()
    orchestrator = ChatOrchestrator(Settings(_env_file=None), llm, registry)
    result = await orchestrator.handle(chat_request)
    assert result.status == "completed"
    assert executed == ["demo"]
    assert llm.calls == 2
    assert any(message["role"] == "tool" for message in llm.messages[1])


class FakeRetriever:
    async def retrieve(self, query: str):
        from app.rag.models import Chunk, RetrievedChunk

        chunk = Chunk(
            "doc:1",
            "покупка оборудования",
            {
                "document_id": "doc",
                "source": "doc.md",
                "chunk_id": "chunk-1",
                "document_version": "1",
            },
        )
        return [RetrievedChunk(chunk, 0.1)]

    @staticmethod
    def format_context(rows):
        return rows[0].chunk.text


async def test_rag_is_not_visible_when_first_tool_arguments_are_selected(
    chat_request: ChatRequest,
) -> None:
    chat_request = chat_request.model_copy(update={"message": "Расскажи подробнее"})
    llm = FakeLLM()

    async def handler(_: ChatRequest, args: GetProductDetailsArgs):
        return {"product_id": args.product_id}

    registry = ToolRegistry()
    registry.register(ToolDefinition("details", "details", GetProductDetailsArgs, handler))
    orchestrator = ChatOrchestrator(Settings(_env_file=None), llm, registry, FakeRetriever())
    await orchestrator.handle(chat_request)
    assert all("retrieved_context" not in message.get("content", "") for message in llm.messages[0])
    assert any("retrieved_context" in message.get("content", "") for message in llm.messages[1])


async def test_planned_decimal_arguments_are_json_serializable(
    chat_request: ChatRequest,
) -> None:
    class AnswerLLM:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []

        async def chat(self, messages: list[dict[str, Any]], tools=None) -> LLMReply:
            self.messages = messages
            return LLMReply(content="Найден демонстрационный продукт.")

    async def search(_: ChatRequest, args: SearchCreditProductsArgs):
        return {"amount": str(args.amount), "term_months": args.term_months}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "search_credit_products", "search", SearchCreditProductsArgs, search
        )
    )
    llm = AnswerLLM()
    request = chat_request.model_copy(
        update={"message": "Мне нужно 2 млн рублей на 24 месяца. Что подходит?"}
    )
    result = await ChatOrchestrator(Settings(_env_file=None), llm, registry).handle(request)
    json.dumps(llm.messages)
    assert result.status == "completed"
