from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from conftest import company, financials
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.products.service import ProductService
from app.profiles.service import ProfileService

DRAFTS = "/api/v1/client/application-drafts"


def draft_body(flow, **overrides):
    finance = financials()
    for key in ["monthly_debt_payments", "outstanding_debt"]:
        finance.pop(key)
    finance["overdue_days"] = str(finance["overdue_days"])
    return {
        "draft_id": str(uuid4()),
        "product_id": flow.product_id,
        "purpose": "working_capital",
        "amount": "1000000",
        "term_months": 24,
        "company": company() | {"name": "Изменённая компания"},
        "financials": finance,
        **overrides,
    }


def test_partial_draft_is_not_an_application_and_resumes_same_record(flow):
    # First visit/validation does not create a draft; incomplete input can be saved later.
    assert flow.api.get(DRAFTS, headers=flow.headers["client"]).json() == []
    assert flow.api.get(DRAFTS + "/prefill", headers=flow.headers["client"]).status_code == 200
    assert flow.api.get(DRAFTS, headers=flow.headers["client"]).json() == []
    result = flow.api.post(
        DRAFTS + "/validate", headers=flow.headers["client"], json={"company": company()}
    )
    assert result.status_code == 200
    assert flow.api.get(DRAFTS, headers=flow.headers["client"]).json() == []
    body = draft_body(
        flow,
        company={"name": "Ещё не заполнено", "inn": "770"},
        financials={"annual_revenue": "", "overdue_days": ""},
    )
    result = flow.api.post(DRAFTS, headers=flow.headers["client"], json=body)
    assert result.status_code == 201, result.text
    draft = result.json()
    flow.id = draft["id"]
    assert draft["company"]["inn"] == "770"
    assert draft["history"] == []
    assert flow.api.get("/api/v1/client/applications", headers=flow.headers["client"]).json() == []
    assert (
        flow.api.get(
            "/api/v1/client/applications?status=DRAFT", headers=flow.headers["client"]
        ).json()
        == []
    )
    assert (
        flow.api.get("/api/v1/bank/applications/queue", headers=flow.headers["officer"]).json()
        == []
    )
    assert flow.api.get(DRAFTS, headers=flow.headers["client"]).json()[0]["id"] == flow.id
    assert flow.api.get(DRAFTS, headers=flow.headers["other"]).json() == []
    assert flow.api.get(DRAFTS, headers=flow.headers["officer"]).status_code == 403
    assert flow.action("submit", confirmed=True).status_code == 422
    payload = {
        "expected_version": draft["version"],
        "company": company(),
        "financials": draft_body(flow)["financials"],
    }
    assert (
        flow.api.put(
            DRAFTS + "/" + flow.id, headers=flow.headers["other"], json=payload
        ).status_code
        == 404
    )
    # Retrying a create after a lost response reuses the same draft ID.
    assert flow.api.post(DRAFTS, headers=flow.headers["client"], json=body).json()["id"] == flow.id
    assert len(flow.api.get(DRAFTS, headers=flow.headers["client"]).json()) == 1
    updated = flow.api.put(DRAFTS + "/" + flow.id, headers=flow.headers["client"], json=payload)
    assert updated.status_code == 200, updated.text
    assert isinstance(updated.json()["financials"]["overdue_days"], int)
    stale = flow.api.put(DRAFTS + "/" + flow.id, headers=flow.headers["client"], json=payload)
    assert stale.status_code == 409
    flow.submit_and_take()
    assert flow.api.get(DRAFTS, headers=flow.headers["client"]).json() == []
    applications = flow.api.get(
        "/api/v1/client/applications", headers=flow.headers["client"]
    ).json()
    assert len(applications) == 1 and applications[0]["id"] == body["draft_id"]


def import_bank_loan(flow, payment="85000", debt="900000"):
    response = flow.api.post(
        "/api/v1/bank/loans/import",
        headers=flow.headers["officer"],
        json={
            "client_id": flow.users["client"],
            "external_reference": str(uuid4()),
            "amount": "2000000",
            "outstanding_balance": debt,
            "monthly_payment": payment,
            "term_months": 36,
            "annual_rate": "15",
            "status": "active",
            "overdue_days": 0,
            "company_snapshot": company(),
            "financials_snapshot": financials(),
        },
    )
    assert response.status_code == 201, response.text


