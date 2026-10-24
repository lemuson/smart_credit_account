from __future__ import annotations

from faststream.rabbit import Channel, ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.core.config import get_settings

settings = get_settings()

EVENTS_EXCHANGE = RabbitExchange("ai.events", type=ExchangeType.DIRECT, durable=True)
RETRY_EXCHANGE = RabbitExchange("ai.retry", type=ExchangeType.DIRECT, durable=True)
DLX_EXCHANGE = RabbitExchange("ai.dlx", type=ExchangeType.DIRECT, durable=True)

CHAT_QUEUE = RabbitQueue(
    "ai.chat.request",
    durable=True,
    routing_key="ai.chat.request",
    arguments={
        "x-dead-letter-exchange": "ai.dlx",
        "x-dead-letter-routing-key": "ai.chat.dead",
    },
)
RESULT_QUEUE = RabbitQueue("ai.chat.result", durable=True, routing_key="ai.chat.result")
RETRY_QUEUE = RabbitQueue(
    "ai.chat.retry",
    durable=True,
    routing_key="ai.chat.retry",
    arguments={
        "x-message-ttl": settings.rabbitmq_retry_delay_ms,
        "x-dead-letter-exchange": "ai.events",
        "x-dead-letter-routing-key": "ai.chat.request",
    },
)
DEAD_QUEUE = RabbitQueue("ai.chat.dead", durable=True, routing_key="ai.chat.dead")

broker = RabbitBroker(
    settings.rabbitmq_url,
    default_channel=Channel(
        prefetch_count=settings.rabbitmq_prefetch_count,
        publisher_confirms=True,
    ),
    graceful_timeout=30,
)
