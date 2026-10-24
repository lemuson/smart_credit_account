from __future__ import annotations

from faststream.rabbit import ExchangeType

from app.messaging.broker import DLX_EXCHANGE, EVENTS_EXCHANGE, RETRY_EXCHANGE


def test_exchanges_use_faststream_exchange_type() -> None:
    assert EVENTS_EXCHANGE.type is ExchangeType.DIRECT
    assert RETRY_EXCHANGE.type is ExchangeType.DIRECT
    assert DLX_EXCHANGE.type is ExchangeType.DIRECT
