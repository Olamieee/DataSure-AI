"""API file download: exact stored bytes with ownership enforcement."""
from __future__ import annotations

import io
from pathlib import Path


def _upload(client, name: str, csv: str) -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


CSV = "name,age,city\nA,29,London\nB,39,Paris\n"


def test_file_download_returns_exact_stored_bytes(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, "bytes test.csv", CSV)

    resp = client.get(f"/api/v1/datasets/{dataset_id}/file")
    assert resp.status_code == 200
    assert resp.data.decode() == CSV
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition and "bytes_test.csv" in disposition


def test_file_download_requires_auth(logged_in_user, app):
    client = logged_in_user["client"]
    dataset_id = _upload(client, "guard.csv", CSV)

    anonymous = app.test_client()
    resp = anonymous.get(f"/api/v1/datasets/{dataset_id}/file")
    assert resp.status_code == 401


def test_file_download_is_scoped(uploaded_messy_dataset, second_user):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]

    resp = second_user.get(f"/api/v1/datasets/{dataset_id}/file")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "dataset not found"

    resp = client.get(f"/api/v1/datasets/{dataset_id}/file")
    assert resp.status_code == 200


def test_file_download_surfaces_missing_storage_file(
    app, uploaded_messy_dataset, monkeypatch
):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]

    resp = client.get(f"/api/v1/datasets/{dataset_id}/file")
    assert resp.status_code == 200

    # Pointer override: make the uploads directory vanish without touching
    # real files (Windows keeps send_file handles open briefly).
    monkeypatch.setattr(
        "datasure.datasets.routes.user_upload_dir",
        lambda instance_path, user_id: (
            Path(instance_path) / "uploads" / f"user_{user_id}" / "gone"
        ),
    )
    resp = client.get(f"/api/v1/datasets/{dataset_id}/file")
    assert resp.status_code == 404
    assert "missing" in resp.get_json()["error"]


def test_file_download_reflects_cleaned_storage(uploaded_messy_dataset):
    """After a cleaning operation, the API serves the cleaned file."""
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]

    original = client.get(f"/api/v1/datasets/{dataset_id}/file")
    assert original.status_code == 200
    original_bytes = original.data

    resp = client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_duplicate_rows", "expected_version": ""},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "applied and recorded" in resp.data.decode(
        "utf-8", errors="replace"
    )

    resp = client.get(f"/api/v1/datasets/{dataset_id}/file")
    assert resp.status_code == 200
    # version churn: the cleaned artefact differs from the original upload
    assert resp.data != original_bytes

    resp = client.get(f"/api/v1/datasets/{dataset_id}/file")
    assert resp.status_code in (200, 404)
