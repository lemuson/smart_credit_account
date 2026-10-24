from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.messages import ChatRequest


def test_chat_request_round_trip(chat_request: ChatRequest) -> None:
    restored = ChatRequest.model_validate_json(chat_request.model_dump_json())
    assert restored == chat_request
    assert restored.schema_version == "1.0"


def test_chat_request_rejects_unknown_fields(chat_request: ChatRequest) -> None:
    payload = chat_request.model_dump(mode="json")
    payload["admin"] = True
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload)


def test_chat_request_rejects_oversized_message(chat_request: ChatRequest) -> None:
    payload = chat_request.model_dump(mode="json")
    payload["message"] = "x" * 8001
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload)
