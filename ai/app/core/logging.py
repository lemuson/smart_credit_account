from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter

REDACTED_KEYS = {"authorization", "token", "password", "secret", "backend_service_token"}


class SafeJsonFormatter(JsonFormatter):
    def process_log_record(self, log_record: dict[str, object]) -> dict[str, object]:
        for key in tuple(log_record):
            if key.lower() in REDACTED_KEYS:
                log_record[key] = "[REDACTED]"
        return log_record


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SafeJsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
