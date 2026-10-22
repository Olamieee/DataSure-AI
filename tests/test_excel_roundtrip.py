"""Round-trip ingest through the real file types: .xlsx and .tsv."""
from __future__ import annotations

import io

import pandas as pd


def _upload_bytes(client, name: str, payload: bytes) -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(payload), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _assess(client, dataset_id: int) -> float:
    resp = client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})
    assert resp.status_code == 201, resp.data
    return resp.get_json()["quality_score"]


def test_xlsx_upload_assess_and_download_roundtrip(logged_in_user):
    client = logged_in_user["client"]

    frame = pd.DataFrame({
        "name": ["A", "B", "C"],
        "age": [29, 39, 44],
        "city": ["London", "Paris", "Lisbon"],
    })
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="data")
    payload = buffer.getvalue()

    dataset_id = _upload_bytes(client, "roundtrip.xlsx", payload)
    score = _assess(client, dataset_id)
    assert 0.0 <= score <= 100.0

    detail = client.get(f"/datasets/{dataset_id}")
    body = detail.data.decode("utf-8", errors="replace")
    assert "3 rows × 3 columns" in body

    downloaded = client.get(f"/api/v1/datasets/{dataset_id}/file")
    assert downloaded.status_code == 200
    again = pd.read_excel(io.BytesIO(downloaded.data), engine="openpyxl")
    assert list(again.columns) == ["name", "age", "city"]
    assert len(again) == 3


def test_tsv_upload_roundtrip(logged_in_user):
    client = logged_in_user["client"]
    payload = "name\tage\tcity\nA\t29\tLondon\nB\t39\tParis\n".encode()

    dataset_id = _upload_bytes(client, "roundtrip.tsv", payload)
    _assess(client, dataset_id)

    downloaded = client.get(f"/api/v1/datasets/{dataset_id}/file")
    assert downloaded.status_code == 200
    body = downloaded.data.decode()
    assert body.startswith("# dataset") or "name\tage\tcity" in body


def test_multi_sheet_xlsx_reads_first_sheet(logged_in_user):
    client = logged_in_user["client"]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_excel(
            writer, index=False, sheet_name="first"
        )
        pd.DataFrame({"c": [99], "d": [88]}).to_excel(
            writer, index=False, sheet_name="second"
        )
    dataset_id = _upload_bytes(client, "multi.xlsx", buffer.getvalue())

    _assess(client, dataset_id)
    resp = client.get(f"/api/v1/datasets/{dataset_id}/columns")
    assert resp.status_code == 200
    names = [column["name"] for column in resp.get_json()["columns"]]
    assert names == ["a", "b"]  # only the first sheet is ingested
