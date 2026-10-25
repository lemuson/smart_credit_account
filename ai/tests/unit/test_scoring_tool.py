from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import (
    BackendAccessDenied,
    BackendConflict,
    BackendNotFound,
    DependencyUnavailable,
    ModelProtocolError,
    ToolValidationError,
)
from app.integrations.backend_client import BackendClient
from app.schemas.messages import ChatRequest
from app.tools.banking_tools import build_banking_registry

ASSESSMENT_ID = UUID("71000000-0000-0000-0000-000000000001")
WHAT_IF_ID = UUID("73000000-0000-0000-0000-000000000001")
FEATURES = (
    "annual_revenue",
    "credit_history",
    "business_age_months",
    "loan_amount",
    "has_collateral",
    "loan_term_months",
)


def _factors() -> list[dict[str, Any]]:
    return [
        {
            "feature": feature,
            "display_name": feature,
            "input_value": index,
            "baseline_value": 0,
            "logit_contribution": index / 10,
            "direction": "positive",
            "rank": index,
        }
        for index, feature in enumerate(FEATURES, start=1)
    ]


def scoring_payload(*, with_what_if: bool = False) -> dict[str, Any]:
    score = {
        "name": "synthetic_model_score",
        "value": 0.7257224270636591,
        "display_percent": 72.57,
    }
    payload: dict[str, Any] = {
        "assessment_id": str(ASSESSMENT_ID),
        "application_id": "30000000-0000-0000-0000-000000000001",
        "application_version": 7,
        "schema_version": "1.0",
        "status": "completed",
        "model": {
            "model_id": "synthetic-credit-logreg",
            "model_version": "1.0",
            "family": "logistic_regression",
            "bundle_sha256": "a" * 64,
        },
        "demonstration_only": True,
        "score": score,
        "explanation": {
            "baseline": {
                "method": "mean_in_transformed_train_space",
                "logit": 0.28,
                "reference_version": "1.0",
            },
            "factors": _factors(),
            "consistency": {"model_logit": 0.97},
        },
        "limitations_warning": (
            "Демонстрационная ML-оценка обучена на синтетических данных и не является "
            "решением банка."
        ),
        "calculated_at": "2026-10-22T10:15:30.123Z",
        "selected_what_if": None,
    }
    if with_what_if:
        payload["selected_what_if"] = {
            "what_if_id": str(WHAT_IF_ID),
            "assessment_id": str(ASSESSMENT_ID),
            "schema_version": "1.0",
            "simulation_only": True,
            "changed_fields": ["loan_amount"],
            "original": {"score": score, "factors": _factors()},
            "alternative": {
                "score": {
                    "name": "synthetic_model_score",
                    "value": 0.6109552629501994,
                    "display_percent": 61.1,
                },
                "factors": _factors(),
            },
            "delta_percentage_points": -11.47,
            "limitations_warning": "What-if — модельная симуляция, а не гарантия.",
            "calculated_at": "2026-10-22T10:20:00Z",
        }
    return payload


@pytest.mark.asyncio
async def test_get_scoring_result_uses_trusted_context_and_minimizes_data(
    chat_request: ChatRequest,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/scoring/assessments/{ASSESSMENT_ID}"
        assert request.headers["Authorization"] == "Bearer demo-user-token"
        assert request.headers["X-User-ID"] == str(chat_request.user_id)
        assert request.headers["X-Organization-ID"] == str(chat_request.organization_id)
        payload = scoring_payload()
        payload["secret_internal_field"] = "must-not-leak"
        payload["score"]["raw_feature_snapshot"] = {"annual_revenue": 1}
        payload["explanation"]["baseline"]["reference_sha256"] = "b" * 64
        payload["explanation"]["factors"][0]["customer_name"] = "must-not-leak"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://backend"
    ) as http:
        result = await BackendClient(Settings(_env_file=None), http).get_scoring_result(
            chat_request, ASSESSMENT_ID
        )

    assert len(result["explanation"]["factors"]) == 6
    assert result["score"]["display_percent"] == 72.57
    assert "application_id" not in result
    assert "consistency" not in result["explanation"]
    assert "bundle_sha256" not in result["model"]
    assert "secret_internal_field" not in result
    assert "raw_feature_snapshot" not in result["score"]
    assert "reference_sha256" not in result["explanation"]["baseline"]
    assert "customer_name" not in result["explanation"]["factors"][0]


@pytest.mark.asyncio
async def test_get_scoring_result_includes_requested_what_if(
    chat_request: ChatRequest,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params["what_if_id"] == str(WHAT_IF_ID)
        return httpx.Response(200, json=scoring_payload(with_what_if=True))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://backend"
    ) as http:
        result = await BackendClient(Settings(_env_file=None), http).get_scoring_result(
            chat_request, ASSESSMENT_ID, WHAT_IF_ID
        )

    what_if = result["selected_what_if"]
    assert what_if["what_if_id"] == str(WHAT_IF_ID)
    assert len(what_if["original"]["factors"]) == 6
    assert len(what_if["alternative"]["factors"]) == 6


@pytest.mark.asyncio
async def test_scoring_tool_rejects_invalid_uuid_and_identity_arguments(
    chat_request: ChatRequest,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        base_url="http://backend",
    ) as http:
        registry = build_banking_registry(BackendClient(Settings(_env_file=None), http))
        with pytest.raises(ToolValidationError):
            await registry.execute(
                "get_scoring_result", {"assessment_id": "not-a-uuid"}, chat_request
            )
        with pytest.raises(ToolValidationError):
            await registry.execute(
                "get_scoring_result",
                {"assessment_id": str(ASSESSMENT_ID), "organization_id": "attacker"},
                chat_request,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, BackendAccessDenied),
        (403, BackendAccessDenied),
        (404, BackendNotFound),
        (409, BackendConflict),
        (503, DependencyUnavailable),
    ],
)
async def test_get_scoring_result_maps_backend_errors(
    chat_request: ChatRequest, status: int, error_type: type[Exception]
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status)),
        base_url="http://backend",
    ) as http:
        with pytest.raises(error_type):
            await BackendClient(Settings(_env_file=None), http).get_scoring_result(
                chat_request, ASSESSMENT_ID, WHAT_IF_ID
            )


@pytest.mark.asyncio
async def test_get_scoring_result_maps_timeout(chat_request: ChatRequest) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow backend", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(timeout), base_url="http://backend"
    ) as http:
        with pytest.raises(DependencyUnavailable):
            await BackendClient(Settings(_env_file=None), http).get_scoring_result(
                chat_request, ASSESSMENT_ID
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["five_factors", "missing_what_if", "foreign_what_if"])
async def test_get_scoring_result_rejects_invalid_backend_payload(
    chat_request: ChatRequest, fault: str
) -> None:
    payload = deepcopy(scoring_payload(with_what_if=fault == "foreign_what_if"))
    requested_what_if: UUID | None = WHAT_IF_ID
    if fault == "five_factors":
        payload["explanation"]["factors"].pop()
        requested_what_if = None
    elif fault == "foreign_what_if":
        payload["selected_what_if"]["what_if_id"] = "73000000-0000-0000-0000-000000000099"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        base_url="http://backend",
    ) as http:
        with pytest.raises(ModelProtocolError):
            await BackendClient(Settings(_env_file=None), http).get_scoring_result(
                chat_request, ASSESSMENT_ID, requested_what_if
            )
