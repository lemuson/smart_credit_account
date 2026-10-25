"""API/storage/security tests. Numerical E2E requires the approved external artifacts."""

import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from ml_scoring.local_inference import LocalInferenceService
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.applications.models import Application, AuditEvent
from app.database import now
from app.profiles.models import Profile
from app.scoring.models import ScoringAssessment, ScoringWhatIf
from app.scoring.service import feature_snapshot, fingerprint

BASE = "/api/v1/scoring/assessments"


def validate_contract(payload, name):
    import jsonschema
    import yaml

    contract = yaml.safe_load(
        (
            Path(__file__).resolve().parents[2]
            / "ai/ml_scoring/docs/backend_integration_openapi.yaml"
        ).read_text()
    )
    schema = {"$ref": f"#/components/schemas/{name}", "components": contract["components"]}
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        payload
    )


def key_headers(flow, who="client", key=None):
    return {**flow.headers[who], "Idempotency-Key": key or str(uuid4())}


def stored_assessment(flow):
    """Explicit persistence fixture; these numbers are not an inference/E2E result."""
    flow.create()
    aid = str(uuid4())
    factors = [
        {
            "feature": name,
            "display_name": name,
            "input_value": value,
            "baseline_value": 0.0,
            "logit_contribution": 0.0,
            "direction": "neutral",
            "rank": index,
        }
        for index, (name, value) in enumerate(
            {
                "annual_revenue": 5000000.0,
                "credit_history": "good",
                "business_age_months": 48,
                "loan_amount": 3000000.0,
                "has_collateral": True,
                "loan_term_months": 24,
            }.items(),
            start=1,
        )
    ]
    payload = {
        "assessment_id": aid,
        "application_id": flow.id,
        "application_version": flow.version(),
        "schema_version": "1.0",
        "status": "completed",
        "demonstration_only": True,
        "model": {
            "model_id": "synthetic-credit-logreg",
            "model_version": "fixture-version",
            "family": "logistic_regression",
            "bundle_sha256": "a" * 64,
        },
        "score": {"name": "synthetic_model_score", "value": 0.5, "display_percent": 50.0},
        "explanation": {
            "baseline": {
                "method": "mean_in_transformed_train_space",
                "logit": 0.0,
                "reference_version": "1.0",
                "reference_sha256": "b" * 64,
            },
            "factors": factors,
            "consistency": {
                "model_logit": 0.0,
                "contribution_sum": 0.0,
                "reconstructed_logit": 0.0,
                "reconstruction_error": 0.0,
            },
        },
        "limitations_warning": "Тестовая демонстрационная оценка на синтетических данных.",
        "calculated_at": now().isoformat().replace("+00:00", "Z"),
        "selected_what_if": None,
    }
    with Session(flow.engine) as db, db.begin():
        application = db.get(Application, flow.id)
        features = feature_snapshot(application, now().date())
        org = db.scalar(select(Profile.id).where(Profile.user_id == flow.users["client"]))
        db.add(
            ScoringAssessment(
                id=aid,
                organization_id=org,
                application_id=flow.id,
                application_version=application.version,
                features=features,
                feature_sha256=fingerprint(features),
                response=payload,
            )
        )
    return aid, payload


def test_missing_runtime_and_application_validation(flow):
    flow.create()
    flow.api.app.state.scoring_service = None
    response = flow.api.post(BASE, headers=key_headers(flow), json={"application_id": flow.id})
    assert response.status_code == 503, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "SCORING_UNAVAILABLE"
    validate_contract(response.json(), "Problem")
    assert flow.api.get("/health/scoring").status_code == 503
    with Session(flow.engine) as db, db.begin():
        obj = db.get(Application, flow.id)
        obj.financials = {"annual_revenue": "5000000"}
    response = flow.api.post(BASE, headers=key_headers(flow), json={"application_id": flow.id})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "SCORING_INVALID_INPUT"
    with Session(flow.engine) as db:
        assert db.scalar(select(func.count()).select_from(ScoringAssessment)) == 0


