"""Cleaning-history CSV export (new 'history' kind on web and API)."""
from __future__ import annotations

import io


def _upload(client, name: str = "hist_src.csv") -> int:
    csv = "name,age,city\nA,29,London\nB,,Paris\nA,29,London\n"  # dup + gap
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _apply_cleaning(client, dataset_id: int, operation: str) -> None:
    resp = client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": operation, "expected_version": ""},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def _run_assessment(client, dataset_id: int) -> int:
    resp = client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})
    assert resp.status_code == 201
    return resp.get_json()["id"]


def test_web_history_export(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    _apply_cleaning(client, dataset_id, "drop_duplicate_rows")
    _apply_cleaning(client, dataset_id, "drop_missing_rows")

    resp = client.get(f"/datasets/{dataset_id}/export/history.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    body = resp.data.decode()
    assert body.startswith(
        "when,operation,rows_before,rows_after,columns_before,"
        "columns_after,cells_changed,success\r\n"
    )
    assert "drop_duplicate_rows" in body
    assert "drop_missing_rows" in body
    # oldest first: the dedupe appears before the dropna
    assert (
        body.index("drop_duplicate_rows") < body.index("drop_missing_rows")
    )


def test_web_history_export_empty_redirects_with_notice(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)

    resp = client.get(f"/datasets/{dataset_id}/export/history.csv",
                      follow_redirects=True)
    assert resp.status_code == 200
    assert "No cleaning operations recorded yet" in resp.data.decode(
        "utf-8", errors="replace"
    )


def test_api_history_export(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    _run_assessment(client, dataset_id)
    _apply_cleaning(client, dataset_id, "drop_duplicate_rows")
    assessment_id = _run_assessment(client, dataset_id)

    resp = client.get(f"/api/v1/assessments/{assessment_id}/export/history.csv")
    assert resp.status_code == 200
    disposition = resp.headers["Content-Disposition"]
    assert "_history.csv" in disposition
    body = resp.data.decode()
    assert "drop_duplicate_rows" in body
    assert "yes" in body  # successful operation marker


def test_unknown_kind_still_404(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    resp = client.get(f"/datasets/{dataset_id}/export/silly.csv")
    assert resp.status_code == 404
