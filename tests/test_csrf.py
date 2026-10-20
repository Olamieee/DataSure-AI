"""CSRF protection tests for all browser state-changing flows.

The default test config disables CSRF so feature tests stay focused; these
tests re-enable it per test and exercise missing/invalid/valid tokens, plus
the API exemption for programmatic clients.
"""
from __future__ import annotations

import io
import re

import pytest

TOKEN_PATTERN = re.compile(
    rb'name="csrf_token"[^>]*value="([^"]+)"', re.DOTALL
)


@pytest.fixture()
def csrf_app(app):
    app.config["WTF_CSRF_ENABLED"] = True
    return app


@pytest.fixture()
def csrf_client(csrf_app, client):
    """Client registered and logged in via their forms, with CSRF re-enabled."""
    token = _extract_token(client.get("/register").data)
    resp = client.post("/register", data={
        "username": "csrfuser", "email": "csrf@example.com",
        "password": "password123", "confirm_password": "password123",
        "csrf_token": token,
    }, follow_redirects=False)
    assert resp.status_code == 302
    token = _extract_token(client.get("/login").data)
    resp = client.post("/login", data={
        "username": "csrfuser", "password": "password123", "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    return client


def _form_token(client, path: str) -> str:
    return _extract_token(client.get(path).data)


def _extract_token(page_bytes: bytes) -> str:
    match = TOKEN_PATTERN.search(page_bytes)
    assert match, "no CSRF token found in page"
    return match.group(1).decode()


def test_form_pages_render_csrf_token(csrf_app):
    anon = csrf_app.test_client()
    for path in ("/login", "/register"):
        resp = anon.get(path)
        assert resp.status_code == 200
        assert TOKEN_PATTERN.search(resp.data), f"missing token on {path}"


def test_logged_in_pages_render_csrf_token(csrf_client):
    for path in ("/datasets/upload", "/dashboard"):
        resp = csrf_client.get(path)
        assert resp.status_code in (200, 302)
        assert TOKEN_PATTERN.search(resp.data) or resp.status_code == 302


def test_post_without_token_rejected(csrf_client):
    resp = csrf_client.post("/login", data={
        "username": "csrfuser", "password": "password123",
    })
    assert resp.status_code == 400
    assert b"csrf" in resp.data.lower() or b"csrf_token" in resp.data


def test_post_with_wrong_token_rejected(csrf_client):
    resp = csrf_client.post("/login", data={
        "username": "csrfuser", "password": "password123",
        "csrf_token": "definitely-wrong-token",
    })
    assert resp.status_code == 400


def test_registration_requires_token(csrf_client):
    resp = csrf_client.post("/register", data={
        "username": "victim", "email": "victim@example.com",
        "password": "password123", "confirm_password": "password123",
    })
    assert resp.status_code == 400


def test_dataset_actions_require_token(csrf_client, csrf_app):
    resp = csrf_client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2\n"), "x.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_cleaning_apply_requires_token(csrf_client, csrf_app):
    # upload with correct token
    resp = csrf_client.get("/datasets/upload")
    token = _extract_token(resp.data)
    resp = csrf_client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2\n3,4\n"), "x.csv"),
              "csrf_token": token},
        content_type="multipart/form-data", follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    # apply without token -> rejected
    resp = csrf_client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_duplicate_rows", "param_keep": "first"},
    )
    assert resp.status_code == 400


def test_logout_requires_token(csrf_client):
    resp = csrf_client.post("/logout")
    assert resp.status_code == 400


def test_api_requests_are_exempt_from_csrf(csrf_app, csrf_client):
    """Programmatic API clients must not be blocked by browser form tokens."""
    csrf_client.get("/datasets/upload")
    token = _extract_token(csrf_client.get("/datasets/upload").data)
    resp = csrf_client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2\n"), "x.csv"), "csrf_token": token},
        content_type="multipart/form-data", follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    with csrf_app.app_context():
        from datasure.auth.apikeys import create_key
        from datasure.extensions import db
        from datasure.models import User
        user = db.session.query(User).filter_by(username="csrfuser").one()
        _record, key = create_key(user, "csrf exemption test")

    resp = csrf_client.post(
        f"/api/v1/datasets/{dataset_id}/assessments",
        json={"target_column": None},          # no csrf_token anywhere
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 201
