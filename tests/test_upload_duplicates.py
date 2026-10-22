"""Duplicate-upload detection via stored SHA-256 (scoping included)."""
from __future__ import annotations

import io


def _upload(client, content: str, name: str = "dup_test.csv"):
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(content.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200, resp.data
    return resp


CSV = "name,age,city\nA,29,London\nB,39,Paris\n"


def test_identical_upload_warns_about_previous_copy(logged_in_user):
    client = logged_in_user["client"]
    _upload(client, CSV, "first copy.csv")
    resp = _upload(client, CSV, "second copy.csv")  # identical bytes
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert "identical file content" in body
    assert "first copy.csv" in body
    assert "dataset #1" in body


def test_distinct_upload_does_not_warn(logged_in_user):
    client = logged_in_user["client"]
    _upload(client, CSV, "one.csv")
    resp = _upload(client, CSV + "C,51,Rome\n", "two.csv")
    body = resp.data.decode("utf-8", errors="replace")
    assert "identical file content" not in body


def test_other_users_duplicates_do_not_trigger_warning(
    logged_in_user, second_user
):
    _upload(logged_in_user["client"], CSV, "user_a.csv")
    resp = _upload(second_user, CSV, "user_b.csv")  # same bytes, other user
    body = resp.data.decode("utf-8", errors="replace")
    assert "identical file content" not in body


def test_duplicate_still_uploaded_and_usable(app, logged_in_user):
    client = logged_in_user["client"]
    _upload(client, CSV)
    _upload(client, CSV, "again.csv")

    from datasure.extensions import db
    from datasure.models import Dataset

    with app.app_context():
        count = (
            db.session.query(Dataset)
            .filter_by(user_id=logged_in_user["user_id"])
            .count()
        )
        assert count == 2  # the duplicate is stored, not blocked
