from datetime import timedelta
from decimal import Decimal

import jwt
import pytest
from conftest import PASSWORD, company, financials
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.applications.models import Application
from app.applications.schemas import VersionAction
from app.applications.service import ApplicationService
from app.auth.models import User
from app.database import now


def test_authentication_and_staff_creation(env):
    api, headers, _, users, _ = env
    assert api.get("/api/v1/auth/me").status_code == 401
    assert api.get("/api/v1/profile", headers={"X-User-ID": users["client"]}).status_code == 401
    assert api.get("/api/v1/auth/me", headers={"Authorization": "Bearer bad"}).status_code == 401
    expired = jwt.encode(
        {
            "sub": users["client"],
            "iat": now() - timedelta(hours=2),
            "exp": now() - timedelta(hours=1),
            "iss": "smart-credit",
            "aud": "smart-credit-api",
        },
        "test-secret-" * 4,
        algorithm="HS256",
    )
    assert (
        api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code
        == 401
    )
    assert (
        api.post(
            "/api/v1/auth/login", json={"email": "client@example.com", "password": "wrong"}
        ).status_code
        == 401
    )
    assert (
        api.post(
            "/api/v1/auth/register",
            json={"email": "forged@example.com", "password": PASSWORD, "role": "ADMIN"},
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/api/v1/admin/users",
            headers=headers["client"],
            json={"email": "staff@example.com", "password": PASSWORD, "role": "BANK_OFFICER"},
        ).status_code
        == 403
    )
    created = api.post(
        "/api/v1/admin/users",
        headers=headers["admin"],
        json={"email": "staff@example.com", "password": PASSWORD, "role": "BANK_OFFICER"},
    )
    assert created.status_code == 201 and created.json()["role"] == "BANK_OFFICER"
    assert "password_hash" not in created.json()
    assert (
        api.patch(
            f"/api/v1/admin/users/{users['client']}",
            headers=headers["admin"],
            json={"active": False},
        ).status_code
        == 200
    )
    assert api.get("/api/v1/auth/me", headers=headers["client"]).status_code == 401


def test_acl_drafts_documents_and_read_only_validation(flow):
    flow.create()
    document = flow.upload()
    for path in [
        flow.base,
        f"/api/v1/applications/{flow.id}/status",
        flow.base + "/documents/" + document["id"],
    ]:
        assert flow.api.get(path, headers=flow.headers["other"]).status_code == 404
    assert (
        flow.api.get(
            f"/api/v1/bank/applications/{flow.id}/dossier", headers=flow.headers["officer"]
        ).status_code
        == 404
    )
    assert (
        flow.api.get("/api/v1/bank/applications/queue", headers=flow.headers["client"]).status_code
        == 403
    )
    assert flow.api.get(flow.base, headers=flow.headers["officer"]).status_code == 403
    before = flow.get()
    for _ in range(2):
        result = flow.api.post(
            f"/api/v1/applications/{flow.id}/validate", headers=flow.headers["client"]
        )
        assert result.status_code == 200 and not result.json()["valid"]
    assert flow.get() == before
    assert flow.action("submit", confirmed=True).status_code == 422
    assert (
        flow.api.post(
            f"/api/v1/applications/{flow.id}/validate", headers=flow.headers["other"]
        ).status_code
        == 404
    )


def test_document_limits_formats_and_deletion(flow):
    flow.create()
    for content, mime, expected in [
        (b"%PDF-" + b"x" * 1024, "application/pdf", 413),
        (b"not-a-pdf", "application/pdf", 422),
        (b"<script>", "text/html", 422),
    ]:
        response = flow.api.post(
            flow.base + "/documents",
            headers=flow.headers["client"],
            data={"kind": "registration", "expected_version": flow.version()},
            files={"file": ("bad.pdf", content, mime)},
        )
        assert response.status_code == expected
    doc = flow.upload()
    downloaded = flow.api.get(flow.base + "/documents/" + doc["id"], headers=flow.headers["client"])
    assert downloaded.status_code == 200 and downloaded.content.startswith(b"%PDF-")
    assert downloaded.headers["Content-Disposition"] == "attachment"
    deleted = flow.api.delete(
        flow.base + "/documents/" + doc["id"] + f"?expected_version={flow.version()}",
        headers=flow.headers["client"],
    )
    assert deleted.status_code == 204
    assert (
        flow.api.get(
            flow.base + "/documents/" + doc["id"], headers=flow.headers["client"]
        ).status_code
        == 404
    )


