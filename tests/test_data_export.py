"""Per-user data export bundle (GET /settings/export)."""
from __future__ import annotations

import io
import json

from datasure.datasets.ingest import DatasetParseError


def _upload(client, name: str = "export_src.csv",
            csv: str = "name,age\nA,29\nB,\n") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    resp = client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})
    assert resp.status_code == 201
    return dataset_id


def _clean(client, dataset_id: int) -> None:
    resp = client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_missing_rows", "expected_version": ""},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_export_contains_everything_owned(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    _clean(client, dataset_id)

    resp = client.get("/settings/export")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    disposition = resp.headers["Content-Disposition"]
    assert "attachment;" in disposition
    assert "testuser" in disposition

    payload = json.loads(resp.data.decode("utf-8"))
    assert payload["generator"] == "DataSure AI data export"
    assert payload["account"]["username"] == "testuser"

    datasets = payload["datasets"]
    assert len(datasets) == 1
    entry = datasets[0]
    assert entry["id"] == dataset_id
    assert entry["tags"] == []  # untagged here, key still present
    assert len(entry["assessments"]) == 1
    assert isinstance(
        entry["assessments"][0]["quality_score"], (int, float)
    )
    assert any(op["operation"] == "drop_missing_rows"
               for op in entry["cleaning_operations"])
    # content preview parsed from the stored file
    assert entry["preview"]["columns"] == ["name", "age"]

    assert payload["contracts"] == []
    assert payload["rules"] == []
    audit_actions = [e["action"] for e in payload["audit_events"]]
    assert "cleaning_applied" in audit_actions


def test_export_scoped_to_the_owner(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    _upload(client, "mine.csv")

    # another user uploads and cleans their own dataset
    resp = second_user.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("x,y\n1,2\n".encode()), "theirs.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    payload = json.loads(client.get("/settings/export").data.decode("utf-8"))
    names = [d["name"] for d in payload["datasets"]]
    assert names == ["mine.csv"]  # only the owner's data is bundled


def test_export_survives_unreadable_stored_file(app, logged_in_user,
                                                monkeypatch):
    client = logged_in_user["client"]
    dataset_id = _upload(client, "gone.csv")

    import datasure.assessment as assessment_pkg

    def explode(_dataset):
        raise DatasetParseError("stored file missing")

    monkeypatch.setattr(assessment_pkg, "load_dataset_dataframe", explode)
    resp = client.get("/settings/export")
    assert resp.status_code == 200  # export must not fail over one bad file
    payload = json.loads(resp.data.decode("utf-8"))
    entry = payload["datasets"][0]
    assert entry["id"] == dataset_id
    assert "could not be read" in entry["preview"]["error"]


def test_export_button_visible_on_storage_page(logged_in_user):
    client = logged_in_user["client"]
    body = client.get("/settings/storage").data.decode("utf-8", errors="replace")
    assert "/settings/export" in body
    assert "Export all my data" in body
