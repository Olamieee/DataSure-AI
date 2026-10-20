"""Tests for login rate limiting."""
from __future__ import annotations

import pytest

from datasure.auth import ratelimit
from datasure.auth.ratelimit import SlidingWindowLimiter


@pytest.fixture(autouse=True)
def clean_limiter():
    ratelimit.login_limiter = SlidingWindowLimiter(3, 600, 900)
    yield


def _fail_n(client, username: str, count: int, password: str = "wrong-password"):
    for _ in range(count):
        resp = client.post("/login", data={"username": username,
                                           "password": password})
        assert resp.status_code == 401


def test_failures_block_further_attempts(client):
    _fail_n(client, "victim", 3)
    resp = client.post("/login", data={"username": "victim",
                                       "password": "any"})
    assert resp.status_code == 429
    assert b"temporarily locked" in resp.data


def test_limiter_records_both_user_and_ip_keys(client):
    _fail_n(client, "someuser", 2)      # 2 failures -> user+ip keys each have 2
    ratelimit.login_limiter.record_failure("user:other")
    assert len(ratelimit.login_limiter._attempts) >= 3  # user key, ip key, other


def test_correct_credentials_after_block_still_blocked(client):
    # register a real user, then fail 3 times on their name
    client.post("/register", data={
        "username": "realuser", "email": "real@example.com",
        "password": "correct-horse", "confirm_password": "correct-horse",
    })
    _fail_n(client, "realuser", 3)
    resp = client.post("/login", data={"username": "realuser",
                                       "password": "correct-horse"})
    assert resp.status_code == 429


def test_successful_login_resets_counter(app, client):
    client.post("/register", data={
        "username": "resetuser", "email": "reset@example.com",
        "password": "another-passphrase", "confirm_password": "another-passphrase",
    })
    _fail_n(client, "resetuser", 2, password="wrong")
    resp = client.post("/login", data={"username": "resetuser",
                                       "password": "another-passphrase"})
    assert resp.status_code == 302
    assert ratelimit.login_limiter.is_blocked("user:resetuser") == (False, 0)
    assert ratelimit.login_limiter.is_blocked(
        ratelimit.address_key("127.0.0.1")) == (False, 0)


def test_window_expiry_clears_block():
    limiter = SlidingWindowLimiter(max_attempts=1, window_seconds=600,
                                   block_seconds=100)
    limiter.record_failure("u", now=1000.0)
    blocked, remaining = limiter.is_blocked("u", now=1050.0)
    assert blocked and 45 <= remaining <= 60
    blocked, _ = limiter.is_blocked("u", now=1101.0)
    assert not blocked


def test_rate_limiting_keeps_username_private_in_logs(app, client, caplog):
    import logging
    _fail_n(client, "someuser", 3)
    with caplog.at_level(logging.WARNING, logger="datasure"):
        client.post("/login", data={"username": "someuser", "password": "x"})
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "someuser***" in log_text or "user:***" in log_text
    assert "blocked" in log_text.lower()