def test_version_and_illegal_transitions(flow):
    flow.create()
    old_version = flow.version()
    flow.upload()
    stale = flow.api.put(
        flow.base,
        headers=flow.headers["client"],
        json={"expected_version": old_version, "amount": "500000"},
    )
    assert stale.status_code == 409
    assert flow.action("pass-to-auto-analysis", "officer", comment="Недопустимо").status_code == 404
    flow.upload("financial_statements")
    assert flow.action("submit", confirmed=False).status_code == 422
    assert flow.action("submit", confirmed=True).status_code == 200
    assert (
        flow.api.put(
            flow.base,
            headers=flow.headers["client"],
            json={"expected_version": flow.version(), "amount": "500000"},
        ).status_code
        == 409
    )
    assert flow.action("take-to-work", "officer").status_code == 200
    assert (
        flow.action("pass-to-auto-analysis", "officer", comment="Без проверок").status_code == 409
    )


def test_concurrent_claim_is_atomic(flow):
    flow.create()
    flow.upload()
    flow.upload("financial_statements")
    assert flow.action("submit", confirmed=True).status_code == 200
    with Session(flow.engine) as first, Session(flow.engine) as second:
        officer1 = first.get(User, flow.users["officer"])
        officer2 = second.get(User, flow.users["officer2"])
        service1, service2 = ApplicationService(first), ApplicationService(second)
        app1 = service1.get(flow.id, officer1)
        app2 = service2.get(flow.id, officer2)
        version = app1.version
        service1.take(app1, VersionAction(expected_version=version), officer1)
        first.commit()
        with pytest.raises(StaleDataError):
            service2.take(app2, VersionAction(expected_version=version), officer2)
        second.rollback()
    assert flow.get()["assigned_manager_id"] == flow.users["officer"]
    assert (
        len([event for event in flow.get()["history"] if event["action"] == "ASSIGNED_TO_OFFICER"])
        == 1
    )


def test_signing_hash_expiry_and_persistent_attempt_limit(flow):
    flow.create()
    flow.approve()
    assert flow.action("offer/accept").status_code == 200
    digest = flow.get()["contract"]["sha256"]
    assert flow.action("sign", code="123456", contract_sha256="0" * 64).status_code == 409
    for _ in range(5):
        assert flow.action("sign", code="999999", contract_sha256=digest).status_code == 422
    assert flow.action("sign", code="123456", contract_sha256=digest).status_code == 429
    with Session(flow.engine) as session, session.begin():
        app = session.get(Application, flow.id)
        assert app.signing_attempts == 5
        app.signing_attempts = 0
        app.signing_expires_at = now() - timedelta(seconds=1)
    assert flow.action("sign", code="123456", contract_sha256=digest).status_code == 409


def test_loan_history_prefill_and_tenant_isolation(flow):
    payload = {
        "client_id": flow.users["client"],
        "external_reference": "demo-old-001",
        "amount": "2000000",
        "outstanding_balance": "900000",
        "monthly_payment": "85000",
        "term_months": 36,
        "annual_rate": "15",
        "status": "active",
        "overdue_days": 0,
        "company_snapshot": company(),
        "financials_snapshot": financials(),
    }
    response = flow.api.post(
        "/api/v1/bank/loans/import", headers=flow.headers["officer"], json=payload
    )
    assert response.status_code == 201, response.text
    loan = response.json()
    assert (
        flow.api.post(
            "/api/v1/bank/loans/import", headers=flow.headers["officer"], json=payload
        ).status_code
        == 409
    )
    assert (
        flow.api.get(
            "/api/v1/client/loans/" + loan["id"], headers=flow.headers["other"]
        ).status_code
        == 404
    )
    data = {
        "product_id": flow.product_id,
        "purpose": "working_capital",
        "amount": "1000000",
        "term_months": 24,
        "source_loan_id": loan["id"],
    }
    foreign = flow.api.post("/api/v1/client/applications", headers=flow.headers["other"], json=data)
    assert foreign.status_code == 404
    draft = flow.api.post("/api/v1/client/applications", headers=flow.headers["client"], json=data)
    assert draft.status_code == 201, draft.text
    flow.id = draft.json()["id"]
    assert draft.json()["company"] == company()
    assert Decimal(draft.json()["financials"]["monthly_debt_payments"]) == Decimal("85000")
    assert Decimal(draft.json()["financials"]["outstanding_debt"]) == Decimal("900000")
    flow.submit_and_take()
    assert flow.action("run-external-checks", "officer").status_code == 200
    dossier = flow.get()
    assert not dossier["checks"][-1]["results"]["discrepancies"]
    assert "signing_code_hash" not in dossier


