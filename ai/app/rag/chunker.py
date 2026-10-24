from __future__ import annotations

import hashlib

from app.rag.models import Chunk, LoadedDocument


class TextChunker:
    def __init__(self, chunk_size: int = 900, overlap: int = 150) -> None:
        if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
            raise ValueError("Expected chunk_size > overlap >= 0")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, document: LoadedDocument) -> list[Chunk]:
        paragraphs = [part.strip() for part in document.text.split("\n\n") if part.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            remaining = paragraph
            while remaining:
                space = self.chunk_size - len(current)
                if len(remaining) <= space:
                    current = f"{current}\n\n{remaining}".strip()
                    remaining = ""
                    continue
                piece = remaining[:space]
                split_at = max(piece.rfind(". "), piece.rfind("\n"), piece.rfind(" "))
                if split_at < max(40, space // 2):
                    split_at = space
                current = f"{current}\n\n{remaining[:split_at]}".strip()
                chunks.append(current)
                carry = current[-self.overlap :] if self.overlap else ""
                current = carry.strip()
                remaining = remaining[split_at:].strip()
            if len(current) >= self.chunk_size:
                chunks.append(current)
                current = current[-self.overlap :].strip() if self.overlap else ""
        if current:
            chunks.append(current)

        result: list[Chunk] = []
        for index, text in enumerate(chunks, start=1):
            digest = hashlib.sha256(
                f"{document.document_id}:{document.version}:{index}:{text}".encode()
            ).hexdigest()[:16]
            chunk_id = f"chunk-{index:03d}-{digest}"
            result.append(
                Chunk(
                    id=f"{document.document_id}:{chunk_id}",
                    text=text,
                    metadata={
                        "document_id": document.document_id,
                        "source": document.source,
                        "chunk_id": chunk_id,
                        "document_version": document.version,
                    },
                )
            )
        return result
