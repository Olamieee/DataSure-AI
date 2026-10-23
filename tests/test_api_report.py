"""API assessment report download (GET /api/v1/assessments/<id>/report)."""
from __future__ import annotations

import io
import json


def _upload_and_run(client, name: str, csv: str) -> tuple[int, int]:
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
    return dataset_id, resp.get_json()["id"]


def test_report_returns_full_json_payload(logged_in_user):
    client = logged_in_user["client"]
    dataset_id, assessment_id = _upload_and_run(
        client, "report.csv", "name,age\nA,29\nB,\n"
    )

    resp = client.get(f"/api/v1/assessments/{assessment_id}/report")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    disposition = resp.headers["Content-Disposition"]
    assert "attachment;" in disposition
    assert f"report_dataset{dataset_id}_assessment{assessment_id}" in disposition

    payload = json.loads(resp.data.decode())
    assert payload["generator"] == "DataSure AI"
    assert payload["dataset"]["id"] == dataset_id
    assert payload["assessment"]["id"] == assessment_id
    assert isinstance(payload["assessment"]["quality_score"], (int, float))
    assert isinstance(payload["assessment"]["issues"], list)


def test_report_is_scoped(logged_in_user, second_user):
    client = logged_in_user["client"]
    _, assessment_id = _upload_and_run(client, "mine.csv", "a,b\n1,2\n")

    resp = second_user.get(f"/api/v1/assessments/{assessment_id}/report")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "assessment not found"


def test_report_unknown_assessment_is_404(logged_in_user):
    client = logged_in_user["client"]
    resp = client.get("/api/v1/assessments/999999/report")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "assessment not found"
