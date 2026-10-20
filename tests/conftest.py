"""Shared pytest fixtures for DataSure AI."""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _fresh_login_limiter():
    """Isolate login rate-limit counters between tests."""
    from datasure.auth.ratelimit import login_limiter

    login_limiter.reset_all()
    yield
    login_limiter.reset_all()


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """A fresh application per test with isolated DB and instance dirs."""
    instance_dir = tmp_path / "instance"
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(instance_dir))

    from datasure import create_app
    from datasure.extensions import db

    application = create_app("testing")
    database_file = tmp_path / "test.db"
    application.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database_file}"

    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def logged_in_user(app, client):
    """Register and log in a test user; returns the client and user id."""
    resp = client.post(
        "/register",
        data={
            "username": "testuser",
            "email": "testuser@example.com",
            "password": "goodpassword1",
            "confirm_password": "goodpassword1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    resp = client.post(
        "/login",
        data={"username": "testuser", "password": "goodpassword1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    from datasure.extensions import db
    from datasure.models import User

    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        user_id = user.id
    return {"client": client, "user_id": user_id}


def make_upload_bytes(content: str, filename: str = "dataset.csv") -> tuple:
    return (io.BytesIO(content.encode("utf-8")), filename)


MESSY_CSV = """name,age,city,salary
Alice,29,London,48000
Bob,39,London,52000
Charlie,,Paris,58000
Alice,29,London,48000
Dave,44,U SA,
Eve,33,Lisbon,47000
Frank,50,Paris,61000
Grace,44,Lisbon,55000
"""


@pytest.fixture()
def uploaded_messy_dataset(app, logged_in_user):
    """Upload MESSY_CSV through the real endpoint; returns dataset id."""
    data = {"file": make_upload_bytes(MESSY_CSV, "messy data.csv")}
    resp = logged_in_user["client"].post(
        "/datasets/upload", data=data, content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    return {"dataset_id": dataset_id, **logged_in_user}


@pytest.fixture()
def second_user(app):
    """An independent browser session logged in as a different user."""
    other = app.test_client()
    resp = other.post(
        "/register",
        data={
            "username": "otheruser",
            "email": "other@example.com",
            "password": "otherpassword1",
            "confirm_password": "otherpassword1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.data
    resp = other.post(
        "/login", data={"username": "otheruser", "password": "otherpassword1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return other
