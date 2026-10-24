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
from app.tools.banking_tools import build_banking_registry

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
