from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.integrations.backend_client import BackendClient
from app.schemas.messages import ChatRequest
from mock_backend.data import APP_OTHER
from mock_backend.main import app


@pytest.mark.asyncio
async def test_backend_client_uses_trusted_identity(chat_request: ChatRequest) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        client = BackendClient(
            Settings(_env_file=None, backend_base_url="http://test"), client=http_client
        )
        profile = await client.get_user_profile(chat_request)
        products = await client.search_credit_products(
            chat_request, purpose=None, amount="2000000", term_months=24
        )
    assert profile["legal_form"] == "ИП"
    assert {product["product_id"] for product in products} == {
        "demo-working-capital",
        "demo-investment",
    }


@pytest.mark.asyncio
async def test_other_organization_application_is_hidden(chat_request: ChatRequest) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        client = BackendClient(
            Settings(_env_file=None, backend_base_url="http://test"), client=http_client
        )
        with pytest.raises(Exception) as captured:
            await client.get_application_status(chat_request, UUID(str(APP_OTHER)))
    assert captured.value.__class__.__name__ == "BackendNotFound"
