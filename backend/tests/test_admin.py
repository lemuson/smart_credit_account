def test_versioned_risk_policy_changes_future_decisions_only(flow):
    flow.create()
    approved = flow.approve()
    original_id = flow.id
    original_decision = approved["decision"]
    assert approved["decision"]["policy_snapshot"]["category_a_min"] == 750
    endpoint = "/api/v1/admin/risk-policy"
    assert flow.api.get(endpoint, headers=flow.headers["client"]).status_code == 403
    policy = flow.api.get(endpoint, headers=flow.headers["admin"]).json()
    assert policy["version"] == 0
    rules = policy["rules"] | {"category_a_min": 850, "category_b_min": 840, "category_c_min": 835}
    updated = flow.api.put(
        endpoint, headers=flow.headers["admin"], json={"expected_version": 0, "rules": rules}
    )
    assert updated.status_code == 200 and updated.json()["version"] == 1
    assert (
        flow.api.put(
            endpoint, headers=flow.headers["admin"], json={"expected_version": 0, "rules": rules}
        ).status_code
        == 409
    )
    assert (
        flow.api.put(
            endpoint,
            headers=flow.headers["admin"],
            json={"expected_version": 1, "rules": rules | {"category_b_min": 850}},
        ).status_code
        == 422
    )
    flow.create()
    rejected = flow.approve()
    assert rejected["status"] == "REJECTED" and "LOW_SCORE" in rejected["decision"]["reasons"]
    old = flow.api.get(
        f"/api/v1/client/applications/{original_id}", headers=flow.headers["client"]
    ).json()
    assert old["decision"] == original_decision
    history = flow.api.get(endpoint + "/history", headers=flow.headers["admin"]).json()
    assert len(history) == 1 and history[0]["actor_id"] == flow.users["admin"]
    second = flow.api.put(
        endpoint,
        headers=flow.headers["admin"],
        json={"expected_version": 1, "rules": policy["rules"]},
    )
    assert second.status_code == 200 and second.json()["version"] == 2


def test_product_snapshots_and_catalog_administration(flow):
    flow.create()
    endpoint = f"/api/v1/credit-products/{flow.product_id}"
    product = flow.api.get(endpoint, headers=flow.headers["client"]).json()
    data = {key: value for key, value in product.items() if key not in {"id", "demonstration_only"}}
    data["annual_rate"] = "25"
    assert flow.api.put(endpoint, headers=flow.headers["officer"], json=data).status_code == 403
    updated = flow.api.put(endpoint, headers=flow.headers["admin"], json=data)
    assert updated.status_code == 200
    approved = flow.approve()
    assert approved["offer"]["annual_rate"] == "18.00"
    flow.create()
    assert flow.get()["product_snapshot"]["annual_rate"] == "25.00"
    data["active"] = False
    assert flow.api.put(endpoint, headers=flow.headers["admin"], json=data).status_code == 200
    flow.upload()
    flow.upload("financial_statements")
    assert flow.action("submit", confirmed=True).status_code == 409
