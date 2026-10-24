from __future__ import annotations

from functools import lru_cache

from app.agent.orchestrator import ChatOrchestrator
from app.core.config import get_settings
from app.integrations.backend_client import BackendClient
from app.llm.client import OllamaEmbeddingClient, OllamaLLMClient
from app.rag.retriever import RagRetriever
from app.rag.vector_store import ChromaVectorStore
from app.tools.banking_tools import build_banking_registry


@lru_cache
def get_vector_store() -> ChromaVectorStore:
    settings = get_settings()
    return ChromaVectorStore(settings.chroma_path, settings.chroma_collection)


def build_orchestrator() -> ChatOrchestrator:
    settings = get_settings()
    backend = BackendClient(settings)
    llm = OllamaLLMClient(settings)
    embeddings = OllamaEmbeddingClient(settings)
    retriever = RagRetriever(
        embeddings,
        get_vector_store(),
        top_k=settings.rag_top_k,
        max_distance=settings.rag_max_distance,
    )
    return ChatOrchestrator(settings, llm, build_banking_registry(backend), retriever)
