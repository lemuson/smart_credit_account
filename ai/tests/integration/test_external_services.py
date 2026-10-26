from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from faststream.rabbit import RabbitBroker, RabbitQueue
from ollama import AsyncClient

from app.agent.orchestrator import ChatOrchestrator
from app.core.config import get_settings
from app.integrations.backend_client import BackendClient
from app.llm.client import OllamaEmbeddingClient, OllamaLLMClient
from app.messaging.demo import demo_request
from app.rag.retriever import RagRetriever
from app.rag.vector_store import ChromaVectorStore
from app.schemas.tools import GetScoringResultArgs
from app.tools.banking_tools import build_banking_registry
from app.tools.registry import ToolDefinition, ToolRegistry

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_EXTERNAL_INTEGRATION") != "1",
    reason="set RUN_EXTERNAL_INTEGRATION=1 to test local services",
)


@pytest.mark.integration
@pytest.mark.ollama
async def test_configured_ollama_models_exist() -> None:
    settings = get_settings()
    client = AsyncClient(host=settings.ollama_base_url, timeout=5)
    response = await client.list()
    names = {model.model for model in response.models}
    assert settings.ollama_llm_model in names
    assert settings.ollama_embedding_model in names
    await client.close()


@pytest.mark.integration
@pytest.mark.ollama
async def test_real_ollama_embedding_and_rag_retrieval() -> None:
    settings = get_settings()
    embeddings = OllamaEmbeddingClient(settings)
    store = ChromaVectorStore(settings.chroma_path, settings.chroma_collection)
    try:
        rows = await RagRetriever(embeddings, store).retrieve("формальная проверка заявки")
    finally:
        await embeddings.close()
    assert rows
    assert all(row.chunk.metadata["document_id"] for row in rows)


@pytest.mark.integration
@pytest.mark.ollama
async def test_real_ollama_orchestrator_executes_required_tool() -> None:
    settings = get_settings()
    llm = OllamaLLMClient(settings)
    backend = BackendClient(settings)
    registry = build_banking_registry(backend)
    orchestrator = ChatOrchestrator(settings, llm, registry)
    try:
        result = await orchestrator.handle(demo_request("Покажи список кредитных продуктов"))
    finally:
        await orchestrator.close()
    assert result.status == "completed"
    assert "search_credit_products" in registry.executed_names


@pytest.mark.integration
@pytest.mark.ollama
async def test_real_qwen_scoring_answer_is_numerically_grounded() -> None:
    settings = get_settings()
    llm = OllamaLLMClient(settings)
    registry = ToolRegistry()
    factors = [
        {
            "feature": feature,
            "display_name": display_name,
            "input_value": input_value,
            "baseline_value": baseline_value,
            "logit_contribution": contribution,
            "direction": direction,
            "rank": rank,
        }
        for rank, (
            feature,
            display_name,
            input_value,
            baseline_value,
            contribution,
            direction,
        ) in enumerate(
            (
                (
                    "loan_amount",
                    "Сумма кредита",
                    3000000.0,
                    1084206.829326128,
                    -1.1700180706736214,
                    "negative",
                ),
                (
                    "annual_revenue",
                    "Годовая выручка",
                    5000000.0,
                    3100150.2539505637,
                    0.6329372000603288,
                    "positive",
                ),
                (
                    "has_collateral",
                    "Наличие залога",
                    False,
                    0.2615,
                    -0.12552998203113533,
                    "negative",
                ),
                (
                    "loan_term_months",
                    "Срок кредита",
                    24,
                    20.962714285714284,
                    0.07319690652896335,
                    "positive",
                ),
                (
                    "credit_history",
                    "Кредитная история",
                    "average",
                    0.31792857142857145,
                    0.032736411607779556,
                    "positive",
                ),
                (
                    "business_age_months",
                    "Срок работы бизнеса",
                    48,
                    51.50957142857143,
                    -0.016381343913534303,
                    "negative",
                ),
            ),
            start=1,
        )
    ]
    payload = {
        "assessment_id": "71000000-0000-0000-0000-000000000001",
        "schema_version": "1.0",
        "status": "completed",
        "model": {
            "model_id": "synthetic-credit-logreg",
            "model_version": "1.0",
            "family": "logistic_regression",
        },
        "demonstration_only": True,
        "score": {
            "name": "synthetic_model_score",
            "value": 0.42812646869272963,
            "display_percent": 42.81,
        },
        "explanation": {"baseline": {"logit": 0.2835596501343672}, "factors": factors},
        "limitations_warning": (
            "Демонстрационная ML-оценка обучена на синтетических данных и не является "
            "решением банка."
        ),
        "calculated_at": "2026-10-26T09:26:12.111675Z",
        "selected_what_if": None,
    }

    async def scoring(_, __: GetScoringResultArgs):
        return payload

    registry.register(
        ToolDefinition("get_scoring_result", "scoring", GetScoringResultArgs, scoring)
    )
    orchestrator = ChatOrchestrator(settings, llm, registry)
    try:
        result = await orchestrator.handle(
            demo_request(
                "Объясни демонстрационный ML scoring 71000000-0000-0000-0000-000000000001."
            )
        )
    finally:
        await orchestrator.close()

    assert result.status == "completed"
    assert "42,81%" in result.answer or "42.81%" in result.answer
    assert "не могу безопасно объяснить" not in result.answer
    assert not ChatOrchestrator._has_ungrounded_number(result.answer, payload)


@pytest.mark.integration
@pytest.mark.rabbitmq
async def test_real_rabbitmq_round_trip() -> None:
    settings = get_settings()
    broker = RabbitBroker(settings.rabbitmq_url)
    queue = RabbitQueue(f"ai.test.{uuid4()}", auto_delete=True, exclusive=True)
    received = None

    @broker.subscriber(queue)
    async def consume(payload: dict) -> None:
        nonlocal received
        received = payload

    async with broker:
        await broker.start()
        await broker.publish({"ok": True}, queue=queue)
        for _ in range(20):
            if received is not None:
                break
            await asyncio.sleep(0.05)
    assert received == {"ok": True}
