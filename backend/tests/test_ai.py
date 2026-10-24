import asyncio
import importlib.util
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.contracts import ChatRequest, ChatResult
from app.ai.models import ChatJob
from app.ai.service import accept_result
from app.ai.worker import consume_result, mark_published, pending_request
from app.database import now


@pytest.fixture
def chat(env):
    api, headers, product_id, users, engine = env
    api.app.state.settings.ai_enabled = True
    # Use a SecretStr just as environment configuration does.
    from pydantic import SecretStr

    api.app.state.settings.ai_service_token = SecretStr("test-service-identity")
    response = api.post("/api/v1/chat/conversations", headers=headers["client"])
    assert response.status_code == 201, response.text
    cid = response.json()["conversation_id"]
    path = f"/api/v1/chat/conversations/{cid}/messages"
    data = {"request_id": str(uuid4()), "message": "Какие кредиты доступны?"}
    return api, headers, engine, cid, path, data


def test_outbox_idempotency_order_and_inbox(chat):
    api, headers, engine, cid, path, data = chat
    for _ in range(2):
        assert api.post(path, headers=headers["client"], json=data).status_code == 202
    assert (
        api.post(
            path, headers=headers["client"], json={**data, "message": "Другой текст"}
        ).status_code
        == 409
    )
    second = {"request_id": str(uuid4()), "message": "Какие документы?"}
    assert api.post(path, headers=headers["client"], json=second).status_code == 409
    # No publish confirmation: the same durable job remains available on restart.
    payload = pending_request(engine, api.app.state.settings)
    assert str(payload.request_id) == data["request_id"]
    assert pending_request(engine, api.app.state.settings).request_id == payload.request_id
    assert payload.history == []
    assert payload.trusted_context.authorization != headers["client"]["Authorization"]
    mark_published(engine, data["request_id"])
    assert pending_request(engine, api.app.state.settings) is None
    # A lost reply is recovered by republishing, with the original request_id.
    with Session(engine) as db, db.begin():
        db.get(ChatJob, data["request_id"]).published_at = now() - timedelta(minutes=6)
    assert pending_request(engine, api.app.state.settings).request_id == payload.request_id
    result = ChatResult(
        request_id=payload.request_id, conversation_id=cid, status="completed", answer="Ответ AI"
    )
    assert accept_result(engine, result.model_dump_json())
    assert accept_result(engine, result.model_copy(update={"answer": "Дубликат"}).model_dump_json())
    job = api.get(f"/api/v1/chat/requests/{payload.request_id}", headers=headers["client"]).json()
    assert job["result"]["answer"] == "Ответ AI"
    assert job["status"] == "completed"
    assert api.post(path, headers=headers["client"], json=second).status_code == 202
    next_request = pending_request(engine, api.app.state.settings)
    assert [item.content for item in next_request.history] == [data["message"], "Ответ AI"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ChatJob)) == 2


def test_chat_acl_and_untrusted_identity(chat, flow):
    api, headers, engine, cid, path, data = chat
    application = flow.create()
    assert api.post(path, headers=headers["other"], json=data).status_code == 404
    assert api.get(path, headers=headers["other"]).status_code == 404
    assert (
        api.post(
            path, headers=headers["client"], json={**data, "user_id": str(uuid4())}
        ).status_code
        == 422
    )
    other_cid = api.post("/api/v1/chat/conversations", headers=headers["other"]).json()[
        "conversation_id"
    ]
    assert (
        api.post(
            f"/api/v1/chat/conversations/{other_cid}/messages",
            headers=headers["other"],
            json={**data, "application_id": application["id"]},
        ).status_code
        == 404
    )
    assert api.post(path, headers=headers["client"], json=data).status_code == 202
    assert (
        api.get(f"/api/v1/chat/requests/{data['request_id']}", headers=headers["other"]).status_code
        == 404
    )
    assert api.post("/api/v1/chat/conversations", headers=headers["officer"]).status_code == 403
    assert api.post(path, json=data).status_code == 401


def tool_headers(payload):
    return {
        "Authorization": payload.trusted_context.authorization,
        "X-Service-Token": "test-service-identity",
        "X-User-ID": str(payload.user_id),
        "X-Organization-ID": str(payload.organization_id),
        "X-Request-ID": str(payload.request_id),
    }


