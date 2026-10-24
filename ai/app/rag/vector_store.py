from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import chromadb

from app.rag.models import Chunk, RetrievedChunk


class ChromaVectorStore:
    def __init__(self, path: Path, collection_name: str) -> None:
        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def heartbeat(self) -> bool:
        return bool(await asyncio.to_thread(self._client.heartbeat))

    async def replace_document(
        self, document_id: str, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts differ")

        def operation() -> int:
            self._collection.delete(where={"document_id": document_id})
            if chunks:
                self._collection.upsert(
                    ids=[chunk.id for chunk in chunks],
                    documents=[chunk.text for chunk in chunks],
                    metadatas=[chunk.metadata for chunk in chunks],
                    embeddings=[list(vector) for vector in embeddings],
                )
            return len(chunks)

        return await asyncio.to_thread(operation)

    async def query(
        self, embedding: Sequence[float], top_k: int, max_distance: float
    ) -> list[RetrievedChunk]:
        def operation() -> list[RetrievedChunk]:
            result = self._collection.query(
                query_embeddings=[list(embedding)],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
            rows: list[RetrievedChunk] = []
            ids = result.get("ids", [[]])[0]
            docs = result.get("documents", [[]])[0]
            metas = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]
            for item_id, text, metadata, distance in zip(ids, docs, metas, distances, strict=True):
                numeric_distance = float(distance)
                if numeric_distance <= max_distance and text and metadata:
                    rows.append(
                        RetrievedChunk(
                            Chunk(
                                str(item_id),
                                str(text),
                                {str(k): str(v) for k, v in metadata.items()},
                            ),
                            numeric_distance,
                        )
                    )
            return rows

        return await asyncio.to_thread(operation)
