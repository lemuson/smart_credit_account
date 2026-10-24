from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Response, status
from ollama import AsyncClient

from app.api.dependencies import get_vector_store
from app.core.config import get_settings

router = APIRouter(tags=["operations"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _rabbit_ready(url: str) -> bool:
    parsed = urlparse(url)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(parsed.hostname or "localhost", parsed.port or 5672),
            timeout=2,
        )
        writer.close()
        await writer.wait_closed()
        return reader is not None
    except (OSError, TimeoutError):
        return False


@router.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    settings = get_settings()
    checks: dict[str, bool] = {}
    try:
        client = AsyncClient(host=settings.ollama_base_url, timeout=3)
        listed = await client.list()
        names = {model.model for model in listed.models}
        checks["ollama"] = True
        checks["llm_model"] = settings.ollama_llm_model in names
        checks["embedding_model"] = settings.ollama_embedding_model in names
        await client.close()
    except Exception:
        checks.update(ollama=False, llm_model=False, embedding_model=False)

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            backend_response = await client.get(f"{settings.backend_base_url}/health")
            checks["backend"] = backend_response.is_success
    except httpx.HTTPError:
        checks["backend"] = False

    checks["rabbitmq"] = await _rabbit_ready(settings.rabbitmq_url)
    try:
        checks["chroma"] = await get_vector_store().heartbeat()
    except Exception:
        checks["chroma"] = False

    ready_state = all(checks.values())
    if not ready_state:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready_state else "not_ready", "checks": checks}
