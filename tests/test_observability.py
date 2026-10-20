"""Observability tests: correlation IDs, error pages, no secrets in logs."""
from __future__ import annotations

import logging


def test_response_carries_request_id(app, client):
    resp = client.get("/login")
    request_id = resp.headers.get("X-Request-ID")
    assert request_id and 8 <= len(request_id) <= 32


def test_each_request_gets_a_fresh_request_id(app, client):
    first = client.get("/login").headers["X-Request-ID"]
    second = client.get("/login").headers["X-Request-ID"]
    assert first != second  # one correlation id per request, not per session


def test_log_records_include_request_id(app, client, caplog):
    with caplog.at_level(logging.INFO, logger="datasure"):
        client.get("/login")
        app.logger.info("probe message")
    record = next(r for r in caplog.records if r.getMessage() == "probe message")
    assert getattr(record, "request_id", None) is not None


def test_error_response_includes_request_id(app, client):
    @app.route("/boom")
    def boom():
        raise RuntimeError("boom")

    app.config["PROPAGATE_EXCEPTIONS"] = False
    resp = client.get("/boom")
    assert resp.status_code == 500
    body = resp.data.decode("utf-8")
    assert resp.headers["X-Request-ID"]
    # HTML error page shows the same id the response header carries
    assert resp.headers["X-Request-ID"] in body


def test_passwords_never_logged(app, client, caplog):
    with caplog.at_level(logging.INFO):
        client.post("/register", data={
            "username": "leakme", "email": "leak@example.com",
            "password": "SuperSecret99", "confirm_password": "SuperSecret99",
        })
    text = "\n".join(str(r.getMessage()) + str(r.__dict__.get("args", ""))
                     for r in caplog.records)
    assert "SuperSecret99" not in text
