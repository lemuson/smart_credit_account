from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="Smart Credit Cabinet AI Service",
    version="0.1.0",
    description="Operational API. Chat requests are transported through RabbitMQ.",
)
app.include_router(health_router)
