"""Tests for the unauthenticated /healthz endpoint."""
from __future__ import annotations

import types

import pytest
from sqlalchemy.exc import SQLAlchemyError


def test_healthz_reports_ok_with_database_check(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.content_type == "application/json"
    body = resp.get_json()
    assert body["status"] == "ok"
    database = body["checks"]["database"]
    assert database["status"] == "ok"
    assert database["latency_ms"] >= 0.0


def test_healthz_does_not_require_login(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_healthz_reports_degraded_when_database_unreachable(client, monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise SQLAlchemyError("engine intentionally broken for test")

    broken_db = types.SimpleNamespace(engine=BrokenEngine())
    monkeypatch.setattr("datasure.main.routes.db", broken_db)

    resp = client.get("/healthz")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["status"] == "error"
    # error field names the exception type only; never its message internals
    assert body["checks"]["database"]["error"] == "SQLAlchemyError"


def test_healthz_reports_degraded_for_any_engine_failure(client, monkeypatch):
    class WeirdEngine:
        def connect(self):
            raise RuntimeError("misconfigured driver")

    broken_db = types.SimpleNamespace(engine=WeirdEngine())
    monkeypatch.setattr("datasure.main.routes.db", broken_db)

    resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.get_json()["checks"]["database"]["error"] == "RuntimeError"
