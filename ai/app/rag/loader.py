from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from app.rag.models import LoadedDocument

SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pdf_text(path: Path) -> str:
    reader = PdfReader(path)
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def load_document(path: Path) -> LoadedDocument:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported document type: {suffix}")
    raw = _pdf_text(path) if suffix == ".pdf" else path.read_text(encoding="utf-8")
    text = clean_text(raw)
    if not text:
        raise ValueError(f"Document {path} contains no extractable text")

    metadata: dict[str, str] = {}
    for line in text.splitlines()[:20]:
        if ":" in line:
            key, value = line.split(":", 1)
            normalized = key.strip().lower().replace(" ", "_")
            if normalized in {"document_id", "document_version"}:
                metadata[normalized] = value.strip()
    return LoadedDocument(
        document_id=metadata.get("document_id", path.stem),
        source=path.name,
        version=metadata.get("document_version", "1"),
        text=text,
    )


def iter_documents(directory: Path) -> list[LoadedDocument]:
    paths = sorted(
        path for path in directory.rglob("*") if path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    return [load_document(path) for path in paths]
