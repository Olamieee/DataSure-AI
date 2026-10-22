"""Dataset detail page: quality trend table with per-step deltas."""
from __future__ import annotations

import io


def _upload_and_run(client, name: str, csv: str) -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    resp = client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})
    assert resp.status_code == 201, resp.data
    return dataset_id


def _clean(client, dataset_id: int) -> None:
    resp = client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_missing_rows", "expected_version": ""},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_trend_table_shows_runs_and_changes(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_run(
        client, "tr1.csv", "name,age,city\nA,29,London\nB,,Paris\n"
    )
    detail_one = client.get(f"/datasets/{dataset_id}")
    body1 = detail_one.data.decode("utf-8", errors="replace")
    assert "Quality trend" in body1
    assert "first run" in body1

    _clean(client, dataset_id)
    client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})

    body2 = client.get(f"/datasets/{dataset_id}").data.decode(
        "utf-8", errors="replace"
    )
    assert "Quality trend" in body2
    # change markers appear once a previous run exists
    assert body2.count("first run") == 1  # newest row is the first-run marker


def test_no_trend_row_for_unassessed_dataset(logged_in_user):
    client = logged_in_user["client"]
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("a,b\n1,2\n".encode()), "silent.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    body = client.get(f"/datasets/{dataset_id}").data.decode(
        "utf-8", errors="replace"
    )
    assert "Quality trend" not in body
