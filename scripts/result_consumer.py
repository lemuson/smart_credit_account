from __future__ import annotations

from faststream import FastStream

from app.messaging.broker import EVENTS_EXCHANGE, RESULT_QUEUE, broker
from app.schemas.messages import ChatResult

app = FastStream(broker)


@broker.subscriber(RESULT_QUEUE, EVENTS_EXCHANGE)
async def print_result(result: ChatResult) -> None:
    print(result.model_dump_json(indent=2))
