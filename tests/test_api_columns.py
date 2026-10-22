"""API column dictionary endpoint (latest-assessment profile)."""
from __future__ import annotations

import io


def _upload_and_run(client, name: str = "cols.csv") -> int:
    csv = "name,age,city,salary\nA,29,London,48000\nB,,Paris,52000\n"
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


def test_columns_lists_profile_metadata(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_run(client)

    resp = client.get(f"/api/v1/datasets/{dataset_id}/columns")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["dataset_id"] == dataset_id
    assert body["row_count"] == 2
    assert body["column_count"] == 4
    names = [column["name"] for column in body["columns"]]
    assert names == ["name", "age", "city", "salary"]
    age = next(column for column in body["columns"] if column["name"] == "age")
    assert age["kind"] == "numeric"
    assert age["missing"] == 1  # row B has no age value


def test_columns_without_assessment_is_404(logged_in_user):
    client = logged_in_user["client"]
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("a,b\n1,2\n".encode()), "fresh.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    resp = client.get(f"/api/v1/datasets/{dataset_id}/columns")
    assert resp.status_code == 404
    assert "no assessment" in resp.get_json()["error"]


def test_columns_is_scoped(uploaded_messy_dataset, second_user):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]

    resp = second_user.get(f"/api/v1/datasets/{dataset_id}/columns")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "dataset not found"

    resp = client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})
    assert resp.status_code == 201, resp.data
    resp = client.get(f"/api/v1/datasets/{dataset_id}/columns")
    assert resp.status_code == 200
