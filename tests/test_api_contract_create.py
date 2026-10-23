"""API contract generation from a dataset (POST /api/v1/datasets/<id>/contract)."""
from __future__ import annotations

import io


def _upload(client, name: str = "contract_src.csv",
            csv: str = "name,age\nA,29\nB,39\n") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_create_contract_defaults_to_dataset_name(app, logged_in_user):
    from datasure.extensions import db
    from datasure.models import SchemaContract

    client = logged_in_user["client"]
    dataset_id = _upload(client)

    resp = client.post(f"/api/v1/datasets/{dataset_id}/contract", json={})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["created"] is True
    summary = body["contract_summary"]
    assert summary["name"] == "contract_src.csv"
    assert summary["column_count"] == 2

    with app.app_context():
        stored = db.session.get(SchemaContract, summary["id"])
        assert stored is not None
        assert stored.user_id == logged_in_user["user_id"]
        assert stored.description.startswith("Generated from")


def test_create_contract_with_custom_name_and_description(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)

    resp = client.post(
        f"/api/v1/datasets/{dataset_id}/contract",
        json={"name": "People snapshot", "description": "Frozen baseline"},
    )
    assert resp.status_code == 201
    summary = resp.get_json()["contract_summary"]
    assert summary["name"] == "People snapshot"

    # the detail shape carries the generated contract columns
    detail = client.get(f"/api/v1/contracts/{summary['id']}").get_json()
    names = [column["name"] for column in detail["contract"]["columns"]]
    assert names == ["name", "age"]


def test_create_contract_rejects_non_object_body(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)

    resp = client.post(f"/api/v1/datasets/{dataset_id}/contract",
                       data="[1,2]", content_type="application/json")
    assert resp.status_code == 400
    assert "JSON object" in resp.get_json()["error"]


def test_create_contract_scoped_to_owner(uploaded_messy_dataset, second_user):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]

    resp = second_user.post(f"/api/v1/datasets/{dataset_id}/contract", json={})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "dataset not found"

    ok = client.post(f"/api/v1/datasets/{dataset_id}/contract", json={})
    assert ok.status_code == 201


def test_create_contract_on_unreadable_dataset(logged_in_user, monkeypatch):
    """A stored file that vanished must 422, not 500."""
    client = logged_in_user["client"]
    dataset_id = _upload(client)

    import datasure.api.routes as api_routes

    def explode(_dataset):
        raise __import__("datasure.datasets.ingest", fromlist=["DatasetParseError"]).__dict__["DatasetParseError"]("file gone")

    monkeypatch.setattr(api_routes, "load_dataset_dataframe", explode)
    resp = client.post(f"/api/v1/datasets/{dataset_id}/contract", json={})
    assert resp.status_code == 422
    assert "file gone" in resp.get_json()["error"]
