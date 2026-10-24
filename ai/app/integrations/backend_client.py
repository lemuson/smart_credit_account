from __future__ import annotations

from datetime import date
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
        payload = await self._request("GET", "/api/v1/profile", request)
        if self._settings.backend_contract == "main":
            company = payload["company"]
            registered = date.fromisoformat(company["registration_date"]) if company else None
            today = date.today()
            age = (
                (
                    (today.year - registered.year) * 12
                    + today.month
                    - registered.month
                    - (today.day < registered.day)
                )
                if registered
                else 0
            )
            return {
                "user_id": payload["user_id"],
                "organization_id": payload["id"],
                "business_name": company.get("name"),
                "business_age_months": age,
                "financials": payload["financials"],
                "is_demo": True,
            }
        return payload

    async def search_credit_products(
        self,
        request: ChatRequest,
        *,
        purpose: str | None,
        amount: str | None,
        term_months: int | None,
    ) -> list[dict[str, Any]]:
        if self._settings.backend_contract == "main" and purpose:
            purpose = self._purpose(purpose)
            if purpose is None:
                return []
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
        if self._settings.backend_contract == "main":
            return [self._product(item) for item in payload]
        return payload["items"]

    async def get_product_details(self, request: ChatRequest, product_id: str) -> dict[str, Any]:
        payload = await self._request("GET", f"/api/v1/credit-products/{product_id}", request)
        return self._product(payload) if self._settings.backend_contract == "main" else payload

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
        if self._settings.backend_contract == "main":
            return [
                {"code": code, "name": code, "required": True}
                for code in payload["required_documents"]
            ]
        return payload["items"]

    @staticmethod
    def _purpose(value: str) -> str | None:
        value = value.casefold()
        purposes = {
            "working_capital": ("оборот",),
            "equipment": ("оборуд", "техник"),
            "expansion": ("расшир", "развит"),
            "refinancing": ("рефинанс",),
        }
        for code, words in purposes.items():
            if value == code or any(word in value for word in words):
                return code
        return None

    @staticmethod
    def _product(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            **payload,
            "product_id": payload["id"],
            "annual_rate_percent": payload["annual_rate"],
            "purpose": payload["purposes"],
            "is_demo": payload["demonstration_only"],
        }

    async def validate_application(
        self, request: ChatRequest, application_id: UUID
    ) -> dict[str, Any]:
        payload = await self._request(
            "POST", f"/api/v1/applications/{application_id}/validate", request
        )
        if self._settings.backend_contract == "main":
            return {**payload, "issues": payload["errors"], "decision": None, "is_demo": True}
        return payload
