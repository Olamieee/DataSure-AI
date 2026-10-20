"""API pagination tests: page metadata, clamping, isolation."""
from __future__ import annotations

import io

from datasure.auth.apikeys import create_key
from datasure.models import User, db


def _api_key(app) -> str:
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        _record, raw = create_key(user, "pagination tests")
    return raw


def _upload_many(client, count: int) -> None:
    for index in range(count):
        resp = client.post(
            "/datasets/upload",
            data={"file": (io.BytesIO(f"a,b\n{index},x\n".encode()), f"api{index}.csv")},
            content_type="multipart/form-data", follow_redirects=False,
        )
        assert resp.status_code == 302


def test_api_list_datasets_paginates(app, logged_in_user):
    key = _api_key(app)
    _upload_many(logged_in_user["client"], 25)
    headers = {"X-API-Key": key}
    first = logged_in_user["client"].get(
        "/api/v1/datasets?per_page=20", headers=headers)
    body = first.get_json()
    assert body["total"] == 25
    assert body["per_page"] == 20
    assert body["page"] == 1
    assert body["next_page"] == 2
    assert len(body["datasets"]) == 20

    second = logged_in_user["client"].get(
        "/api/v1/datasets?page=2&per_page=20", headers={"X-API-Key": key})
    body = second.get_json()
    assert len(body["datasets"]) == 5
    assert body["next_page"] is None


def test_api_page_size_clamped(app, logged_in_user):
    key = _api_key(app)
    _upload_many(logged_in_user["client"], 3)
    resp = logged_in_user["client"].get(
        "/api/v1/datasets?per_page=100000",
        headers={"X-API-Key": key})
    assert resp.get_json()["per_page"] == 100


def test_api_assessments_paginate(app, logged_in_user):
    key = _api_key(app)
    _upload_many(logged_in_user["client"], 1)
    dataset_id = logged_in_user["client"].get(
        "/api/v1/datasets", headers={"X-API-Key": key}).get_json()["datasets"][0]["id"]
    for index in range(23):
        resp = logged_in_user["client"].post(
            f"/api/v1/datasets/{dataset_id}/assessments", json={"label": f"a{index}"},
            headers={"X-API-Key": key})
        assert resp.status_code == 201
    resp = logged_in_user["client"].get(
        f"/api/v1/datasets/{dataset_id}/assessments?per_page=10&page=1",
        headers={"X-API-Key": key})
    body = resp.get_json()
    assert body["total"] == 23 and body["page"] == 1 and body["next_page"] == 2
    assert len(body["assessments"]) == 10
    resp = logged_in_user["client"].get(
        f"/api/v1/datasets/{dataset_id}/assessments?page=3&per_page=10",
        headers={"X-API-Key": key})
    body = resp.get_json()
    assert len(body["assessments"]) == 3 and body["next_page"] is None


def test_api_cleaning_history_paginates(app, logged_in_user):
    key = _api_key(app)
    client = logged_in_user["client"]
    _upload_many(client, 1)
    dataset_id = client.get(
        "/api/v1/datasets", headers={"X-API-Key": key}).get_json()["datasets"][0]["id"]
    for _ in range(12):
        resp = client.post(
            f"/datasets/{dataset_id}/clean/apply",
            data={"operation": "drop_duplicate_rows", "param_keep": "first"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
    body = client.get(
        f"/api/v1/datasets/{dataset_id}/cleaning?per_page=5&page=1",
        headers={"X-API-Key": key}).get_json()
    assert body["total"] == 12 and len(body["operations"]) == 5
    assert body["next_page"] == 2