def test_delegated_tools_acl_and_readonly(chat, flow):
    api, headers, engine, cid, path, data = chat
    application = flow.create()
    assert api.post(path, headers=headers["client"], json=data).status_code == 202
    payload = pending_request(engine, api.app.state.settings)
    delegated = tool_headers(payload)
    paths = [
        "/api/v1/profile",
        "/api/v1/credit-products/search",
        f"/api/v1/credit-products/{flow.product_id}",
        f"/api/v1/credit-products/{flow.product_id}/required-documents",
        f"/api/v1/applications/{application['id']}/status",
    ]
    for url in paths:
        assert api.get(url, headers=delegated).status_code == 200, url
    before = flow.get()
    assert (
        api.post(
            f"/api/v1/applications/{application['id']}/validate", headers=delegated
        ).status_code
        == 200
    )
    assert flow.get() == before
    assert api.get("/api/v1/client/applications", headers=delegated).status_code == 403
    assert api.put("/api/v1/profile", headers=delegated, json={}).status_code == 403
    assert (
        api.get("/api/v1/profile", headers={**delegated, "X-Service-Token": "wrong"}).status_code
        == 401
    )
    assert (
        api.get(
            "/api/v1/profile", headers={**delegated, "X-Organization-ID": str(uuid4())}
        ).status_code
        == 403
    )
    assert api.get(f"/api/v1/applications/{uuid4()}/status", headers=delegated).status_code == 404
    # A delegation cannot be used after the originating job has completed.
    result = ChatResult(
        request_id=payload.request_id, conversation_id=cid, status="completed", answer="Готово"
    )
    accept_result(engine, result.model_dump_json())
    assert api.get("/api/v1/profile", headers=delegated).status_code == 403


def test_other_tenant_and_expired_delegation(chat, flow):
    api, headers, engine, cid, path, data = chat
    application = flow.create()
    other_cid = api.post("/api/v1/chat/conversations", headers=headers["other"]).json()[
        "conversation_id"
    ]
    other_path = f"/api/v1/chat/conversations/{other_cid}/messages"
    api.post(other_path, headers=headers["other"], json=data)
    payload = pending_request(engine, api.app.state.settings)
    delegated = tool_headers(payload)
    assert (
        api.get(f"/api/v1/applications/{application['id']}/status", headers=delegated).status_code
        == 404
    )
    secret = api.app.state.settings.jwt_secret.get_secret_value()
    claims = jwt.decode(
        payload.trusted_context.authorization[7:],
        secret,
        algorithms=["HS256"],
        audience="smart-credit-ai-tools",
    )
    claims["exp"] = now() - timedelta(seconds=1)
    delegated["Authorization"] = "Bearer " + jwt.encode(claims, secret, algorithm="HS256")
    assert api.get("/api/v1/profile", headers=delegated).status_code == 401


def test_result_consumer_ack_reject_and_retry(chat):
    api, headers, engine, cid, path, data = chat
    api.post(path, headers=headers["client"], json=data)
    result = ChatResult(
        request_id=data["request_id"],
        conversation_id=cid,
        status="failed",
        answer="Недоступен",
        error_code="LLM_UNAVAILABLE",
    )
    message = AsyncMock()
    message.body = result.model_dump_json().encode()
    asyncio.run(consume_result(message, engine))
    message.ack.assert_awaited_once()
    message.ack.reset_mock()
    asyncio.run(consume_result(message, engine))
    message.ack.assert_awaited_once()
    message.reset_mock()
    message.body = b"{invalid"
    asyncio.run(consume_result(message, engine))
    message.reject.assert_awaited_once_with(requeue=False)
    for change in [{"request_id": uuid4()}, {"conversation_id": uuid4()}]:
        message.reset_mock()
        message.body = result.model_copy(update=change).model_dump_json().encode()
        asyncio.run(consume_result(message, engine))
        message.reject.assert_awaited_once_with(requeue=False)
    message.reset_mock()
    message.body = result.model_dump_json().encode()
    with patch("app.ai.worker.accept_result", side_effect=RuntimeError("DB unavailable")):
        asyncio.run(consume_result(message, engine))
    message.nack.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_awaited()


