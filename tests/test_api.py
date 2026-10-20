"""Tests for the REST API v1: auth, scoping and responses."""
from __future__ import annotations

import io

from datasure.models import User, db


def _get_user_api_key(app):
    with app.app_context():
        from datasure.auth.apikeys import create_key
        from datasure.models import User
        user = db.session.query(User).filter_by(username="testuser").one()
        _record, raw = create_key(user, "test key")
    return raw


def _upload(client):
    csv = ("name,age,score\nA,29,1\nB,39,2\nC,,3\n" * 5)
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), "api_test.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_health_is_public(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_datasets_require_auth(client):
    resp = client.get("/api/v1/datasets")
    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_api_key_auth_allowed(app, client, logged_in_user):
    key = _get_user_api_key(app)
    dataset_id = _upload(logged_in_user["client"])
    resp = client.get("/api/v1/datasets", headers={"X-API-Key": key})
    assert resp.status_code == 200
    items = resp.get_json()["datasets"]
    assert any(d["id"] == dataset_id for d in items)


def test_api_key_rejection(app, client, logged_in_user):
    _upload(logged_in_user["client"])
    resp = client.get("/api/v1/datasets", headers={"X-API-Key": "wrong-key-value"})
    assert resp.status_code == 401


def test_dataset_scope_isolation(app, client, logged_in_user, second_user):
    """User B can never fetch user A's dataset through the API."""
    dataset_id = _upload(logged_in_user["client"])
    resp = second_user.get(f"/api/v1/datasets/{dataset_id}")
    assert resp.status_code == 404


def test_assessment_via_api(app, client, logged_in_user):
    dataset_id = _upload(logged_in_user["client"])
    resp = client.post(
        f"/api/v1/datasets/{dataset_id}/assessments",
        json={"target_column": "score"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert "quality_score" in body and body["quality_score"] is not None
    assert body["scores"]["dimensions"]
    assert isinstance(body["issues"], list)


def test_cleaning_history_endpoint(app, client, logged_in_user):
    dataset_id = _upload(logged_in_user["client"])
    resp = client.get(f"/api/v1/datasets/{dataset_id}/cleaning")
    assert resp.status_code == 200
    assert resp.get_json()["operations"] == []


def test_unknown_dataset_returns_404_json(app, client, logged_in_user):
    resp = client.get("/api/v1/datasets/999")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "dataset not found"


def test_api_preview_limits_rows(app, client, logged_in_user):
    dataset_id = _upload(logged_in_user["client"])
    resp = client.get(f"/api/v1/datasets/{dataset_id}/preview?rows=3")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["rows"]) <= 3
