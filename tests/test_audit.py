"""Tests for the audit trail: recording, constraints, display, isolation."""
from __future__ import annotations

import io

import pytest

from datasure.audit import ALLOWED_ACTIONS, record_audit
from datasure.models import AuditEvent, User, db


def _upload_and_clean(client):
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2\n2,3\n"), "audit.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_duplicate_rows", "param_keep": "first"},
        follow_redirects=False,
    )
    return dataset_id


def test_cleaning_apply_recorded_with_request_id(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_clean(client)
    with app.app_context():
        events = db.session.query(AuditEvent).filter_by(
            dataset_id=dataset_id, action="cleaning_applied").all()
        assert len(events) == 1
        assert events[0].detail_json["operation"] == "drop_duplicate_rows"
        assert events[0].detail_json.get("version")
        # correlation id present when the action ran inside a request
        non_empty_csrf_note = None
        assert events[0].request_id, "expected a request id on in-request actions"


def test_api_key_actions_recorded_without_key_material(app, logged_in_user):
    client = logged_in_user["client"]
    resp = client.get("/settings/api-keys")
    own_user_id = None
    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        own_user_id = user.id
    # create via settings form
    client.post("/settings/api-keys", data={"name": "audit key"},
                follow_redirects=True)
    with app.app_context():
        created = db.session.query(AuditEvent).filter_by(
            user_id=own_user_id, action="api_key_created").all()
        assert len(created) == 1
        assert created[0].detail_json["name"] == "audit key"
        stored_json = str(created[0].detail_json).lower()
        assert "ey_" not in stored_json and "hash" not in stored_json


def test_dataset_deletion_recorded_before_relationships_removed(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_clean(client)
    client.post(f"/datasets/{dataset_id}/delete", follow_redirects=True)
    with app.app_context():
        deleted = db.session.query(AuditEvent).filter_by(
            action="dataset_deleted").all()
        assert len(deleted) == 1
        assert deleted[0].detail_json.get("name")


def test_record_audit_rejects_unknown_actions(app):
    assert "raw_sql" not in ALLOWED_ACTIONS
    with app.app_context():
        with pytest.raises(ValueError):
            record_audit("fabricated_action", 1)


def test_dataset_audit_events_are_owner_scoped(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_clean(client)
    resp = second_user.get(f"/datasets/{dataset_id}/history",
                           follow_redirects=False)
    assert resp.status_code == 404
    # the owner sees the trail
    resp = client.get(f"/datasets/{dataset_id}/history")
    assert b"Audit trail" in resp.data
    assert b"cleaning_applied" in resp.data
