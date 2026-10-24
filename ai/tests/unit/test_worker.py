from __future__ import annotations

from typing import Any

import pytest

from app.core.exceptions import DependencyUnavailable
from app.messaging import worker
from app.schemas.messages import ChatRequest, ChatResult


class FakeMessage:
    def __init__(self, body: bytes, headers: dict[str, Any] | None = None) -> None:
        self.body = body
        self.headers = headers or {}
        self.acked = False
        self.rejected = False
        self.requeue: bool | None = None

    async def decode(self) -> bytes:
        return self.body

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, *, requeue: bool) -> None:
        self.rejected = True
        self.requeue = requeue


async def test_worker_rejects_malformed_json() -> None:
    message = FakeMessage(b"{not-json")
    await worker.process_chat(message)  # type: ignore[arg-type]
    assert message.rejected is True
    assert message.requeue is False
    assert message.acked is False


async def test_worker_publishes_result_then_acks(
    chat_request: ChatRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[dict[str, Any]] = []

    class Orchestrator:
        async def handle(self, request: ChatRequest) -> ChatResult:
            return ChatResult(
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                status="completed",
                answer="Готово",
            )

    async def publish(payload: dict[str, Any], **kwargs: Any) -> None:
        published.append({"payload": payload, **kwargs})

    monkeypatch.setattr(worker, "orchestrator", Orchestrator())
    monkeypatch.setattr(worker.broker, "publish", publish)
    message = FakeMessage(chat_request.model_dump_json().encode())
    await worker.process_chat(message)  # type: ignore[arg-type]
    assert message.acked is True
    assert published[0]["routing_key"] == "ai.chat.result"
    assert published[0]["payload"]["request_id"] == str(chat_request.request_id)


async def test_worker_schedules_retry_for_dependency_failure(
    chat_request: ChatRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[dict[str, Any]] = []

    class Orchestrator:
        async def handle(self, request: ChatRequest) -> ChatResult:
            raise DependencyUnavailable("offline")

    async def publish(payload: dict[str, Any], **kwargs: Any) -> None:
        published.append({"payload": payload, **kwargs})

    monkeypatch.setattr(worker, "orchestrator", Orchestrator())
    monkeypatch.setattr(worker.broker, "publish", publish)
    message = FakeMessage(chat_request.model_dump_json().encode())
    await worker.process_chat(message)  # type: ignore[arg-type]
    assert message.acked is True
    assert published[0]["routing_key"] == "ai.chat.retry"
    assert published[0]["headers"] == {"x-retry-count": 1}


async def test_worker_rejects_unhandled_error(
    chat_request: ChatRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Orchestrator:
        async def handle(self, request: ChatRequest) -> ChatResult:
            raise RuntimeError("unexpected")

    monkeypatch.setattr(worker, "orchestrator", Orchestrator())
    message = FakeMessage(chat_request.model_dump_json().encode())
    await worker.process_chat(message)  # type: ignore[arg-type]
    assert message.rejected is True
    assert message.requeue is False
