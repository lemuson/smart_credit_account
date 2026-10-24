from io import BytesIO

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.models import AuditEvent


def test_history_hides_saves_uploads_and_client_internal_review(flow):
    flow.create()
    before = flow.get()
    # Different decimal formatting must not change the application revision.
    payload = before["financials"] | {"annual_revenue": "24000000"}
    result = flow.api.put(
        flow.base,
        headers=flow.headers["client"],
        json={
            "expected_version": before["version"],
            "financials": payload,
        },
    )
    assert result.status_code == 200
    assert flow.get() == before
    payload["annual_revenue"] = "25000000"
    assert (
        flow.api.put(
            flow.base,
            headers=flow.headers["client"],
            json={
                "expected_version": before["version"],
                "financials": payload,
            },
        ).status_code
        == 200
    )
    flow.approve()
    client = flow.get()
    officer = flow.get("officer")
    actions = {event["action"] for event in client["history"]}
    assert actions.isdisjoint(
        {
            "APPLICATION_UPDATED",
            "DOCUMENT_UPLOADED",
            "DOCUMENT_DELETED",
            "EXTERNAL_CHECKS_COMPLETED",
            "PRIMARY_REVIEW_PASSED",
            "AUTOMATIC_ANALYSIS_STARTED",
        }
    )
    assert client["checks"] == []
    assert officer["checks"]
    assert "PRIMARY_REVIEW_PASSED" in {event["action"] for event in officer["history"]}
    with Session(flow.engine) as db:
        audit = list(db.scalars(select(AuditEvent).where(AuditEvent.application_id == flow.id)))
        assert {"APPLICATION_UPDATED", "DOCUMENT_UPLOADED"} <= {event.action for event in audit}
        assert sum(event.action == "APPLICATION_UPDATED" for event in audit) == 1


def test_notifications_read_state_is_persistent_idempotent_and_isolated(flow):
    flow.create()
    flow.submit_and_take()
    path = "/api/v1/notifications"
    client = flow.api.get(path, headers=flow.headers["client"]).json()
    officer = flow.api.get(path, headers=flow.headers["officer"]).json()
    assert client["unread_count"] == 2 and officer["unread_count"] == 1
    assert flow.api.get(path, headers=flow.headers["other"]).json()["items"] == []
    assert flow.api.get(path, headers=flow.headers["officer2"]).json()["items"] == []
    client_id, officer_id = client["items"][0]["id"], officer["items"][0]["id"]
    for _ in range(2):
        result = flow.api.post(
            path + "/read", headers=flow.headers["client"], json={"ids": [client_id]}
        )
        assert result.status_code == 200 and result.json()["unread_count"] == 1
    # A client cannot mark another user's event read.
    flow.api.post(path + "/read", headers=flow.headers["other"], json={"ids": [client_id]})
    assert flow.api.get(path, headers=flow.headers["other"]).json()["items"] == []
    assert flow.api.get(path, headers=flow.headers["officer"]).json()["unread_count"] == 1
    result = flow.api.post(
        path + "/read", headers=flow.headers["officer"], json={"ids": [officer_id]}
    )
    assert result.json()["unread_count"] == 0
    result = flow.api.post(path + "/read", headers=flow.headers["client"], json={"all": True})
    assert result.json()["unread_count"] == 0
    assert flow.api.get(path, headers=flow.headers["client"]).json()["unread_count"] == 0
    assert (
        flow.action("request-clarification", "officer", comment="Уточните сведения").status_code
        == 200
    )
    result = flow.api.get(path, headers=flow.headers["client"]).json()
    assert result["unread_count"] == 1 and result["items"][0]["title"] == "Нужно уточнить сведения"
    assert flow.api.get(path).status_code == 401


def test_contract_pdf_contains_fixed_terms_and_respects_access(flow):
    flow.create()
    assert (
        flow.api.get(flow.base + "/contract/pdf", headers=flow.headers["client"]).status_code == 409
    )
    flow.approve()
    assert flow.action("offer/accept").status_code == 200
    before = flow.get()
    response = flow.api.get(flow.base + "/contract/pdf", headers=flow.headers["client"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.content.startswith(b"%PDF-")
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert "УЧЕБНЫЙ КРЕДИТНЫЙ ДОГОВОР" in text
    assert before["company"]["inn"] in text and before["company"]["name"] in text
    assert "1 000 000,00 руб." in text
    assert before["contract"]["sha256"] in text
    assert "График платежей" in text and "123456" not in text
    assert flow.get() == before  # Preview does not mutate or sign the application.
    assert (
        flow.api.get(flow.base + "/contract/pdf", headers=flow.headers["client"]).content
        == response.content
    )
    assert (
        flow.api.get(flow.base + "/contract/pdf", headers=flow.headers["other"]).status_code == 404
    )
    staff = f"/api/v1/bank/applications/{flow.id}/contract/pdf"
    assert flow.api.get(staff, headers=flow.headers["officer"]).content == response.content
    signed = flow.action("sign", code="123456", contract_sha256=before["contract"]["sha256"])
    assert signed.status_code == 200
    assert (
        flow.api.get(flow.base + "/contract/pdf", headers=flow.headers["client"]).content
        == response.content
    )
