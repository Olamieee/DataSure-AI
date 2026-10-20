"""Tests for auth flows, dataset ownership and cleaning web endpoints."""
from __future__ import annotations

import io


def _csv_bytes(content: str = "name,age\nA,1\nB,2\n"):
    return io.BytesIO(content.encode("utf-8"))


# ------------------------------------------------------------------ auth flows
def test_register_then_login_flow(client):
    resp = client.post("/register", data={
        "username": "flowuser", "email": "flow@example.com",
        "password": "password123", "confirm_password": "password123",
    }, follow_redirects=False)
    assert resp.status_code == 302
    resp = client.post("/login", data={"username": "flowuser", "password": "password123"},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data


def test_register_rejects_short_password(client):
    resp = client.post("/register", data={
        "username": "shorty", "email": "short@example.com",
        "password": "123", "confirm_password": "123",
    })
    assert resp.status_code == 400
    assert b"at least 8 characters" in resp.data


def test_register_rejects_bad_username(client):
    resp = client.post("/register", data={
        "username": "bad user name!!", "email": "bad@example.com",
        "password": "password123", "confirm_password": "password123",
    })
    assert resp.status_code == 400


def test_register_rejects_duplicate_email(client):
    client.post("/register", data={
        "username": "firstuser", "email": "dup@example.com",
        "password": "password123", "confirm_password": "password123",
    }, follow_redirects=False)
    client.post("/logout")
    resp = client.post("/register", data={
        "username": "seconduser", "email": "dup@example.com",
        "password": "password123", "confirm_password": "password123",
    })
    assert resp.status_code == 400
    assert b"already registered" in resp.data


def test_login_wrong_password_rejected(client):
    client.post("/register", data={
        "username": "pwuser", "email": "pw@example.com",
        "password": "password123", "confirm_password": "password123",
    })
    resp = client.post("/login", data={"username": "pwuser", "password": "wrongpassword"},
                       follow_redirects=False)
    assert resp.status_code == 401


def test_login_open_redirect_blocked(app, client):
    client.post("/register", data={
        "username": "redi", "email": "redi@example.com",
        "password": "password123", "confirm_password": "password123",
    })
    resp = client.get("/login?next=https%3A%2F%2Fevil.example.com")
    resp = client.post("/login?next=https%3A%2F%2Fevil.example.com",
                       data={"username": "redi", "password": "password123"},
                       follow_redirects=False)
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]


# ------------------------------------------------------------------ ownership
def test_cross_user_dataset_access_denied(app, logged_in_user, second_user):
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (_csv_bytes(), "mine.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    assert second_user.get(f"/datasets/{dataset_id}").status_code == 404
    assert second_user.get(f"/datasets/{dataset_id}/download").status_code == 404
    assert second_user.post(f"/datasets/{dataset_id}/assess",
                            data={"label": "hack"}).status_code == 404


# ------------------------------------------------------------------ assess + clean
def test_full_assess_and_clean_cycle(app, logged_in_user):
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (_csv_bytes("name,age,city\nA,29,London\nB,29,London\nC,,Rome\n"),
                       "people.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    resp = logged_in_user["client"].post(
        f"/datasets/{dataset_id}/assess",
        data={"target_column": "age", "label": "first"}, follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/assessments/" in resp.headers["Location"]

    # invalid target is rejected
    resp = logged_in_user["client"].post(
        f"/datasets/{dataset_id}/assess",
        data={"target_column": "not_a_column"}, follow_redirects=True,
    )
    assert b"not present" in resp.data

    # invalid cleaning op name
    resp = logged_in_user["client"].post(
        f"/datasets/{dataset_id}/clean/preview",
        data={"operation": "not_an_operation"}, follow_redirects=True,
    )
    assert b"Unknown cleaning operation" in resp.data


def test_clean_apply_creates_new_version_and_keeps_original(app, logged_in_user, tmp_path):
    csv = "name,age\nA,29\nA,29\nB,30\n"
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (_csv_bytes(csv), "dupes.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    resp = logged_in_user["client"].post(
        f"/datasets/{dataset_id}/clean/preview",
        data={"operation": "drop_duplicate_rows", "param_keep": "first"},
    )
    assert resp.status_code == 200
    assert b"Preview" in resp.data

    resp = logged_in_user["client"].post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_duplicate_rows", "param_keep": "first"},
        follow_redirects=True,
    )
    assert b"applied and recorded" in resp.data

    from datasure.models import Dataset, db
    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset.storage_version == 2
        assert dataset.is_cleaned is True
        operations = dataset.cleaning_operations.all()
        assert len(operations) == 1
        assert operations[0].rows_before == 3
        assert operations[0].rows_after == 2


def test_cleaning_history_page_lists_operations(app, logged_in_user):
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (_csv_bytes(), "hist.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    page = logged_in_user["client"].get(f"/datasets/{dataset_id}/history")
    assert page.status_code == 200
    assert b"No cleaning operations recorded" in page.data


def test_delete_dataset_removes_file_and_record(app, logged_in_user):
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (_csv_bytes(), "doomed.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    from pathlib import Path

    from datasure.models import Dataset, db
    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        storage_name = dataset.storage_filename
        upload_dir = Path(app.instance_path) / "uploads" / f"user_{logged_in_user['user_id']}"
        assert (upload_dir / storage_name).exists()
    resp = logged_in_user["client"].post(
        f"/datasets/{dataset_id}/delete", follow_redirects=True,
    )
    assert b"Dataset deleted" in resp.data
    with app.app_context():
        assert db.session.get(Dataset, dataset_id) is None
    assert not (upload_dir / storage_name).exists()


def test_dashboard_lists_datasets(app, logged_in_user):
    logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (_csv_bytes(), "dash.csv")},
        content_type="multipart/form-data", follow_redirects=True,
    )
    resp = logged_in_user["client"].get("/dashboard")
    assert resp.status_code == 200
    assert b"dash" in resp.data.lower() or b".csv" in resp.data


def test_history_all_page(app, logged_in_user):
    resp = logged_in_user["client"].get("/datasets/history")
    assert resp.status_code == 200
    assert b"Assessment history" in resp.data
