from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    document_id: str
    source: str
    version: str
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk: Chunk
    distance: float
