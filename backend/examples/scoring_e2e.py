"""Real HTTP -> PostgreSQL -> ML -> RabbitMQ -> Qwen smoke; no model/HTTP mocks.

Run only against a local synthetic-data stack: python -m examples.scoring_e2e.
Creates two synthetic users and one draft; never deletes existing records.
"""

import argparse
import json
import secrets
import time
from uuid import uuid4

import httpx


def run(base_url, ai_timeout):
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=20) as api:

        def call(method, path, expected=200, **kwargs):
            response = api.request(method, "/api/v1" + path, **kwargs)
            if response.status_code != expected:
                # Credentials and request bodies must never enter failure output.
                code = response.json().get("code", response.json().get("detail", {}))
                raise RuntimeError(f"{method} {path}: HTTP {response.status_code}, {code}")
            return response.json()

        def register():
            credentials = {
                "email": f"scoring-{uuid4().hex}@example.com",
                "password": secrets.token_urlsafe(24),
            }
            call("POST", "/auth/register", expected=201, json=credentials)
            token = call("POST", "/auth/login", json=credentials)["access_token"]
            return {"Authorization": f"Bearer {token}"}

        owner, other = register(), register()
        call(
            "POST",
            "/auth/company",
            headers=owner,
            json={
                "company": {
                    "name": "Синтетический Scoring E2E",
                    "inn": "7700000009",
                    "registration_date": "2022-10-25",
                    "address": "Учебный адрес",
                    "industry": "62.01",
                },
                "financials": {
                    "annual_revenue": "5000000",
                    "monthly_expenses": "100000",
                    "monthly_debt_payments": "0",
                    "outstanding_debt": "0",
                    "credit_history": "average",
                    "overdue_days": 0,
                    "has_collateral": False,
                },
            },
        )
        products = call(
            "GET",
            "/credit-products/search",
            headers=owner,
            params={"purpose": "working_capital", "amount": "3000000", "term_months": 24},
        )
        if not products:
            raise RuntimeError("No seeded demonstration credit product for the E2E scenario")
        application = call(
            "POST",
            "/client/applications",
            expected=201,
            headers=owner,
            json={
                "product_id": products[0]["id"],
                "purpose": "working_capital",
                "amount": "3000000",
                "term_months": 24,
            },
        )
        application_id = application["id"]
        print(json.dumps({"step": "application_created", "application_id": application_id}))
        scoring_headers = {**owner, "Idempotency-Key": str(uuid4())}
        body = {
            "application_id": application_id,
            "expected_application_version": application["version"],
        }
        assessment = call(
            "POST", "/scoring/assessments", expected=201, headers=scoring_headers, json=body
        )
        aid = assessment["assessment_id"]
        path = f"/scoring/assessments/{aid}"
        assert (
            call("POST", "/scoring/assessments", headers=scoring_headers, json=body) == assessment
        )
        assert call("GET", path, headers=owner) == assessment
        assert len(assessment["explanation"]["factors"]) == 6
        assert assessment["demonstration_only"] is True
        assert api.get("/api/v1" + path).status_code == 401
        assert api.get("/api/v1" + path, headers=other).status_code == 404
        alternative = call(
            "POST",
            path + "/what-if",
            expected=201,
            headers={**owner, "Idempotency-Key": str(uuid4())},
            json={"changes": {"loan_amount": 1500000}},
        )
        assert len(alternative["alternative"]["factors"]) == 6
        assert alternative["original"]["score"] == assessment["score"]
        assert alternative["delta_percentage_points"] == round(
            (alternative["alternative"]["score"]["value"] - assessment["score"]["value"]) * 100, 4
        )
        selected = call(
            "GET", path, headers=owner, params={"what_if_id": alternative["what_if_id"]}
        )
        assert selected["selected_what_if"] == alternative
        after = call("GET", f"/client/applications/{application_id}", headers=owner)
        assert all(after[key] == application[key] for key in application)
        print(json.dumps({"assessment": assessment, "what_if": alternative}, ensure_ascii=False))
        cid = call("POST", "/chat/conversations", expected=201, headers=owner)["conversation_id"]
        rid = str(uuid4())
        call(
            "POST",
            f"/chat/conversations/{cid}/messages",
            expected=202,
            headers=owner,
            json={
                "request_id": rid,
                "application_id": application_id,
                "message": f"Объясни демонстрационный ML scoring {aid} и What-if "
                f"{alternative['what_if_id']}. Используй get_scoring_result.",
            },
        )
        deadline = time.monotonic() + ai_timeout
        while time.monotonic() < deadline:
            result = call("GET", f"/chat/requests/{rid}", headers=owner)
            if result["status"] in {"completed", "needs_clarification", "failed"}:
                assert result["status"] == "completed", result
                assert "синтетическ" in result["result"]["answer"].lower()
                print(json.dumps({"qwen": result["result"]}, ensure_ascii=False))
                return
            time.sleep(1)
        raise RuntimeError("Timed out waiting for real RabbitMQ / Qwen result")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ai-timeout", type=int, default=180)
    args = parser.parse_args()
    run(args.base_url, args.ai_timeout)
