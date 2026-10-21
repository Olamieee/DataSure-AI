"""Tests for the production WSGI entry point."""
from __future__ import annotations

import pytest


@pytest.fixture()
def production_app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATASURE_SECRET_KEY", "wsgi-entry-test-key-not-secret")
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path / "wsgi-instance"))
    import wsgi

    return wsgi.application


def test_wsgi_application_exposes_flask(production_app):
    import flask

    assert isinstance(production_app, flask.Flask)
    assert production_app.config["TESTING"] is False


def test_wsgi_app_refuses_missing_secret_key(monkeypatch):
    """Running the entry point without DATASURE_SECRET_KEY must fail fast."""
    import pathlib
    import runpy

    monkeypatch.delenv("DATASURE_SECRET_KEY", raising=False)
    monkeypatch.delenv("DATASURE_CONFIG", raising=False)
    module_path = pathlib.Path(__file__).resolve().parent.parent / "wsgi.py"
    with pytest.raises(RuntimeError, match="DATASURE_SECRET_KEY"):
        runpy.run_path(str(module_path))


def test_health_endpoint_on_production_app(production_app):
    client = production_app.test_client()
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
