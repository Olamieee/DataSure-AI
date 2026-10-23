"""API identity endpoint (GET /api/v1/me)."""
from __future__ import annotations

from datasure.auth.apikeys import create_key
from datasure.extensions import db
from datasure.models import User


def _user(app, username: str = "testuser") -> User:
    with app.app_context():
        return db.session.query(User).filter_by(username=username).one()


def test_me_via_session(logged_in_user, app):
    client = logged_in_user["client"]
    resp = client.get("/api/v1/me")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["username"] == "testuser"
    assert body["auth"] == "session"
    assert "key_last_used" not in body
    assert "created_at" in body
    assert body["datasets"] == 0


def test_me_via_api_key_shows_auth_and_last_used(app, logged_in_user):
    with app.app_context():
        user = _user(app)
        _, raw = create_key(user, "me check")

    fresh = app.test_client()
    resp = fresh.get(
        "/api/v1/me", headers={"X-API-Key": raw}, follow_redirects=False
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["username"] == "testuser"
    assert body["auth"] == "api_key"
    assert body["key_last_used"]  # authenticate_key stamped the usage

    # wrong key cannot see the account
    wrong = app.test_client().get(
        "/api/v1/me", headers={"X-API-Key": "not-a-real-key"}
    )
    assert wrong.status_code == 401


def test_me_requires_authentication(app):
    resp = app.test_client().get("/api/v1/me")
    assert resp.status_code == 401
    assert "authentication required" in resp.get_json()["error"]
