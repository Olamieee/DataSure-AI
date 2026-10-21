"""REST API v1 contract endpoints: list, retrieve and cross-user scoping."""
from __future__ import annotations

import io


def _upload(client, csv: str, name: str = "contract_src.csv") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _make_contract(client, dataset_id: int) -> int:
    """Create a contract via the existing web flow; returns its id."""
    resp = client.post(
        f"/contracts/create/{dataset_id}",
        data={"name": "people schema", "description": "small test contract"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


CONTRACT_CSV = "name,age,city\nA,29,London\nB,39,Paris\n"

CONTRACT_CSV_ALT = "name,age\nC,44\n"


def test_contracts_require_auth(client, app):
    resp = client.get("/api/v1/contracts")
    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_contract_list_starts_empty(logged_in_user):
    resp = logged_in_user["client"].get("/api/v1/contracts")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["contracts"] == []
    assert body["page"] == 1


def test_created_contract_appears_in_api(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    contract_id = _make_contract(client, dataset_id)

    resp = client.get("/api/v1/contracts")
    assert resp.status_code == 200
    contracts = resp.get_json()["contracts"]
    match = [c for c in contracts if c["id"] == contract_id]
    assert len(match) == 1
    entry = match[0]
    assert entry["name"] == "people schema"
    assert entry["column_count"] >= 3  # messy csv has 4 columns


def test_contract_retrieve_includes_contract_json(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    contract_id = _make_contract(client, dataset_id)

    resp = client.get(f"/api/v1/contracts/{contract_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "people schema"
    contract = body["contract"]
    assert contract["allow_extra_columns"] is True
    names = [entry["name"] for entry in contract["columns"]]
    assert names == ["name", "age", "city", "salary"]


def test_unknown_contract_is_404_with_api_error_shape(logged_in_user):
    resp = logged_in_user["client"].get("/api/v1/contracts/99999")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "contract not found"}


def test_contract_scope_isolation(uploaded_messy_dataset, second_user):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    contract_id = _make_contract(client, dataset_id)

    resp = second_user.get(f"/api/v1/contracts/{contract_id}")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "contract not found"}

    listing = second_user.get("/api/v1/contracts")
    assert listing.get_json()["contracts"] == []


def test_contract_validation_passes_for_matching_dataset(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    contract_id = _make_contract(client, dataset_id)

    resp = client.post(
        f"/api/v1/contracts/{contract_id}/validate",
        json={"dataset_id": dataset_id},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["passed"] is True
    assert body["violations"] == []
    assert body["contract_name"] == "people schema"


def test_contract_validation_reports_violations(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    contract_id = _make_contract(client, dataset_id)

    # Misspelled chorus of missing columns plus bad ages: must fail.
    broken = "nm,age,city,salary\nA,not-a-number,X,1\n"
    other_id = _upload(client, broken, "broken.csv")
    resp = client.post(
        f"/api/v1/contracts/{contract_id}/validate",
        json={"dataset_id": other_id},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["passed"] is False
    types = {v["type"] for v in body["violations"]}
    assert "missing_column" in types
    assert "wrong_kind" in types
    # Generated contracts are permissive about extra columns (allow_extra=True).
    assert "extra_column" not in types


def test_contract_validation_updates_dataset_flags(app, uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    contract_id = _make_contract(client, dataset_id)

    client.post(
        f"/api/v1/contracts/{contract_id}/validate",
        json={"dataset_id": dataset_id},
    )
    from datasure.extensions import db
    from datasure.models import Dataset

    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset.contract_id == contract_id
        assert dataset.contract_passed is True


def test_contract_validation_bad_request_shape(logged_in_user, uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    contract_id = _make_contract(client, dataset_id)

    resp = client.post(
        f"/api/v1/contracts/{contract_id}/validate",
        json={"nope": 1},
    )
    assert resp.status_code == 400
    assert "dataset_id" in resp.get_json()["error"]


def test_contract_validation_dataset_must_be_owned(
    uploaded_messy_dataset, second_user
):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    contract_id = _make_contract(client, dataset_id)

    other_id = _upload(second_user, "x,y\n1,2\n", "other_users_file.csv")
    resp = client.post(
        f"/api/v1/contracts/{contract_id}/validate",
        json={"dataset_id": other_id},
    )
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "dataset not found"}
