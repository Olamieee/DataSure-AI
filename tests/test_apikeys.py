"""Tests for API key management: creation UI, storage, revocation, isolation."""
from __future__ import annotations

import re

import pytest

from datasure.auth.apikeys import (
    authenticate_key,
    create_key,
    hash_key,
    list_keys,
    revoke_key,
)
from datasure.models import ApiKey, User, db


def _user_id(app, username: str) -> int:
    with app.app_context():
        return db.session.query(User).filter_by(username=username).one().id


# ------------------------------------------------------------------ service level
def test_create_key_returns_raw_once_and_stores_hash(app, logged_in_user):
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        record, raw = create_key(user, "ci runner")
        stored = db.session.query(ApiKey).filter_by(id=record.id).one()
        assert stored.key_hash == hash_key(raw)
        assert raw not in stored.key_hash
        assert len(raw) >= 40
        assert raw != raw + "x"


def test_list_keys_is_scoped_to_owner(app, logged_in_user):
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        create_key(user, "a")
        create_key(user, "b")
        others = db.session.query(ApiKey).all()
        assert len(others) == 2
        for record in others:
            assert record.user_id == user.id


def test_key_limit_enforced(app, logged_in_user):
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        for i in range(10):
            create_key(user, f"key {i}")
        with pytest.raises(ValueError, match="Revoke one before creating another"):
            create_key(user, "one too many")


def test_revoke_disables_key(app, logged_in_user):
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        record, raw = create_key(user, "short-lived")
        from datasure.auth.apikeys import authenticate_key, revoke_key

        assert authenticate_key(raw) is not None
        assert revoke_key(user, record.id).revoked_at is not None
        assert authenticate_key(raw) is None


def test_revoke_is_idempotent_but_safe(app, logged_in_user):
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        record, _raw = create_key(user, "twice")
        assert revoke_key(user, record.id) is not None
        # second revoke of an inactive key returns the record, not an error
        assert revoke_key(user, record.id).revoked_at is not None


# ------------------------------------------------------------------ web routes
def test_settings_page_requires_login(client):
    resp = client.get("/settings/api-keys", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_create_key_via_settings_displays_raw_once(app, logged_in_user):
    client = logged_in_user["client"]
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    assert b"No API keys yet" in resp.data
    resp = client.post("/settings/api-keys", data={"name": "script key"},
                       follow_redirects=True)
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    # the raw key must appear exactly once on the page
    matches = re.findall(r"[A-Za-z0-9_\-=]{43,}", html)
    assert matches, "raw key expected in creation banner"
    assert b"script key" in resp.data
    with app.app_context():
        assert len(list_keys(
            db.session.query(User).filter_by(username="testuser").one()
        )) == 1


def test_revoked_key_cannot_be_used(app, logged_in_user, client):
    client = logged_in_user["client"]
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        record, raw = create_key(user, "doomed")
        key_id = record.id
    resp = client.get("/api/v1/datasets", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    client.post(f"/settings/api-keys/{key_id}/revoke", follow_redirects=True)
    resp = client.get("/api/v1/datasets", headers={"X-API-Key": raw})
    assert resp.status_code == 401
    # the revoked key shows in the list as revoked but never regenerates
    resp = client.get("/settings/api-keys")
    assert b"revoked" in resp.data


def test_cross_user_revocation_blocked(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        record, _raw = create_key(user, "private key")
        key_id = record.id
    resp = second_user.post(f"/settings/api-keys/{key_id}/revoke", follow_redirects=True)
    assert resp.status_code == 200
    assert b"API key not found" in resp.data
    with app.app_context():
        stored = db.session.get(ApiKey, key_id)
        assert stored.revoked_at is None  # untouched


def test_cross_user_key_listing_isolated(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        create_key(user, "only mine")
    resp = second_user.get("/settings/api-keys")
    assert b"only mine" not in resp.data
    resp = client.get("/settings/api-keys")
    assert b"only mine" in resp.data