def test_saved_read_without_model_and_tenant_isolation(flow):
    aid, payload = stored_assessment(flow)
    flow.api.app.state.scoring_service = None
    response = flow.api.get(f"{BASE}/{aid}", headers=flow.headers["client"])
    assert response.status_code == 200, response.text
    assert response.json() == payload
    validate_contract(response.json(), "AssessmentResponse")
    assert response.headers["cache-control"] == "private, no-store"
    for resource in (aid, str(uuid4())):
        response = flow.api.get(f"{BASE}/{resource}", headers=flow.headers["other"])
        assert response.status_code == 404
        assert response.json()["code"] == "SCORING_NOT_FOUND"
        assert (
            flow.api.post(
                f"{BASE}/{resource}/what-if",
                headers=key_headers(flow, "other"),
                json={"changes": {"loan_amount": 1500000}},
            ).status_code
            == 404
        )
    assert flow.api.get(f"{BASE}/{aid}").status_code == 401
    assert flow.api.get(f"{BASE}/{aid}", headers=flow.headers["officer"]).status_code == 403
    assert (
        flow.api.post(
            BASE, headers=key_headers(flow, "other"), json={"application_id": flow.id}
        ).status_code
        == 404
    )
    assert (
        flow.api.post(
            BASE,
            headers=key_headers(flow),
            json={"application_id": flow.id, "expected_application_version": flow.version() + 1},
        ).status_code
        == 409
    )
    assert (
        flow.api.post(
            f"{BASE}/{aid}/what-if",
            headers=key_headers(flow),
            json={"changes": {"loan_amount": 1500000}},
        ).status_code
        == 503
    )
    assert (
        flow.api.get(
            f"{BASE}/{aid}?what_if_id={uuid4()}", headers=flow.headers["client"]
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"loan_amount": None},
        {"loan_amount": "1000000"},
        {"loan_amount": True},
        {"has_collateral": 1},
        {"age": 40},
        {"approved": True},
        {"loan_term_months": 12.0},
        {"business_age_months": True},
        {"loan_term_months": 7},
    ],
)
def test_strict_what_if_input(flow, changes):
    response = flow.api.post(
        f"{BASE}/{uuid4()}/what-if", headers=key_headers(flow), json={"changes": changes}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "SCORING_INVALID_INPUT"


def test_snapshot_exact_mapping_and_no_defaults():
    obj = SimpleNamespace(
        company={"registration_date": "2022-10-26"},
        financials={
            "annual_revenue": "5000000.25",
            "credit_history": "good",
            "has_collateral": False,
        },
        amount=3000000,
        term_months=24,
    )
    values = feature_snapshot(obj, date(2026, 10, 25))
    assert values == {
        "annual_revenue": 5000000.25,
        "credit_history": "good",
        "has_collateral": False,
        "business_age_months": 47,
        "loan_amount": 3000000.0,
        "loan_term_months": 24,
    }
    obj.company = {}
    with pytest.raises(HTTPException) as error:
        feature_snapshot(obj, date(2026, 10, 25))
    assert error.value.detail["code"] == "SCORING_INVALID_INPUT"


@pytest.mark.scoring_e2e
def test_real_artifact_scoring_round_trip_and_what_if(flow):
    directory = os.environ.get("SCORING_E2E_MODELS_DIR")
    if not directory:
        pytest.skip("Approved ML artifacts unavailable; no substitute model is trained")
    service = LocalInferenceService.from_artifact_directory(Path(directory))
    flow.api.app.state.scoring_service = service
    flow.create()
    before = flow.get()
    headers = key_headers(flow)
    request = {"application_id": flow.id, "expected_application_version": flow.version()}
    response = flow.api.post(BASE, headers=headers, json=request)
    assert response.status_code == 201, response.text
    result = response.json()
    validate_contract(result, "AssessmentResponse")
    direct = service.score(
        {f["feature"]: f["input_value"] for f in result["explanation"]["factors"]}
    )
    assert result["score"]["value"] == direct.score.probability
    assert len(result["explanation"]["factors"]) == 6
    assert flow.api.post(BASE, headers=headers, json=request).status_code == 200
    assert flow.api.post(BASE, headers=headers, json={"application_id": flow.id}).status_code == 409
    aid = result["assessment_id"]
    assert flow.api.get(f"{BASE}/{aid}", headers=flow.headers["client"]).json() == result
    changed = {"changes": {"loan_amount": 1500000}}
    w_headers = key_headers(flow)
    response = flow.api.post(f"{BASE}/{aid}/what-if", headers=w_headers, json=changed)
    assert response.status_code == 201, response.text
    alternative = response.json()
    validate_contract(alternative, "WhatIfResponse")
    assert alternative["changed_fields"] == ["loan_amount"]
    assert len(alternative["alternative"]["factors"]) == 6
    assert alternative["original"]["score"] == result["score"]
    assert alternative["delta_percentage_points"] == round(
        (alternative["alternative"]["score"]["value"] - result["score"]["value"]) * 100, 4
    )
    replay = flow.api.post(f"{BASE}/{aid}/what-if", headers=w_headers, json=changed)
    assert replay.status_code == 200 and replay.json() == alternative
    selected = flow.api.get(
        f"{BASE}/{aid}?what_if_id={alternative['what_if_id']}", headers=flow.headers["client"]
    ).json()
    assert selected["selected_what_if"] == alternative
    after = flow.get()
    assert {k: v for k, v in after.items() if k != "history"} == {
        k: v for k, v in before.items() if k != "history"
    }
    flow.api.app.state.scoring_service = None
    assert flow.api.get(f"{BASE}/{aid}", headers=flow.headers["client"]).json() == result
    assert flow.api.post(BASE, headers=headers, json=request).json() == result
    with Session(flow.engine) as db:
        assert db.scalar(select(func.count()).select_from(ScoringAssessment)) == 1
        assert db.scalar(select(func.count()).select_from(ScoringWhatIf)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.like("scoring.%"))
            )
            == 2
        )


