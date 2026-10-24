from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.schemas.messages import ChatRequest, TrustedContext


@pytest.fixture
def chat_request() -> ChatRequest:
    return ChatRequest(
        request_id=uuid4(),
        conversation_id=uuid4(),
        user_id=UUID("20000000-0000-0000-0000-000000000001"),
        organization_id=UUID("10000000-0000-0000-0000-000000000001"),
        message="Какие кредиты подходят моему ИП?",
        trusted_context=TrustedContext(
            subject="demo-user-1",
            roles=["entrepreneur"],
            authorization="Bearer demo-user-token",
        ),
    )
