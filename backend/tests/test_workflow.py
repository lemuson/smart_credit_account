from decimal import Decimal

from conftest import company, financials


def test_happy_path_disbursement_and_feed(flow):
    created = flow.create()
    assert created["company"] == company()
    products = flow.api.get(
        "/api/v1/catalog/products?purpose=working_capital&amount=1000000&term_months=24",
        headers=flow.headers["client"],
    )
    assert products.status_code == 200 and products.json()[0]["id"] == flow.product_id
    preview = flow.api.post(
        "/api/v1/catalog/calculate-preview",
        headers=flow.headers["client"],
        json={"product_id": flow.product_id, "amount": "1000000", "term_months": 24},
    )
    assert preview.status_code == 200
    approved = flow.approve()
    assert approved["status"] == "OFFER_READY"
    assert approved["decision"]["score"] == 830
    assert approved["decision"]["risk_category"] == "CATEGORY_A"
    rows = approved["offer"]["schedule"]
    assert len(rows) == 24
    assert sum(Decimal(row["principal"]) for row in rows) == Decimal("1000000")
    assert rows[-1]["balance"] == "0.00"
    accepted = flow.action("offer/accept")
    assert accepted.status_code == 200 and accepted.json()["status"] == "SIGNING"
    contract = flow.api.get(flow.base + "/contract", headers=flow.headers["client"]).json()
    signed = flow.action("sign", code="123456", contract_sha256=contract["sha256"])
    assert signed.status_code == 200 and signed.json()["status"] == "DISBURSED"
    assert flow.action("sign", code="123456", contract_sha256=contract["sha256"]).status_code == 409
    loans = flow.api.get("/api/v1/client/loans", headers=flow.headers["client"]).json()
    assert len(loans) == 1 and loans[0]["application_id"] == flow.id
    history = flow.get()["history"]
    assert [event["to_status"] for event in history if event["from_status"]] == [
        "SUBMITTED",
        "PRIMARY_REVIEW",
        "AUTOMATIC_ANALYSIS",
        "OFFER_READY",
        "OFFER_ACCEPTED",
        "SIGNING",
        "DISBURSED",
    ]
    feed = flow.api.get("/api/v1/client/feed", headers=flow.headers["client"])
    assert feed.status_code == 200
    assert {row["id"] for row in feed.json()["items"]} >= {"it", "issued"}


def test_clarification_returns_directly_to_officer_and_invalidates_checks(flow):
    flow.create()
    flow.submit_and_take()
    assert flow.action("run-external-checks", "officer").status_code == 200
    requested = flow.action(
        "request-clarification",
        "officer",
        comment="Уточните расходы и выписку",
        required_fields=["financials.monthly_expenses"],
        required_documents=["bank_statement"],
    )
    assert requested.status_code == 200 and requested.json()["status"] == "NEEDS_CLARIFICATION"
    assert flow.action("clarify", response="Данные проверены", confirmed=True).status_code == 422
    update = flow.api.put(
        flow.base,
        headers=flow.headers["client"],
        json={
            "expected_version": flow.version(),
            "financials": financials(monthly_expenses="600000"),
        },
    )
    assert update.status_code == 200
    flow.upload("bank_statement")
    reply = flow.action("clarify", response="Расходы исправлены, выписка приложена", confirmed=True)
    assert reply.status_code == 200 and reply.json()["status"] == "PRIMARY_REVIEW"
    old_checks = flow.action("pass-to-auto-analysis", "officer", comment="Проверено")
    assert (
        old_checks.status_code == 409
        and old_checks.json()["detail"]["code"] == "FRESH_EXTERNAL_CHECKS_REQUIRED"
    )
    assert flow.action("run-external-checks", "officer").status_code == 200
    decision = flow.action("pass-to-auto-analysis", "officer", comment="Проверено повторно")
    assert decision.status_code == 200 and decision.json()["status"] == "OFFER_READY"
    assert flow.get()["clarifications"][0]["response"] == "Расходы исправлены, выписка приложена"


def test_stop_factors_rejected_with_saved_reasons(flow):
    flow.create(group="bad")
    decision = flow.approve()
    assert decision["status"] == "REJECTED"
    assert {
        "COMPANY_NOT_ACTIVE",
        "ACCOUNTS_BLOCKED",
        "CURRENT_OVERDUE",
        "HISTORICAL_DEFAULT",
    } <= set(decision["decision"]["reasons"])
    assert decision["offer"] is None
    assert flow.action("offer/accept").status_code == 409


def test_high_debt_medium_score_rejected(flow):
    flow.create(
        group="warning",
        finance=financials(monthly_expenses="1950000", monthly_debt_payments="49000"),
    )
    decision = flow.approve()
    assert decision["status"] == "REJECTED"
    assert "DEBT_BURDEN_EXCEEDED" in decision["decision"]["reasons"]


def test_client_declines_offer(flow):
    flow.create()
    assert flow.approve()["status"] == "OFFER_READY"
    declined = flow.action("offer/decline")
    assert declined.status_code == 200 and declined.json()["status"] == "OFFER_DECLINED"
    assert flow.api.get(flow.base + "/contract", headers=flow.headers["client"]).status_code == 409
    assert flow.action("offer/accept").status_code == 409


def test_primary_rejection_and_assignment(flow):
    flow.create()
    flow.submit_and_take()
    assert flow.action("reject-primary", "officer2", comment="Отказ").status_code == 403
    rejected = flow.action("reject-primary", "officer", comment="Выявлены недостоверные сведения")
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    assert flow.action("run-external-checks", "officer").status_code == 409
