from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.config import get_settings
from app.llm.client import OllamaEmbeddingClient
from app.rag.retriever import RagRetriever
from app.rag.vector_store import ChromaVectorStore


@dataclass(frozen=True, slots=True)
class EvaluationQuestion:
    id: int
    question: str
    expected_source: str


def load_questions(path: Path) -> list[EvaluationQuestion]:
    questions: list[EvaluationQuestion] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        questions.append(EvaluationQuestion(int(cells[0]), cells[1], cells[2]))
    if not questions:
        raise ValueError(f"No evaluation questions found in {path}")
    return questions


async def evaluate(path: Path, top_k: int | None, max_distance: float | None) -> list[dict]:
    settings = get_settings()
    embeddings = OllamaEmbeddingClient(settings)
    retriever = RagRetriever(
        embeddings,
        ChromaVectorStore(settings.chroma_path, settings.chroma_collection),
        top_k=top_k or settings.rag_top_k,
        max_distance=(settings.rag_max_distance if max_distance is None else max_distance),
    )
    results: list[dict] = []
    try:
        for question in load_questions(path):
            rows = await retriever.retrieve(question.question)
            results.append(
                {
                    **asdict(question),
                    "retrieved": [
                        {
                            "document_id": row.chunk.metadata["document_id"],
                            "source": row.chunk.metadata["source"],
                            "chunk_id": row.chunk.metadata["chunk_id"],
                            "distance": round(row.distance, 6),
                        }
                        for row in rows
                    ],
                }
            )
    finally:
        await embeddings.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval on the RAG demo corpus")
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path("rag_demo_credit_cabinet/evaluation/rag_eval_questions.md"),
    )
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--max-distance", type=float)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(evaluate(args.questions, args.top_k, args.max_distance)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
