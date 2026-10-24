from __future__ import annotations

import argparse
import asyncio
import json

from faststream.rabbit import RabbitBroker

from app.core.config import get_settings
from app.messaging.broker import EVENTS_EXCHANGE, RESULT_QUEUE
from app.messaging.demo import demo_request
from app.schemas.messages import ChatResult


async def run(wait_seconds: float) -> ChatResult:
    settings = get_settings()
    broker = RabbitBroker(settings.rabbitmq_url)
    request = demo_request()
    completed = asyncio.Event()
    received: ChatResult | None = None

    @broker.subscriber(RESULT_QUEUE, EVENTS_EXCHANGE)
    async def capture(result: ChatResult) -> None:
        nonlocal received
        if result.request_id == request.request_id:
            received = result
            completed.set()

    async with broker:
        await broker.start()
        await broker.publish(
            request.model_dump(mode="json"),
            exchange=EVENTS_EXCHANGE,
            routing_key="ai.chat.request",
            correlation_id=str(request.request_id),
            persist=True,
        )
        await asyncio.wait_for(completed.wait(), timeout=wait_seconds)
    if received is None:
        raise RuntimeError("No matching result received")
    return received


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RabbitMQ end-to-end smoke test")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    result = asyncio.run(run(args.timeout)).model_dump(mode="json")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
