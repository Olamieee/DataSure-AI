"""Dataset quality trend endpoint."""
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


def test_trend_lists_runs_in_order(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_run(
        client, "t1.csv", "name,age\nA,29\nB,\n"
    )
    _upload_and_run(client, "t2.csv", "name,age\nC,33\nD,44\n")

    resp = client.get(f"/api/v1/datasets/{dataset_id}/trend")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["dataset_id"] == dataset_id
    points = body["points"]
    assert len(points) == 1  # the second run belongs to another dataset
    point = points[0]
    assert point["assessment_id"] > 0
    assert isinstance(point["quality_score"], (int, float))
    assert point["issue_count"] >= 1  # the missing age is flagged


def test_trend_empty_dataset_is_zero_points(logged_in_user):
    client = logged_in_user["client"]
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("a,b\n1,2\n".encode()), "quiet.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    resp = client.get(f"/api/v1/datasets/{dataset_id}/trend")
    assert resp.status_code == 200
    assert resp.get_json()["points"] == []


def test_trend_is_scoped(uploaded_messy_dataset, second_user):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})

    resp = second_user.get(f"/api/v1/datasets/{dataset_id}/trend")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "dataset not found"

    resp = client.get(f"/api/v1/datasets/{dataset_id}/trend")
    assert resp.status_code == 200
    assert len(resp.get_json()["points"]) == 1
