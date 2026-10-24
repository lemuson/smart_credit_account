from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.agent.orchestrator import ChatOrchestrator
from app.core.config import get_settings
from app.integrations.backend_client import BackendClient
from app.llm.client import LLMClient, OllamaEmbeddingClient, OllamaLLMClient
from app.llm.prompts import SYSTEM_PROMPT
from app.rag.retriever import RagRetriever
from app.rag.vector_store import ChromaVectorStore
from app.schemas.messages import ChatRequest, TrustedContext
from app.schemas.tools import LLMReply
from app.tools.banking_tools import build_banking_registry


class RecordingLLM:
    def __init__(self, delegate: LLMClient) -> None:
        self.delegate = delegate
        self.tool_names: list[str] = []

    async def chat(self, messages: list[dict[str, Any]], tools=None) -> LLMReply:
        reply = await self.delegate.chat(messages, tools)
        self.tool_names.extend(call.name for call in reply.tool_calls)
        return reply


def make_request(query: str) -> ChatRequest:
    return ChatRequest(
        request_id=uuid4(),
        conversation_id=uuid4(),
        user_id=UUID("20000000-0000-0000-0000-000000000001"),
        organization_id=UUID("10000000-0000-0000-0000-000000000001"),
        message=query,
        trusted_context=TrustedContext(
            subject="evaluation-user",
            roles=["entrepreneur"],
            authorization="Bearer demo-user-token",
        ),
    )


async def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    backend = BackendClient(settings)
    raw_llm = OllamaLLMClient(settings)
    recording_llm = RecordingLLM(raw_llm)
    embedder = OllamaEmbeddingClient(settings)
    store = ChromaVectorStore(settings.chroma_path, settings.chroma_collection)
    retriever = RagRetriever(
        embedder, store, top_k=settings.rag_top_k, max_distance=settings.rag_max_distance
    )
    registry = build_banking_registry(backend)
    orchestrator = ChatOrchestrator(settings, recording_llm, registry, retriever)
    started = time.perf_counter()
    try:
        result = await orchestrator.handle(make_request(case["query"]))
        answer = result.answer.casefold()
        expected = set(case.get("expected_tools", []))
        selected_names = list(registry.executed_names)
        selected = set(selected_names)
        checks = {
            "tools": expected.issubset(selected),
            "must_contain": all(term.casefold() in answer for term in case.get("must_contain", [])),
            "forbidden_absent": all(
                term.casefold() not in answer for term in case.get("forbidden_strings", [])
            ),
            "valid_result": result.status in {"completed", "needs_clarification", "failed"},
            "sources_valid": all(
                source.document_id and source.chunk_id for source in result.sources
            ),
        }
        return {
            "id": case["id"],
            "passed": all(checks.values()),
            "checks": checks,
            "selected_tools": selected_names,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "answer": result.answer,
            "sources": [source.model_dump() for source in result.sources],
        }
    finally:
        await backend.close()
        await raw_llm.close()
        await embedder.close()


async def run(dataset_path: Path, output_path: Path, selected_ids: set[str] | None = None) -> None:
    cases = [json.loads(line) for line in dataset_path.read_text().splitlines() if line.strip()]
    if selected_ids:
        cases = [case for case in cases if case["id"] in selected_ids]
    results = []
    for case in cases:
        results.append(await evaluate_case(case))
    settings = get_settings()
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "model": settings.ollama_llm_model,
        "embedding_model": settings.ollama_embedding_model,
        "temperature": settings.llm_temperature,
        "num_ctx": settings.llm_num_ctx,
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("passed", "total")}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible local AI evaluation")
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/dataset.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/results/latest.json"))
    parser.add_argument("--ids", help="Comma-separated scenario IDs for a focused regression run")
    args = parser.parse_args()
    selected_ids = set(args.ids.split(",")) if args.ids else None
    asyncio.run(run(args.dataset, args.output, selected_ids))


if __name__ == "__main__":
    main()