def test_contract_matches_real_ai_schema(chat):
    api, headers, engine, cid, path, data = chat
    api.post(path, headers=headers["client"], json=data)
    source = Path(__file__).resolve().parents[2] / "ai/app/schemas/messages.py"
    spec = importlib.util.spec_from_file_location("ai_wire_contract", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert ChatRequest.model_json_schema() == module.ChatRequest.model_json_schema()
    assert ChatResult.model_json_schema() == module.ChatResult.model_json_schema()
    payload = pending_request(engine, api.app.state.settings)
    real_request = module.ChatRequest.model_validate_json(payload.model_dump_json())
    real_result = module.ChatResult(
        request_id=real_request.request_id,
        conversation_id=real_request.conversation_id,
        status="needs_clarification",
        answer="Уточните сумму",
    )
    assert accept_result(engine, real_result.model_dump_json())
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({**payload.model_dump(), "created_at": "2026-10-24T10:00:00"})


def test_disabled_chat(env):
    api, headers, *_ = env
    assert api.post("/api/v1/chat/conversations", headers=headers["client"]).status_code == 503


def test_publish_failure_keeps_outbox_and_commit_failure_rolls_back(chat):
    from sqlalchemy import event

    from app.ai.worker import publish_request

    api, headers, engine, cid, path, data = chat
    api.post(path, headers=headers["client"], json=data)
    payload = pending_request(engine, api.app.state.settings)
    exchange = AsyncMock()
    exchange.publish.side_effect = ConnectionError("broker unavailable")
    with pytest.raises(ConnectionError):
        asyncio.run(publish_request(exchange, engine, payload))
    assert pending_request(engine, api.app.state.settings).request_id == payload.request_id
    exchange.publish.side_effect = None
    asyncio.run(publish_request(exchange, engine, payload))
    message = exchange.publish.call_args.args[0]
    assert message.delivery_mode == 2
    assert message.correlation_id == data["request_id"]
    assert exchange.publish.call_args.kwargs["mandatory"] is True
    assert pending_request(engine, api.app.state.settings) is None
    result = ChatResult(
        request_id=payload.request_id, conversation_id=cid, status="completed", answer="Ответ"
    )

    def fail_commit(session):
        raise RuntimeError("commit failed")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            accept_result(engine, result.model_dump_json())
    finally:
        event.remove(Session, "before_commit", fail_commit)
    with Session(engine) as db:
        stored = db.get(ChatJob, data["request_id"])
        assert stored.result is None
        assert stored.status == "published"
    assert accept_result(engine, result.model_dump_json())


def test_rate_limit_and_history_bound(chat):
    api, headers, engine, cid, path, data = chat
    for number in range(10):
        request_id = str(uuid4())
        response = api.post(
            path, headers=headers["client"], json={**data, "request_id": request_id}
        )
        assert response.status_code == 202
        result = ChatResult(
            request_id=request_id, conversation_id=cid, status="completed", answer=f"Ответ {number}"
        )
        accept_result(engine, result.model_dump_json())
    response = api.post(path, headers=headers["client"], json=data)
    assert response.status_code == 429
    # A later request gets the most recent six complete exchanges, in order.
    with Session(engine) as db, db.begin():
        from sqlalchemy import update

        db.execute(update(ChatJob).values(created_at=now() - timedelta(minutes=2)))
    assert api.post(path, headers=headers["client"], json=data).status_code == 202
    payload = pending_request(engine, api.app.state.settings)
    assert len(payload.history) == 12


@pytest.mark.rabbitmq
def test_real_rabbitmq_roundtrip(chat, monkeypatch):
    import os
    from contextlib import suppress

    import aio_pika
    from pydantic import SecretStr

    from app.ai import worker

    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        pytest.skip("TEST_RABBITMQ_URL must point to an isolated RabbitMQ")
    api, headers, engine, cid, path, data = chat
    api.post(path, headers=headers["client"], json=data)
    settings = api.app.state.settings
    settings.rabbitmq_url = SecretStr(url)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)

    async def scenario():
        task = asyncio.create_task(worker.run())
        try:
            async with await aio_pika.connect(url) as connection:
                channel = await connection.channel(publisher_confirms=True)
                queue = await channel.declare_queue(
                    "ai.chat.request",
                    durable=True,
                    arguments={
                        "x-dead-letter-exchange": "ai.dlx",
                        "x-dead-letter-routing-key": "ai.chat.dead",
                    },
                )
                message = None
                for _ in range(100):
                    message = await queue.get(fail=False)
                    if message:
                        break
                    await asyncio.sleep(0.1)
                assert message is not None, "backend did not publish the durable outbox"
                payload = ChatRequest.model_validate_json(message.body)
                assert str(payload.request_id) == data["request_id"]
                await message.ack()
                result = ChatResult(
                    request_id=payload.request_id,
                    conversation_id=cid,
                    status="completed",
                    answer="RabbitMQ roundtrip",
                )
                exchange = await channel.get_exchange("ai.events")
                for _ in range(2):
                    await exchange.publish(
                        aio_pika.Message(body=result.model_dump_json().encode(), delivery_mode=2),
                        routing_key="ai.chat.result",
                        mandatory=True,
                    )
                for _ in range(100):
                    with Session(engine) as db:
                        job = db.get(ChatJob, data["request_id"])
                        if job.result:
                            assert job.result["answer"] == "RabbitMQ roundtrip"
                            break
                    await asyncio.sleep(0.1)
                else:
                    pytest.fail("backend did not consume the AI result")
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
