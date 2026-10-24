"""Run separately: python -m app.ai.worker. No broker dependency for API startup."""

import asyncio
import logging
from datetime import timedelta
from functools import partial

import aio_pika
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.models import ChatJob
from app.ai.service import accept_result, build_request
from app.config import get_settings
from app.database import make_engine, now

logger = logging.getLogger(__name__)


def pending_request(engine, settings):
    with Session(engine) as db:
        job = db.scalar(
            select(ChatJob)
            .where(
                ChatJob.status.in_(["pending", "published"]),
                (ChatJob.published_at.is_(None))
                | (ChatJob.published_at < now() - timedelta(minutes=5)),
            )
            .order_by(ChatJob.created_at)
            .limit(1)
        )
        return build_request(db, job, settings) if job else None


def mark_published(engine, request_id):
    with Session(engine) as db, db.begin():
        job = db.scalar(select(ChatJob).where(ChatJob.id == str(request_id)).with_for_update())
        if job and job.result is None:
            job.status = "published"
            job.published_at = now()


async def consume_result(message, engine):
    try:
        accepted = await asyncio.to_thread(accept_result, engine, message.body)
    except (ValidationError, ValueError, TypeError):
        await message.reject(requeue=False)
        return
    except Exception:
        logger.warning("AI result storage unavailable; retrying delivery")
        await message.nack(requeue=True)
        return
    if accepted:
        await message.ack()
    else:
        await message.reject(requeue=False)


async def publish_request(exchange, engine, payload):
    await exchange.publish(
        aio_pika.Message(
            body=payload.model_dump_json().encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            correlation_id=str(payload.request_id),
        ),
        routing_key="ai.chat.request",
        mandatory=True,
    )
    await asyncio.to_thread(mark_published, engine, payload.request_id)


async def run():
    settings = get_settings()
    if not settings.ai_enabled or not settings.ai_service_token:
        raise RuntimeError("AI_ENABLED and AI_SERVICE_TOKEN are required")
    engine = make_engine(settings.database_url)
    try:
        while True:
            try:
                async with await aio_pika.connect_robust(
                    settings.rabbitmq_url.get_secret_value()
                ) as connection:
                    channel = await connection.channel(publisher_confirms=True)
                    await channel.set_qos(prefetch_count=1)
                    exchange = await channel.declare_exchange("ai.events", "direct", durable=True)
                    await channel.declare_exchange("ai.dlx", "direct", durable=True)
                    # Keep result queue arguments compatible with the AI Service's declaration.
                    results = await channel.declare_queue("ai.chat.result", durable=True)
                    await results.bind(exchange, "ai.chat.result")
                    requests = await channel.declare_queue(
                        "ai.chat.request",
                        durable=True,
                        arguments={
                            "x-dead-letter-exchange": "ai.dlx",
                            "x-dead-letter-routing-key": "ai.chat.dead",
                        },
                    )
                    await requests.bind(exchange, "ai.chat.request")
                    await results.consume(partial(consume_result, engine=engine))
                    while not connection.is_closed:
                        payload = await asyncio.to_thread(pending_request, engine, settings)
                        if payload:
                            await publish_request(exchange, engine, payload)
                        else:
                            await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("AI bridge unavailable; reconnecting in 3 seconds")
                await asyncio.sleep(3)
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