def test_delegated_scoring_readonly(flow):
    from datetime import timedelta

    import jwt
    from pydantic import SecretStr

    from app.ai.models import ChatJob
    from app.ai.service import build_request

    aid, payload = stored_assessment(flow)
    api = flow.api
    api.app.state.settings.ai_enabled = True
    api.app.state.settings.ai_service_token = SecretStr("test-service-identity")
    cid = api.post("/api/v1/chat/conversations", headers=flow.headers["client"]).json()[
        "conversation_id"
    ]
    rid = str(uuid4())
    response = api.post(
        f"/api/v1/chat/conversations/{cid}/messages",
        headers=flow.headers["client"],
        json={"request_id": rid, "message": f"Объясни ML-оценку {aid}"},
    )
    assert response.status_code == 202
    with Session(flow.engine) as db:
        envelope = build_request(db, db.get(ChatJob, rid), api.app.state.settings)
    headers = {
        "Authorization": envelope.trusted_context.authorization,
        "X-Service-Token": "test-service-identity",
        "X-User-ID": str(envelope.user_id),
        "X-Organization-ID": str(envelope.organization_id),
        "X-Request-ID": rid,
    }
    assert api.get(f"{BASE}/{aid}", headers=headers).json() == payload
    assert (
        api.post(
            BASE,
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"application_id": flow.id},
        ).status_code
        == 403
    )
    assert (
        api.post(
            f"{BASE}/{aid}/what-if",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"changes": {"loan_amount": 1500000}},
        ).status_code
        == 403
    )
    assert (
        api.get(f"{BASE}/{aid}", headers={**headers, "X-Service-Token": "bad"}).status_code == 401
    )
    assert (
        api.get(f"{BASE}/{aid}", headers={**headers, "X-Organization-ID": str(uuid4())}).status_code
        == 403
    )
    token = jwt.decode(headers["Authorization"].split()[1], options={"verify_signature": False})
    token["exp"] = int((now() - timedelta(minutes=1)).timestamp())
    expired = jwt.encode(
        token, api.app.state.settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    assert (
        api.get(
            f"{BASE}/{aid}", headers={**headers, "Authorization": f"Bearer {expired}"}
        ).status_code
        == 401
    )


def test_unit_adapter_persistence_replay_and_model_version(flow):
    """Unit boundary stub verifies storage/adapter only; never counted as model E2E."""
    from unittest.mock import Mock

    from ml_scoring.inference_schema import InferenceResponse

    aid, payload = stored_assessment(flow)
    diagnostics = {
        "reference_version": "1.0",
        "reference_sha256": "b" * 64,
        "reference_source_sha256": "c" * 64,
        "model_logit": 0.0,
        "baseline_logit": 0.0,
        "contribution_sum": 0.0,
        "reconstructed_logit": 0.0,
        "reconstruction_error": 0.0,
        "probability_from_logit": 0.5,
        "probability_error": 0.0,
        "transformed_feature_count": 9,
        "grouped_factor_count": 6,
    }
    output = InferenceResponse(
        model=payload["model"],
        score={"probability": 0.5, "display_percent": 50.0},
        factors=payload["explanation"]["factors"],
        diagnostics=diagnostics,
        limitations_warning=payload["limitations_warning"],
    )
    service = Mock(bundle_sha256="a" * 64, reference_sha256="b" * 64)
    service.bundle.training_version = "fixture-version"
    service.score.return_value = output
    flow.api.app.state.scoring_service = service
    before = flow.get()
    headers = key_headers(flow)
    body = {"application_id": flow.id, "expected_application_version": before["version"]}
    response = flow.api.post(BASE, headers=headers, json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    validate_contract(result, "AssessmentResponse")
    service.score.assert_called_once()
    assert len(service.score.call_args.args[0]) == 6
    response = flow.api.post(BASE, headers=headers, json=body)
    assert response.status_code == 200 and response.json() == result
    assert service.score.call_count == 1
    response = flow.api.post(BASE, headers=headers, json={"application_id": flow.id})
    assert response.status_code == 409 and response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    wid_headers = key_headers(flow)
    what_if = {"changes": {"loan_amount": 1500000}}
    response = flow.api.post(f"{BASE}/{aid}/what-if", headers=wid_headers, json=what_if)
    assert response.status_code == 201, response.text
    alternative = response.json()
    validate_contract(alternative, "WhatIfResponse")
    assert alternative["delta_percentage_points"] == 0
    assert service.score.call_count == 3
    assert (
        flow.api.post(f"{BASE}/{aid}/what-if", headers=wid_headers, json=what_if).status_code == 200
    )
    assert service.score.call_count == 3
    response = flow.api.post(
        f"{BASE}/{aid}/what-if",
        headers=key_headers(flow),
        json={"changes": {"loan_amount": 1000000}},
    )
    assert response.status_code == 422 and response.json()["code"] == "SCORING_NO_CHANGED_FIELDS"
    service.bundle_sha256 = "d" * 64
    response = flow.api.post(f"{BASE}/{aid}/what-if", headers=key_headers(flow), json=what_if)
    assert response.status_code == 409
    assert response.json()["code"] == "SCORING_MODEL_VERSION_UNAVAILABLE"
    after = flow.get()
    assert {k: v for k, v in after.items() if k != "history"} == {
        k: v for k, v in before.items() if k != "history"
    }
    flow.api.app.state.scoring_service = None
    assert (
        flow.api.get(f"{BASE}/{result['assessment_id']}", headers=flow.headers["client"]).json()
        == result
    )
    assert flow.api.post(BASE, headers=headers, json=body).status_code == 200
    assert (
        flow.api.post(f"{BASE}/{aid}/what-if", headers=wid_headers, json=what_if).status_code == 200
    )
    with Session(flow.engine) as db:
        assert db.scalar(select(func.count()).select_from(ScoringWhatIf)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action.like("scoring.%"))
            )
            == 2
        )

    # A real DB update during the stubbed CPU call must prevent saving a stale assessment.
    def concurrent_update(_features):
        from decimal import Decimal

        with Session(flow.engine) as db, db.begin():
            application = db.get(Application, flow.id)
            application.amount += Decimal("1.00")
        return output

    service.bundle_sha256 = "a" * 64
    service.score.side_effect = concurrent_update
    flow.api.app.state.scoring_service = service
    response = flow.api.post(BASE, headers=key_headers(flow), json=body)
    assert response.status_code == 409
    assert response.json()["code"] == "APPLICATION_VERSION_CONFLICT"
    with Session(flow.engine) as db:
        assert db.scalar(select(func.count()).select_from(ScoringAssessment)) == 2

    from ml_scoring.local_inference import UnsupportedInputRangeError

    service.score.side_effect = UnsupportedInputRangeError(
        [
            {
                "field": "annual_revenue",
                "value": 1,
                "supported_minimum": 300000,
                "supported_maximum": 120000000,
                "message": "outside supported range",
            }
        ]
    )
    response = flow.api.post(BASE, headers=key_headers(flow), json={"application_id": flow.id})
    assert response.status_code == 422
    assert response.json()["code"] == "SCORING_UNSUPPORTED_RANGE"
    assert "value" not in response.json()["errors"][0]
