"""Pagination on the contracts and rules management pages."""
from __future__ import annotations


def _many_rules(client, count: int) -> None:
    for i in range(count):
        resp = client.post(
            "/rules/create",
            data={"name": f"rule {i}", "rule_type": "not_null",
                  "column": "age", "severity": "error"},
            follow_redirects=True,
        )
        assert resp.status_code == 200


def _many_contracts(client, dataset_id: int, count: int) -> None:
    for i in range(count):
        resp = client.post(
            f"/contracts/create/{dataset_id}",
            data={"name": f"contract {i}", "description": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 302


def test_rules_page_paginates_past_default_page_size(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    _many_rules(client, 25)

    page1 = client.get("/rules", follow_redirects=True)
    assert page1.status_code == 200
    body1 = page1.data.decode("utf-8", errors="replace")
    assert "rule 24" in body1  # newest first
    assert f"Page 1 of" in body1

    page2 = client.get("/rules?page=2", follow_redirects=True)
    assert page2.status_code == 200
    body2 = page2.data.decode("utf-8", errors="replace")
    assert "rule 0" in body2
    assert "rule 20" not in body2


def test_rules_page_total_reflects_all_rules(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    _many_rules(client, 25)
    resp = client.get("/rules?page=3", follow_redirects=True)
    body = resp.data.decode("utf-8", errors="replace")
    assert "25 saved rule(s)" in body


def test_contracts_page_paginates_past_default_page_size(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    _many_contracts(client, dataset_id, 25)

    page1 = client.get("/contracts", follow_redirects=True)
    assert page1.status_code == 200
    body1 = page1.data.decode("utf-8", errors="replace")
    assert "contract 0" in body1
    assert "Page 1 of" in body1
    assert "25 contracts" in body1


def test_contracts_page_scope_isolation(uploaded_messy_dataset, second_user):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    _many_contracts(client, dataset_id, 3)

    resp = second_user.get("/contracts", follow_redirects=True)
    body = resp.data.decode("utf-8", errors="replace")
    assert "contract 0" not in body
    assert "No contracts yet" in body
