from __future__ import annotations

from app.rag.chunker import TextChunker
from app.rag.models import LoadedDocument, RetrievedChunk
from app.rag.retriever import RagIndexer, RagRetriever


class FakeEmbeddings:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in texts]


class FakeStore:
    def __init__(self) -> None:
        self.chunks = []
        self.replacements = 0

    async def replace_document(self, document_id: str, chunks: list, embeddings: list):
        self.replacements += 1
        self.chunks = list(chunks)
        return len(chunks)

    async def query(self, embedding: list[float], top_k: int, max_distance: float):
        return [RetrievedChunk(self.chunks[0], 0.1)] if self.chunks else []


def test_chunk_ids_are_stable() -> None:
    document = LoadedDocument("doc", "doc.md", "1", "Первый абзац.\n\n" + "Текст " * 100)
    chunker = TextChunker(200, 20)
    assert chunker.split(document) == chunker.split(document)


async def test_reindex_replaces_existing_document() -> None:
    store = FakeStore()
    indexer = RagIndexer(FakeEmbeddings(), store, TextChunker(200, 20))
    document = LoadedDocument("doc", "doc.md", "1", "Демонстрационный текст " * 30)
    first_count = await indexer.index(document)
    second_count = await indexer.index(document)
    assert first_count == second_count == len(store.chunks)
    assert store.replacements == 2


async def test_retriever_returns_sources() -> None:
    store = FakeStore()
    indexer = RagIndexer(FakeEmbeddings(), store, TextChunker(200, 20))
    await indexer.index(LoadedDocument("doc", "doc.md", "1", "Порядок подачи заявки."))
    rows = await RagRetriever(FakeEmbeddings(), store).retrieve("Как подать заявку?")
    assert rows[0].chunk.metadata["source"] == "doc.md"
