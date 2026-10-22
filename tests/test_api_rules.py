"""REST API v1 rule endpoints: list, create, and run (with scoping)."""
from __future__ import annotations

import io


def _upload(client, csv: str, name: str = "rules_api.csv") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


CSV = "name,age,city\nA,29,London\nB,39,Paris\n"


def _create_rule(client, name: str = "age bounds", rule: dict | None = None,
                 rule_type: str = "numeric_range") -> dict:
    payload = {
        "name": name,
        "rule_type": rule_type,
        "rule": rule or {"column": "age", "min": 0, "max": 130},
    }
    resp = client.post("/api/v1/rules", json=payload)
    assert resp.status_code == 201, resp.data
    return resp.get_json()


def test_rules_list_requires_auth(client):
    resp = client.get("/api/v1/rules")
    assert resp.status_code == 401


def test_create_rule_normalises_and_stores(logged_in_user):
    body = _create_rule(logged_in_user["client"])
    assert body["name"] == "age bounds"
    assert body["rule_type"] == "numeric_range"
    assert body["rule"]["min"] == 0 and body["rule"]["max"] == 130
    assert body["id"] > 0

    listing = logged_in_user["client"].get("/api/v1/rules").get_json()
    assert listing["total"] == 1
    assert listing["rules"][0]["id"] == body["id"]


def test_create_rule_rejects_malformed_definition(logged_in_user):
    client = logged_in_user["client"]
    resp = client.post(
        "/api/v1/rules",
        json={
            "name": "evil rule",
            "rule_type": "column_comparison",
            "rule": {"left": "a", "right": "b", "operator": "__import__"},
        },
    )
    assert resp.status_code == 422
    body = resp.get_json()
    assert "operator" in body["error"]
    # free-form expressions are never permitted
    listing = client.get("/api/v1/rules").get_json()
    assert listing["total"] == 0


def test_create_rule_requires_name_and_rule_object(logged_in_user):
    client = logged_in_user["client"]
    resp = client.post("/api/v1/rules", json={"rule_type": "unique", "rule": {}})
    assert resp.status_code == 400
    assert "name" in resp.get_json()["error"]

    resp = client.post(
        "/api/v1/rules",
        json={"name": "x", "rule_type": "unique", "rule": "not-a-dict"},
    )
    assert resp.status_code == 400
    assert "'rule'" in resp.get_json()["error"]


def test_run_rules_reports_pass_and_fail(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    good = _create_rule(client)["id"]
    strict = _create_rule(
        client, name="strict ages", rule={"column": "age", "min": 100, "max": 200}
    )["id"]

    resp = client.post(
        f"/api/v1/datasets/{dataset_id}/rules/run",
        json={"rule_ids": [good, strict]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["passed"] == 1 and body["failed"] == 1
    by_id = {r["id"]: r for r in body["results"]}
    assert by_id[good]["passed"] is True
    assert by_id[strict]["passed"] is False
    assert "outside the accepted range" in by_id[strict]["message"]


def test_run_rules_unknown_rule_is_404(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    resp = client.post(
        f"/api/v1/datasets/{dataset_id}/rules/run",
        json={"rule_ids": [987654]},
    )
    assert resp.status_code == 404
    assert "rules" in resp.get_json()["error"]


def test_run_rules_bad_body_is_400(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    resp = client.post(f"/api/v1/datasets/{dataset_id}/rules/run", json={})
    assert resp.status_code == 400
    assert "rule_ids" in resp.get_json()["error"]


def test_rules_scoping_between_users(uploaded_messy_dataset, second_user):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    rule_id = _create_rule(client)["id"]

    # Rule invisible in the other user's listing.
    listing = second_user.get("/api/v1/rules").get_json()
    assert listing["total"] == 0

    # And unusable against the other user's own dataset.
    other_id = _upload(second_user, "age\n1\n2\n", "mine.csv")
    resp = second_user.post(
        f"/api/v1/datasets/{other_id}/rules/run",
        json={"rule_ids": [rule_id]},
    )
    assert resp.status_code == 404

    # Owner cannot run another user's rule against a shared-looking id either.
    resp = client.post(
        f"/api/v1/datasets/{dataset_id}/rules/run",
        json={"rule_ids": [rule_id]},
    )
    assert resp.status_code == 200  # own rule, own dataset: fine