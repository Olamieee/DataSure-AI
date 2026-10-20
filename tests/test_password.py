"""Tests for password change and session hardening configuration."""
from __future__ import annotations


def test_change_password_requires_login(client):
    resp = client.get("/change-password", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def _register_and_login(client, password="original-passphrase"):
    client.post("/register", data={
        "username": "passuser", "email": "pass@example.com",
        "password": password, "confirm_password": password,
    })
    client.post("/login", data={"username": "passuser", "password": password},
                follow_redirects=True)


def test_change_password_flow(app, client):
    _register_and_login(client)
    resp = client.post("/change-password", data={
        "current_password": "original-passphrase",
        "new_password": "brand-new-passphrase",
        "confirm_password": "brand-new-passphrase",
    }, follow_redirects=True)
    assert b"Password changed" in resp.data
    # old password no longer valid
    client.post("/logout", follow_redirects=True)
    resp = client.post("/login", data={"username": "passuser",
                                       "password": "original-passphrase"})
    assert resp.status_code == 401
    resp = client.post("/login", data={"username": "passuser",
                                       "password": "brand-new-passphrase"},
                       follow_redirects=True)
    assert resp.status_code == 200


def test_change_password_requires_correct_current(client):
    _register_and_login(client)
    resp = client.post("/change-password", data={
        "current_password": "wrong-current",
        "new_password": "brand-new-passphrase",
        "confirm_password": "brand-new-passphrase",
    })
    assert resp.status_code == 400
    assert b"current password is incorrect" in resp.data


def test_change_password_rejects_short_or_repeated(client):
    _register_and_login(client)
    resp = client.post("/change-password", data={
        "current_password": "original-passphrase",
        "new_password": "short",
        "confirm_password": "short",
    })
    assert resp.status_code == 400
    assert b"at least 8 characters" in resp.data
    resp = client.post("/change-password", data={
        "current_password": "original-passphrase",
        "new_password": "original-passphrase",
        "confirm_password": "original-passphrase",
    })
    assert b"must be different" in resp.data


def test_wrong_confirmation_rejected(client):
    _register_and_login(client)
    resp = client.post("/change-password", data={
        "current_password": "original-passphrase",
        "new_password": "brand-new-passphrase",
        "confirm_password": "mismatched",
    })
    assert b"do not match" in resp.data


def test_security_headers_applied(app, client):
    resp = client.get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "same-origin"


def test_production_config_secure_cookies_and_refresh():
    from datasure.config import ProductionConfig

    assert ProductionConfig.SESSION_COOKIE_SECURE is True
    assert ProductionConfig.SESSION_REFRESH_EACH_REQUEST is True
    assert ProductionConfig.PERMANENT_SESSION_LIFETIME <= 60 * 60 * 12


def test_testing_config_not_secure_cookies():
    from datasure.config import TestingConfig

    assert not getattr(TestingConfig, "SESSION_COOKIE_SECURE", False)
