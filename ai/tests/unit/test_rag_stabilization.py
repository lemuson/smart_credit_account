from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.orchestrator import ChatOrchestrator
from app.agent.planner import plan_tool_calls, requests_demo_knowledge
from app.core.config import Settings
from app.rag.chunker import TextChunker
from app.rag.grounding import extract_relevant_enumeration, missing_enumeration_items
from app.rag.loader import load_document
from app.rag.models import RetrievedChunk
from app.rag.retriever import RagRetriever
from app.schemas.messages import ChatRequest
from app.schemas.tools import (
    GetRequiredDocumentsArgs,
    GetUserProfileArgs,
    LLMReply,
    SearchCreditProductsArgs,
)
from app.tools.registry import ToolDefinition, ToolRegistry

CHECKLIST_QUESTION = "Какие документы нужны ИП без залога согласно демонстрационному чек-листу?"


class ChecklistRetriever:
    def __init__(self) -> None:
        root = Path(__file__).resolve().parents[2]
        document = load_document(
            root / "rag_demo_credit_cabinet/documents/KB-03_учебный_перечень_документов.txt"
        )
        self.rows = [
            RetrievedChunk(chunk, index / 100)
            for index, chunk in enumerate(TextChunker().split(document), start=1)
        ]
        self.queries: list[str] = []

    async def retrieve(self, query: str) -> list[RetrievedChunk]:
        self.queries.append(query)
        return self.rows

    @staticmethod
    def format_context(rows: list[RetrievedChunk]) -> str:
        return RagRetriever.format_context(rows)


class IncompleteChecklistLLM:
    def __init__(self) -> None:
        self.tools_seen: list[list[dict[str, Any]]] = []

    async def chat(self, messages: list[dict[str, Any]], tools=None) -> LLMReply:
        self.tools_seen.append(list(tools or []))
        return LLMReply(
            content=(
                "Нужны удостоверение личности, регистрационные сведения ИП и выписка "
                "за шесть месяцев."
            )
        )


class StaticLLM:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def chat(self, messages: list[dict[str, Any]], tools=None) -> LLMReply:
        return LLMReply(content=self.answer)


async def test_demo_checklist_is_rag_only_complete_and_grounded(
    chat_request: ChatRequest,
) -> None:
    async def search(_: ChatRequest, __: SearchCreditProductsArgs):
        raise AssertionError("search_credit_products must not run for the demo checklist")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition("search_credit_products", "search", SearchCreditProductsArgs, search)
    )
    retriever = ChecklistRetriever()
    llm = IncompleteChecklistLLM()
    request = chat_request.model_copy(update={"message": CHECKLIST_QUESTION})

    result = await ChatOrchestrator(Settings(_env_file=None), llm, registry, retriever).handle(
        request
    )

    enumeration = extract_relevant_enumeration(CHECKLIST_QUESTION, retriever.rows)
    assert enumeration is not None
    assert enumeration.document_id == "KB-03"
    assert len(enumeration.items) == 4
    assert "анкета" in enumeration.items[0]
    assert missing_enumeration_items(result.answer, enumeration) == []
    assert "анкета" in result.answer.casefold()
    assert "демонстрацион" in result.answer.casefold()
    assert {source.document_id for source in result.sources} == {"KB-03"}
    assert registry.executed_names == ()
    assert all(tools == [] for tools in llm.tools_seen)


async def test_mixed_demo_checklist_and_product_keeps_rag_and_backend_tool(
    chat_request: ChatRequest,
) -> None:
    async def documents(_: ChatRequest, args: GetRequiredDocumentsArgs):
        assert args.product_id == "demo-working-capital"
        return {"documents": ["registration"], "is_demo": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition("get_required_documents", "documents", GetRequiredDocumentsArgs, documents)
    )
    retriever = ChecklistRetriever()
    request = chat_request.model_copy(
        update={
            "message": ("Сравни учебный чек-лист и актуальные документы для demo-working-capital")
        }
    )

    result = await ChatOrchestrator(
        Settings(_env_file=None),
        StaticLLM("Сравнение подготовлено по найденным данным."),
        registry,
        retriever,
    ).handle(request)

    assert registry.executed_names == ("get_required_documents",)
    assert retriever.queries == [request.message]
    assert {source.document_id for source in result.sources} == {"KB-03"}
    assert "демонстрацион" in result.answer.casefold()


async def test_demo_tool_warning_is_added_deterministically(chat_request: ChatRequest) -> None:
    async def profile(_: ChatRequest, __: GetUserProfileArgs):
        return {"company_name": "ООО Демо", "is_demo": True}

    registry = ToolRegistry()
    registry.register(ToolDefinition("get_user_profile", "profile", GetUserProfileArgs, profile))
    request = chat_request.model_copy(update={"message": "Покажи сведения о профиле бизнеса"})

    result = await ChatOrchestrator(
        Settings(_env_file=None), StaticLLM("Компания: ООО Демо."), registry
    ).handle(request)

    assert registry.executed_names == ("get_user_profile",)
    assert "демонстрационного контура" in result.answer
    assert "официальным предложением или решением банка" in result.answer


async def test_internal_tool_names_are_hidden_from_user(chat_request: ChatRequest) -> None:
    async def documents(_: ChatRequest, __: GetRequiredDocumentsArgs):
        return {"documents": []}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition("get_required_documents", "documents", GetRequiredDocumentsArgs, documents)
    )
    result = await ChatOrchestrator(
        Settings(_env_file=None),
        StaticLLM("Вызовите Backend Tool `get_required_documents`, чтобы проверить требования."),
        registry,
    ).handle(chat_request.model_copy(update={"message": "Что делать дальше?"}))

    assert "get_required_documents" not in result.answer
    assert "Backend Tool" not in result.answer
    assert "защищённый сервис проверки данных" in result.answer


def test_routing_keeps_current_products_and_application_status_tools() -> None:
    assert requests_demo_knowledge(CHECKLIST_QUESTION)
    assert plan_tool_calls(CHECKLIST_QUESTION) == []
    assert [
        call.name
        for call in plan_tool_calls(
            "Какие сегодня реальные ставки и лимиты по кредитам для моей организации?"
        )
    ] == ["search_credit_products"]
    assert [
        call.name for call in plan_tool_calls("Статус заявки 30000000-0000-0000-0000-000000000001")
    ] == ["get_application_status"]
    assert requests_demo_knowledge(
        "Сравни учебный чек-лист и актуальные документы для demo-working-capital"
    )
    assert [
        call.name
        for call in plan_tool_calls(
            "Сравни учебный чек-лист и актуальные документы для demo-working-capital"
        )
    ] == ["get_required_documents"]
