from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID, uuid4

from app.agent.orchestrator import ChatOrchestrator
from app.core.config import get_settings
from app.integrations.backend_client import BackendClient
from app.llm.client import OllamaEmbeddingClient, OllamaLLMClient
from app.rag.retriever import RagRetriever
from app.rag.vector_store import ChromaVectorStore
from app.schemas.messages import ChatRequest, TrustedContext
from app.tools.banking_tools import build_banking_registry


async def run(query: str) -> dict:
    settings = get_settings()
    backend = BackendClient(settings)
    llm = OllamaLLMClient(settings)
    embeddings = OllamaEmbeddingClient(settings)
    store = ChromaVectorStore(settings.chroma_path, settings.chroma_collection)
    retriever = RagRetriever(
        embeddings, store, top_k=settings.rag_top_k, max_distance=settings.rag_max_distance
    )
    orchestrator = ChatOrchestrator(settings, llm, build_banking_registry(backend), retriever)
    request = ChatRequest(
        request_id=uuid4(),
        conversation_id=uuid4(),
        user_id=UUID("20000000-0000-0000-0000-000000000001"),
        organization_id=UUID("10000000-0000-0000-0000-000000000001"),
        message=query,
        trusted_context=TrustedContext(
            subject="live-check-user",
            roles=["entrepreneur"],
            authorization="Bearer demo-user-token",
        ),
    )
    try:
        return (await orchestrator.handle(request)).model_dump(mode="json")
    finally:
        await backend.close()
        await llm.close()
        await embeddings.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Call the full orchestrator without RabbitMQ")
    parser.add_argument("query", nargs="?", default="Какие кредиты подходят моему ИП?")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.query)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