def test_bank_payments_are_added_to_external_profile_payments_and_not_editable(flow):
    created = flow.create(
        finance=financials(monthly_debt_payments="40000", outstanding_debt="250000")
    )
    import_bank_loan(flow)
    import_bank_loan(flow, "15000", "100000")
    actual = flow.get()["credit_obligations"]
    assert Decimal(actual["bank_monthly_payments"]) == Decimal("100000")
    assert Decimal(actual["external_monthly_payments"]) == Decimal("40000")
    assert Decimal(actual["total_monthly_payments"]) == Decimal("140000")
    assert Decimal(actual["total_outstanding_debt"]) == Decimal("1250000")
    profile_before = flow.api.get("/api/v1/profile", headers=flow.headers["client"]).json()
    assert profile_before["credit_obligations"] == actual
    for field in ["monthly_debt_payments", "outstanding_debt"]:
        result = flow.api.put(
            flow.base,
            headers=flow.headers["client"],
            json={
                "expected_version": flow.version(),
                "financials": created["financials"] | {field: "0"},
            },
        )
        assert result.status_code == 422
        assert result.json()["detail"]["code"] == "EXTERNAL_LIABILITIES_READ_ONLY"
    # The draft API also rejects protected fields; they cannot be smuggled into partial data.
    body = draft_body(flow)
    body["financials"]["monthly_debt_payments"] = "0"
    assert flow.api.post(DRAFTS, headers=flow.headers["client"], json=body).status_code == 422
    assert flow.api.get("/api/v1/profile", headers=flow.headers["client"]).json() == profile_before
    approved = flow.approve()
    assert approved["status"] == "OFFER_READY"
    assert Decimal(approved["decision"]["metrics"]["existing_monthly_payments"]) == Decimal(
        "140000"
    )
    results = flow.get("officer")["checks"][-1]["results"]
    assert results["discrepancies"] == []
    assert Decimal(results["bki"]["monthly_payments"]) == Decimal("140000")


def test_sync_profile_cannot_overwrite_other_bank_payments(flow):
    flow.create(finance=financials(monthly_debt_payments="40000", outstanding_debt="250000"))
    response = flow.api.put(
        "/api/v1/profile",
        headers=flow.headers["client"],
        json={
            "company": company(),
            "external_liabilities": {
                "monthly_debt_payments": "55000",
                "outstanding_debt": "200000",
            },
        },
    )
    assert response.status_code == 200
    assert (
        flow.api.put(
            flow.base,
            headers=flow.headers["client"],
            json={
                "expected_version": flow.version(),
                "company": company() | {"industry": "63.11"},
            },
        ).status_code
        == 200
    )
    synced = flow.action("sync-profile")
    assert synced.status_code == 200, synced.text
    profile = flow.api.get("/api/v1/profile", headers=flow.headers["client"]).json()
    assert profile["company"]["industry"] == "63.11"
    assert Decimal(profile["financials"]["monthly_debt_payments"]) == Decimal("55000")
    assert Decimal(profile["financials"]["outstanding_debt"]) == Decimal("200000")


def test_lists_and_timeline_are_newest_first_and_hide_analysis_events(flow):
    first = flow.create()
    first_id = first["id"]
    flow.approve()
    client_history = flow.get()["history"]
    assert {row["action"] for row in client_history}.isdisjoint(
        {
            "DRAFT_CREATED",
            "EXTERNAL_CHECKS_COMPLETED",
            "PRIMARY_REVIEW_PASSED",
            "AUTOMATIC_ANALYSIS_STARTED",
            "AUTOMATIC_DECISION",
        }
    )
    assert [row["created_at"] for row in client_history] == sorted(
        (row["created_at"] for row in client_history),
        reverse=True,
    )
    flow.create()
    flow.submit_and_take()
    with Session(flow.engine) as db, db.begin():
        obj = db.get(Application, first_id)
        obj.created_at -= timedelta(days=2)
    for who, path in [
        ("client", "/api/v1/client/applications"),
        ("officer", "/api/v1/bank/applications/queue"),
    ]:
        rows = flow.api.get(path, headers=flow.headers[who]).json()
        assert [row["id"] for row in rows] == [flow.id, first_id]
        assert (
            flow.api.get(path + "?offset=0&limit=1", headers=flow.headers[who]).json()[0]["id"]
            == flow.id
        )


def test_product_eligibility_uses_sum_of_bank_and_other_bank_payments(flow):
    flow.create(
        finance=financials(
            annual_revenue="1200000", monthly_expenses="1000", monthly_debt_payments="40000"
        )
    )
    import_bank_loan(flow, payment="50000")
    with Session(flow.engine) as db:
        profile = ProfileService(db).get(flow.users["client"])
        assert ProductService(db).search("working_capital", Decimal("100000"), 24, profile) == []
