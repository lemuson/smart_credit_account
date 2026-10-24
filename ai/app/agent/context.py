from __future__ import annotations

from app.schemas.messages import HistoryMessage


class ContextManager:
    def __init__(self, max_messages: int = 12, max_chars: int = 16000) -> None:
        self.max_messages = max_messages
        self.max_chars = max_chars

    def trim(self, history: list[HistoryMessage]) -> list[HistoryMessage]:
        kept: list[HistoryMessage] = []
        used = 0
        for item in reversed(history[-self.max_messages :]):
            if used + len(item.content) > self.max_chars:
                break
            kept.append(item)
            used += len(item.content)
        return list(reversed(kept))
