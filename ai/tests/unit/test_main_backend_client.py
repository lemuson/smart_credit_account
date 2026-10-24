import asyncio

import httpx

from app.core.config import Settings
from app.integrations.backend_client import BackendClient


def test_main_backend_response_adapter_and_purpose(chat_request):
    seen = []

    def handle(request):
        seen.append(request)
        assert request.headers["X-User-ID"] == str(chat_request.user_id)
        path = request.url.path
        product = {
            "id": "example",
            "name": "Кредит",
            "annual_rate": "18.00",
            "purposes": ["equipment"],
            "demonstration_only": True,
        }
        if path.endswith("/profile"):
            payload = {
                "id": str(chat_request.organization_id),
                "user_id": str(chat_request.user_id),
                "company": {"name": "Демо", "registration_date": "2020-01-01"},
                "financials": {"annual_revenue": "24000000"},
            }
        elif path.endswith("/search"):
            assert request.url.params["purpose"] == "equipment"
            payload = [product]
        elif path.endswith("/required-documents"):
            payload = {"product_id": "example", "required_documents": ["registration"]}
        elif path.endswith("/validate"):
            payload = {
                "valid": False,
                "errors": [{"code": "MISSING_DOCUMENT"}],
                "product_id": "example",
            }
        else:
            payload = product
        return httpx.Response(200, json=payload)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), base_url="http://backend"
        ) as http:
            backend = BackendClient(Settings(backend_contract="main"), http)
            profile = await backend.get_user_profile(chat_request)
            assert profile["business_name"] == "Демо"
            assert profile["organization_id"] == str(chat_request.organization_id)
            products = await backend.search_credit_products(
                chat_request, purpose="покупку оборудования", amount="1000000", term_months=24
            )
            assert products[0]["product_id"] == "example"
            assert products[0]["annual_rate_percent"] == "18.00"
            details = await backend.get_product_details(chat_request, "example")
            assert details["product_id"] == "example"
            documents = await backend.get_required_documents(chat_request, "example")
            assert documents == [{"code": "registration", "name": "registration", "required": True}]
            validation = await backend.validate_application(chat_request, chat_request.request_id)
            assert validation["issues"] == [{"code": "MISSING_DOCUMENT"}]
            assert validation["decision"] is None
            count = len(seen)
            assert (
                await backend.search_credit_products(
                    chat_request, purpose="неизвестная цель", amount=None, term_months=None
                )
                == []
            )
            assert len(seen) == count

    asyncio.run(scenario())


def test_mock_backend_contract_is_preserved(chat_request):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"items": [{"product_id": "demo"}]})
            ),
            base_url="http://mock",
        ) as http:
            backend = BackendClient(Settings(), http)
            products = await backend.search_credit_products(
                chat_request, purpose=None, amount=None, term_months=None
            )
            assert products == [{"product_id": "demo"}]

    asyncio.run(scenario())
