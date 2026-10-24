from __future__ import annotations

from typing import Protocol

from app.rag.models import LoadedDocument, RetrievedChunk


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    async def replace_document(
        self, document_id: str, chunks: list, embeddings: list[list[float]]
    ) -> int: ...

    async def query(
        self, embedding: list[float], top_k: int, max_distance: float
    ) -> list[RetrievedChunk]: ...


class RagRetriever:
    def __init__(
        self,
        embeddings: EmbeddingProvider,
        store: VectorStore,
        *,
        top_k: int = 5,
        max_distance: float = 0.65,
    ) -> None:
        self.embeddings = embeddings
        self.store = store
        self.top_k = top_k
        self.max_distance = max_distance

    async def retrieve(self, query: str) -> list[RetrievedChunk]:
        vectors = await self.embeddings.embed([query])
        return await self.store.query(vectors[0], self.top_k, self.max_distance)

    @staticmethod
    def format_context(chunks: list[RetrievedChunk], max_chars: int = 8000) -> str:
        parts: list[str] = []
        used = 0
        for row in chunks:
            source = row.chunk.metadata.get("source", "unknown")
            part = f"[Источник: {source}]\n{row.chunk.text}"
            if used + len(part) > max_chars:
                break
            parts.append(part)
            used += len(part)
        return "\n\n".join(parts)


class RagIndexer:
    def __init__(self, embeddings: EmbeddingProvider, store: VectorStore, chunker: object) -> None:
        self.embeddings = embeddings
        self.store = store
        self.chunker = chunker

    async def index(self, document: LoadedDocument) -> int:
        chunks = self.chunker.split(document)
        vectors = await self.embeddings.embed([chunk.text for chunk in chunks])
        return await self.store.replace_document(document.document_id, chunks, vectors)
