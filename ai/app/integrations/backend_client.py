from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.core.exceptions import BackendAccessDenied, BackendNotFound, DependencyUnavailable
from app.schemas.messages import ChatRequest


class BackendClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.backend_base_url,
            timeout=settings.backend_timeout_seconds,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self, request: ChatRequest) -> dict[str, str]:
        # Identity always comes from the signed/trusted message envelope, never tool arguments.
        return {
            "Authorization": request.trusted_context.authorization,
            "X-Service-Token": self._settings.backend_service_token.get_secret_value(),
            "X-User-ID": str(request.user_id),
            "X-Organization-ID": str(request.organization_id),
            "X-Request-ID": str(request.request_id),
        }

    async def _request(
        self,
        method: str,
        path: str,
        request: ChatRequest,
        **kwargs: Any,
    ) -> Any:
        try:
            response = await self._client.request(
                method, path, headers=self._headers(request), **kwargs
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise DependencyUnavailable("Main Backend timed out") from exc
        except httpx.ConnectError as exc:
            raise DependencyUnavailable("Main Backend is unavailable") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise BackendAccessDenied("Main Backend denied access") from exc
            if exc.response.status_code == 404:
                raise BackendNotFound("Requested backend resource was not found") from exc
            if exc.response.status_code >= 500:
                raise DependencyUnavailable("Main Backend returned a server error") from exc
            raise
        return response.json()

    async def get_user_profile(self, request: ChatRequest) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/profile", request)

    async def search_credit_products(
        self,
        request: ChatRequest,
        *,
        purpose: str | None,
        amount: str | None,
        term_months: int | None,
    ) -> list[dict[str, Any]]:
        params = {
            k: v
            for k, v in {
                "purpose": purpose,
                "amount": amount,
                "term_months": term_months,
            }.items()
            if v is not None
        }
        payload = await self._request(
            "GET", "/api/v1/credit-products/search", request, params=params
        )
        return payload["items"]

    async def get_product_details(self, request: ChatRequest, product_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/credit-products/{product_id}", request)

    async def get_application_status(
        self, request: ChatRequest, application_id: UUID
    ) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/applications/{application_id}/status", request)

    async def get_required_documents(
        self, request: ChatRequest, product_id: str
    ) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET", f"/api/v1/credit-products/{product_id}/required-documents", request
        )
        return payload["items"]

    async def validate_application(
        self, request: ChatRequest, application_id: UUID
    ) -> dict[str, Any]:
        return await self._request(
            "POST", f"/api/v1/applications/{application_id}/validate", request
        )
