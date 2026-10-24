from __future__ import annotations

from uuid import UUID, uuid4

from app.messaging.broker import EVENTS_EXCHANGE, broker
from app.schemas.messages import ChatRequest, TrustedContext


def demo_request(message: str = "Какие кредиты подходят моему ИП?") -> ChatRequest:
    return ChatRequest(
        request_id=uuid4(),
        conversation_id=uuid4(),
        user_id=UUID("20000000-0000-0000-0000-000000000001"),
        organization_id=UUID("10000000-0000-0000-0000-000000000001"),
        message=message,
        trusted_context=TrustedContext(
            subject="demo-user-1",
            roles=["entrepreneur"],
            authorization="Bearer demo-user-token",
        ),
    )


async def publish_demo(message: str = "Какие кредиты подходят моему ИП?") -> ChatRequest:
    request = demo_request(message)
    async with broker:
        await broker.publish(
            request.model_dump(mode="json"),
            exchange=EVENTS_EXCHANGE,
            routing_key="ai.chat.request",
            correlation_id=str(request.request_id),
            persist=True,
        )
    return request