def test_input_validation(env):
    api, headers, product_id, _, _ = env
    for updates in [
        {"amount": "NaN"},
        {"amount": "1.001"},
        {"term_months": 0},
        {"status": "DISBURSED"},
    ]:
        response = api.post(
            "/api/v1/client/applications",
            headers=headers["client"],
            json={
                "product_id": product_id,
                "purpose": "working_capital",
                "amount": "1000000",
                "term_months": 24,
                **updates,
            },
        )
        assert response.status_code == 422
    assert (
        api.post(
            "/api/v1/auth/company",
            headers=headers["client"],
            json={"company": company() | {"inn": "1111111111"}},
        ).status_code
        == 422
    )
    assert (
        api.get("/api/v1/auth/company/suggest/1111111111", headers=headers["client"]).status_code
        == 422
    )
    assert (
        api.get(
            "/api/v1/credit-products/search?purpose=equipment&amount=1&term_months=24",
            headers=headers["client"],
        ).json()
        == []
    )


def test_password_whitespace_is_preserved_and_errors_do_not_echo_it(env):
    api, _, _, _, _ = env
    password = "  test-password-with-spaces  "
    registered = api.post(
        "/api/v1/auth/register", json={"email": "spaces@example.com", "password": password}
    )
    assert registered.status_code == 201
    assert (
        api.post(
            "/api/v1/auth/login", json={"email": "spaces@example.com", "password": password}
        ).status_code
        == 200
    )
    assert (
        api.post(
            "/api/v1/auth/login", json={"email": "spaces@example.com", "password": password.strip()}
        ).status_code
        == 401
    )
    invalid = api.post(
        "/api/v1/auth/register", json={"email": "spaces2@example.com", "password": "secret"}
    )
    assert invalid.status_code == 422 and "secret" not in invalid.text


def test_large_money_is_persisted_without_float_precision_loss(flow):
    product = flow.api.get(
        f"/api/v1/credit-products/{flow.product_id}", headers=flow.headers["client"]
    ).json()
    data = {key: value for key, value in product.items() if key not in {"id", "demonstration_only"}}
    data["max_amount"] = "99999999999999.99"
    updated = flow.api.put(
        f"/api/v1/credit-products/{flow.product_id}", headers=flow.headers["admin"], json=data
    )
    assert updated.status_code == 200 and updated.json()["max_amount"] == "99999999999999.99"
    created = flow.api.post(
        "/api/v1/client/applications",
        headers=flow.headers["client"],
        json={
            "product_id": flow.product_id,
            "purpose": "working_capital",
            "amount": "99999999999999.99",
            "term_months": 24,
        },
    )
    assert created.status_code == 201 and created.json()["amount"] == "99999999999999.99"
    fetched = flow.api.get(
        "/api/v1/client/applications/" + created.json()["id"], headers=flow.headers["client"]
    )
    assert fetched.status_code == 200 and fetched.json()["amount"] == "99999999999999.99"


def test_noop_save_preserves_revision_checks_and_single_draft(flow):
    flow.create()
    before = flow.get()
    response = flow.api.put(
        flow.base,
        headers=flow.headers["client"],
        json={
            "expected_version": before["version"],
            "company": before["company"],
            "financials": before["financials"],
        },
    )
    assert response.status_code == 200, response.text
    assert flow.get() == before
    flow.submit_and_take()
    assert flow.action("run-external-checks", "officer").status_code == 200
    client_view = flow.get()
    assert client_view["status"] == "PRIMARY_REVIEW"
    assert sum(event["action"] == "DRAFT_CREATED" for event in client_view["history"]) == 1
    assert any(event["action"] == "DOCUMENT_UPLOADED" for event in client_view["history"])
    listed = flow.api.get("/api/v1/client/applications", headers=flow.headers["client"]).json()
    assert len(listed) == 1 and listed[0]["id"] == flow.id
