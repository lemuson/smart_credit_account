from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.core.exceptions import (
    BackendAccessDenied,
    BackendConflict,
    BackendNotFound,
    DependencyUnavailable,
    ModelProtocolError,
)
from app.schemas.messages import ChatRequest

SCORING_FEATURES = {
    "annual_revenue",
    "credit_history",
    "business_age_months",
    "loan_amount",
    "has_collateral",
    "loan_term_months",
}


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
            if exc.response.status_code == 409:
                raise BackendConflict("Main Backend reported a resource conflict") from exc
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

    async def get_scoring_result(
        self,
        request: ChatRequest,
        assessment_id: UUID,
        what_if_id: UUID | None = None,
    ) -> dict[str, Any]:
        params = {"what_if_id": str(what_if_id)} if what_if_id is not None else None
        payload = await self._request(
            "GET",
            f"/api/v1/scoring/assessments/{assessment_id}",
            request,
            params=params,
        )
        try:
            if UUID(payload["assessment_id"]) != assessment_id:
                raise ValueError("assessment id does not match the request")
            if (
                payload["schema_version"] != "1.0"
                or payload["status"] != "completed"
                or payload["demonstration_only"] is not True
            ):
                raise ValueError("unsupported scoring result metadata")
            factors = payload["explanation"]["factors"]
            safe_factors = self._scoring_factors(factors)
            selected_what_if = payload.get("selected_what_if")
            if what_if_id is not None and selected_what_if is None:
                raise ValueError("requested what-if is missing from the response")
            view: dict[str, Any] = {
                "assessment_id": payload["assessment_id"],
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "model": {
                    key: payload["model"][key] for key in ("model_id", "model_version", "family")
                },
                "demonstration_only": payload["demonstration_only"],
                "score": self._scoring_score(payload["score"]),
                "explanation": {
                    "baseline": {
                        key: payload["explanation"]["baseline"][key]
                        for key in ("method", "logit", "reference_version")
                    },
                    "factors": safe_factors,
                },
                "limitations_warning": payload["limitations_warning"],
                "calculated_at": payload["calculated_at"],
                "selected_what_if": None,
            }
            if selected_what_if is not None:
                if UUID(selected_what_if["what_if_id"]) != what_if_id:
                    raise ValueError("what-if id does not match the request")
                if UUID(selected_what_if["assessment_id"]) != assessment_id:
                    raise ValueError("what-if belongs to another assessment")
                view["selected_what_if"] = {
                    "what_if_id": selected_what_if["what_if_id"],
                    "assessment_id": selected_what_if["assessment_id"],
                    "schema_version": selected_what_if["schema_version"],
                    "simulation_only": selected_what_if["simulation_only"],
                    "changed_fields": selected_what_if["changed_fields"],
                    "original": self._scoring_snapshot(selected_what_if["original"]),
                    "alternative": self._scoring_snapshot(selected_what_if["alternative"]),
                    "delta_percentage_points": selected_what_if["delta_percentage_points"],
                    "limitations_warning": selected_what_if["limitations_warning"],
                    "calculated_at": selected_what_if["calculated_at"],
                }
            return view
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelProtocolError("Main Backend returned an invalid scoring result") from exc

    @staticmethod
    def _scoring_score(score: dict[str, Any]) -> dict[str, Any]:
        if score["name"] != "synthetic_model_score":
            raise ValueError("unsupported score name")
        return {key: score[key] for key in ("name", "value", "display_percent")}

    @staticmethod
    def _scoring_factors(factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(factors) != 6 or {factor["feature"] for factor in factors} != SCORING_FEATURES:
            raise ValueError("scoring result must contain the six expected factors")
        keys = (
            "feature",
            "display_name",
            "input_value",
            "baseline_value",
            "logit_contribution",
            "direction",
            "rank",
        )
        return [{key: factor[key] for key in keys} for factor in factors]

    @classmethod
    def _scoring_snapshot(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "score": cls._scoring_score(snapshot["score"]),
            "factors": cls._scoring_factors(snapshot["factors"]),
        }
