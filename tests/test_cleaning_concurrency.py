"""Optimistic-concurrency tests for cleaning apply (version guard)."""
from __future__ import annotations

import io

from datasure.models import Dataset, db


def _upload(client) -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2\n1,2\n3,4\n"), "race.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _version(app, dataset_id: int) -> int:
    with app.app_context():
        return db.session.get(Dataset, dataset_id).storage_version


def test_apply_with_matching_version_succeeds(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    version = _version(app, dataset_id)
    resp = client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_duplicate_rows", "param_keep": "first",
              "expected_version": str(version)},
        follow_redirects=True,
    )
    assert b"applied and recorded" in resp.data
    assert _version(app, dataset_id) == version + 1


def test_apply_rejected_when_version_changed(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    # user previews on version 1; meanwhile another action bumps the dataset
    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        dataset.storage_version += 1
        db.session.commit()
    stuck_version = _version(app, dataset_id) - 1
    resp = client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_duplicate_rows", "param_keep": "first",
              "expected_version": str(stuck_version)},
        follow_redirects=True,
    )
    assert b"changed since this preview" in resp.data
    assert _version(app, dataset_id) == stuck_version + 1  # no extra bump
    with app.app_context():
        from datasure.models import CleaningOperation

        assert db.session.query(CleaningOperation).filter_by(
            dataset_id=dataset_id).count() == 0


def test_apply_without_expected_version_still_works(app, logged_in_user):
    """Backwards compatibility: API-style callers may omit the field."""
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    resp = client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_duplicate_rows", "param_keep": "first"},
        follow_redirects=True,
    )
    assert b"applied and recorded" in resp.data


def test_invalid_version_value_is_rejected_cleanly(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    resp = client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_duplicate_rows", "param_keep": "first",
              "expected_version": "not-a-number"},
        follow_redirects=True,
    )
    assert b"Invalid version reference" in resp.data
    assert _version(app, dataset_id) == 1
