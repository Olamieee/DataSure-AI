"""API dataset deletion (DELETE /api/v1/datasets/<id>)."""
from __future__ import annotations

import io


def _upload(client, name: str = "api_del.csv", csv: str = "a,b\n1,2\n") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_delete_removes_row_file_and_records_audit(app, logged_in_user):
    from datasure.extensions import db
    from datasure.models import AuditEvent, Dataset

    client = logged_in_user["client"]
    dataset_id = _upload(client)

    resp = client.delete(f"/api/v1/datasets/{dataset_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["deleted"] is True
    assert body["dataset"]["id"] == dataset_id
    assert body["dataset"]["name"] == "api_del.csv"
    assert body["dataset"]["file_removed"]  # storage filename exposed

    with app.app_context():
        assert db.session.get(Dataset, dataset_id) is None
        events = AuditEvent.query.filter_by(action="dataset_deleted").all()
        assert len(events) == 1
        assert events[0].dataset_id == dataset_id

    # the deleted dataset is gone for API consumers too
    assert client.get(f"/api/v1/datasets/{dataset_id}").status_code == 404


def test_delete_is_scoped_to_the_owner(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)

    resp = second_user.delete(f"/api/v1/datasets/{dataset_id}")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "dataset not found"

    # row still present for the owner
    assert client.get(f"/api/v1/datasets/{dataset_id}").status_code == 200


def test_delete_requires_authentication(app):
    client = app.test_client()
    resp = client.delete("/api/v1/datasets/1")
    assert resp.status_code == 401
    assert "authentication required" in resp.get_json()["error"]


def test_web_delete_still_works(app, logged_in_user):
    from datasure.extensions import db
    from datasure.models import Dataset

    client = logged_in_user["client"]
    dataset_id = _upload(client)

    resp = client.post(f"/datasets/{dataset_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Dataset, dataset_id) is None
