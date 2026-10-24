from __future__ import annotations

import logging

from faststream import AckPolicy, FastStream
from faststream.rabbit import RabbitMessage
from pydantic import ValidationError

from app.api.dependencies import build_orchestrator
from app.core.config import get_settings
from app.core.exceptions import AIServiceError
from app.core.logging import configure_logging
from app.messaging.broker import (
    CHAT_QUEUE,
    DEAD_QUEUE,
    DLX_EXCHANGE,
    EVENTS_EXCHANGE,
    RETRY_EXCHANGE,
    RETRY_QUEUE,
    broker,
)
from app.schemas.messages import ChatRequest, ChatResult

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
orchestrator = build_orchestrator()
app = FastStream(broker)


async def decode_raw_message(message: RabbitMessage) -> bytes:
    """Keep decoding inside the manual-ack handler so malformed JSON can be rejected."""
    return message.body


@app.after_shutdown
async def close_clients() -> None:
    await orchestrator.close()


@app.after_startup
async def declare_retry_and_dead_letter_topology() -> None:
    retry_exchange = await broker.declare_exchange(RETRY_EXCHANGE)
    retry_queue = await broker.declare_queue(RETRY_QUEUE)
    await retry_queue.bind(retry_exchange, routing_key="ai.chat.retry")

    dead_exchange = await broker.declare_exchange(DLX_EXCHANGE)
    dead_queue = await broker.declare_queue(DEAD_QUEUE)
    await dead_queue.bind(dead_exchange, routing_key="ai.chat.dead")


@broker.subscriber(
    CHAT_QUEUE,
    EVENTS_EXCHANGE,
    ack_policy=AckPolicy.MANUAL,
    decoder=decode_raw_message,
)
async def process_chat(message: RabbitMessage) -> None:
    try:
        payload = await message.decode()
        request = ChatRequest.model_validate_json(payload)
    except (ValidationError, TypeError, ValueError):
        logger.warning("invalid_chat_message", exc_info=True)
        await message.reject(requeue=False)
        return

    correlation_id = str(request.request_id)
    raw_retry = message.headers.get("x-retry-count", 0) if message.headers else 0
    retry_count = int(raw_retry)
    try:
        result = await orchestrator.handle(request)
        await broker.publish(
            result.model_dump(mode="json"),
            exchange=EVENTS_EXCHANGE,
            routing_key="ai.chat.result",
            correlation_id=correlation_id,
            persist=True,
        )
        await message.ack()
    except AIServiceError as exc:
        if exc.retryable and retry_count + 1 < settings.rabbitmq_max_attempts:
            await broker.publish(
                request.model_dump(mode="json"),
                exchange=RETRY_EXCHANGE,
                routing_key="ai.chat.retry",
                headers={"x-retry-count": retry_count + 1},
                correlation_id=correlation_id,
                persist=True,
            )
        else:
            result = ChatResult(
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                status="failed",
                answer="Не удалось обработать запрос. Повторите попытку позднее.",
                error_code=exc.code,
            )
            await broker.publish(
                result.model_dump(mode="json"),
                exchange=EVENTS_EXCHANGE,
                routing_key="ai.chat.result",
                correlation_id=correlation_id,
                persist=True,
            )
        await message.ack()
    except Exception:
        logger.exception("unhandled_chat_error", extra={"request_id": correlation_id})
        await message.reject(requeue=False)
