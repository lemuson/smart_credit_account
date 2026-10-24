from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import get_settings
from app.llm.client import OllamaEmbeddingClient
from app.rag.chunker import TextChunker
from app.rag.loader import iter_documents
from app.rag.retriever import RagIndexer
from app.rag.vector_store import ChromaVectorStore


async def run() -> dict[str, int]:
    settings = get_settings()
    embeddings = OllamaEmbeddingClient(settings)
    store = ChromaVectorStore(settings.chroma_path, settings.chroma_collection)
    indexer = RagIndexer(
        embeddings,
        store,
        TextChunker(settings.rag_chunk_size, settings.rag_chunk_overlap),
    )
    indexed: dict[str, int] = {}
    try:
        for document in iter_documents(settings.knowledge_base_path):
            indexed[document.document_id] = await indexer.index(document)
    finally:
        await embeddings.close()
    return indexed


def main() -> None:
    parser = argparse.ArgumentParser(description="Index the local demonstration knowledge base")
    parser.parse_args()
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
