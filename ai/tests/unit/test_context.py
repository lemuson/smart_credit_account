from __future__ import annotations

from app.agent.context import ContextManager
from app.schemas.messages import HistoryMessage


def test_context_keeps_most_recent_messages() -> None:
    history = [HistoryMessage(role="user", content=f"message-{i}") for i in range(5)]
    result = ContextManager(max_messages=2, max_chars=100).trim(history)
    assert [item.content for item in result] == ["message-3", "message-4"]


def test_context_respects_character_budget() -> None:
    history = [
        HistoryMessage(role="user", content="a" * 10),
        HistoryMessage(role="assistant", content="b" * 10),
    ]
    result = ContextManager(max_messages=10, max_chars=10).trim(history)
    assert [item.content for item in result] == ["b" * 10]
