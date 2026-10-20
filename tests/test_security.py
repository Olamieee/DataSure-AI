"""Security-focused tests: secrets, logs, XSS, path safety, error handling."""
from __future__ import annotations

import io

import pytest


def _csv(content: str = "a,b\n1,2\n"):
    return io.BytesIO(content.encode("utf-8"))


def test_no_secret_key_in_production_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("DATASURE_SECRET_KEY", "")
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path))
    monkeypatch.setenv("DATASURE_CONFIG", "production")
    from datasure import create_app

    with pytest.raises(RuntimeError, match="DATASURE_SECRET_KEY is not set"):
        create_app("production")


def test_passwords_never_stored_in_plain(app, logged_in_user):
    from datasure.models import User, db
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        assert user.password_hash.startswith(("scrypt", "pbkdf2", "argon2"))
        assert "goodpassword1" not in user.password_hash


def test_api_key_not_stored_in_plain(app, logged_in_user):
    from datasure.auth.apikeys import create_key
    from datasure.models import ApiKey, db
    with app.app_context():
        from datasure.models import User
        user = db.session.query(User).filter_by(username="testuser").one()
        _record, raw = create_key(user, "plain check")
        stored = db.session.query(ApiKey).filter_by(user_id=user.id).first()
        assert raw not in str(stored.key_hash)


def test_error_page_does_not_leak_paths(app, client, logged_in_user):
    resp = logged_in_user["client"].get("/datasets/999999")
    assert resp.status_code == 404
    assert b"C:\\Users" not in resp.data
    assert b"Traceback" not in resp.data


def test_storage_filenames_are_server_generated(app, logged_in_user):
    weird_name = '../../../etc/passwd name.csv'
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (_csv("a,b\n1,2\n"), weird_name)},
        content_type="multipart/form-data", follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    from datasure.models import Dataset, db
    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        import re
        assert re.fullmatch(r"[0-9a-f]{32}\.csv", dataset.storage_filename)
        # display name has no path separators or traversal segments
        assert "/" not in dataset.name and ".." not in dataset.name


def test_dashboard_escaping(app, logged_in_user):
    """Dataset display names are escaped; injected HTML cannot execute."""
    payload = "bold<b>name.csv"
    logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (_csv(), payload)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    resp = logged_in_user["client"].get("/dashboard")
    html = resp.data.decode("utf-8")
    assert "<b>" not in html


def test_assessment_endpoint_survives_weird_payload(app, logged_in_user):
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (_csv("a,b\n1,2\n"), "odd.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    resp = logged_in_user["client"].post(
        f"/datasets/{dataset_id}/assess",
        data={"target_column": "a'; DROP TABLE datasets;--", "label": "<b>x"},
        follow_redirects=True,
    )
    assert b"not present" in resp.data
    # DB still intact afterwards
    from datasure.models import Dataset, db
    with app.app_context():
        assert db.session.get(Dataset, dataset_id) is not None


def test_unknown_route_returns_404(client):
    assert client.get("/no/such/page").status_code == 404


def test_sessions_cookie_flags(app, client):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
