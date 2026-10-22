"""API dataset payloads expose tags."""
from __future__ import annotations

import io


def _upload(client, name: str = "tags_api.csv") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("name,age\nA,29\n".encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _set_tags(client, dataset_id: int, tags: str) -> None:
    resp = client.post(
        f"/datasets/{dataset_id}/tags", data={"tags": tags},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_dataset_retrieve_includes_tags(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    _set_tags(client, dataset_id, "finance, q4")

    resp = client.get(f"/api/v1/datasets/{dataset_id}")
    assert resp.status_code == 200
    assert resp.get_json()["tags"] == ["finance", "q4"]


def test_dataset_list_includes_tags(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    _set_tags(client, dataset_id, "beta")

    resp = client.get("/api/v1/datasets")
    entries = resp.get_json()["datasets"]
    entry = next(item for item in entries if item["id"] == dataset_id)
    assert entry["tags"] == ["beta"]


def test_untyped_datasets_report_empty_tags(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)

    resp = client.get(f"/api/v1/datasets/{dataset_id}")
    assert resp.get_json()["tags"] == []
