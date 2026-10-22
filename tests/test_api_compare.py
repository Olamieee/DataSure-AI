"""REST API assessment comparison endpoint."""
from __future__ import annotations

import io


def _upload_and_run(client, csv_name: str = "cmp-base.csv", csv: str | None = None):
    csv = csv or "name,age,city,salary\nA,29,London,48000\nB,,Paris,\n"
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), csv_name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    resp = client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})
    assert resp.status_code == 201, resp.data
    return resp.get_json()["id"]


def test_compare_reports_no_change_between_identical_runs(logged_in_user):
    client = logged_in_user["client"]
    first = _upload_and_run(client, csv_name="cmp-base.csv")
    second = _upload_and_run(client, "cmp-again.csv")

    resp = client.get(f"/api/v1/assessments/compare?from={first}&to={second}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["from"] == first and body["to"] == second
    comparison = body["comparison"]
    assert comparison["overall"]["delta"] == 0.0
    assert comparison["verdict"] == "No overall quality change."
    # repeated issues are computed as a list
    assert isinstance(comparison["issues"]["repeated"], list)


def test_compare_reports_degradation_for_changed_data(logged_in_user):
    client = logged_in_user["client"]
    first = _upload_and_run(client, csv=(
        "name,age,city,salary\nA,29,London,48000\nB,,Paris,\n"))
    worse = (
        "name,age,city,salary\nA,29,London,48000\nB,,Paris,999999\n"
        "B,,Paris,999999\n")
    second = _upload_and_run(client, "cmp-worse.csv", worse)

    resp = client.get(f"/api/v1/assessments/compare?from={first}&to={second}")
    assert resp.status_code == 200
    comparison = resp.get_json()["comparison"]
    assert comparison["overall"]["delta"] < 0
    assert "degraded" in comparison["verdict"]


def test_compare_requires_both_ids(logged_in_user):
    client = logged_in_user["client"]
    resp = client.get("/api/v1/assessments/compare?from=5")
    assert resp.status_code == 400
    assert "'from' and 'to'" in resp.get_json()["error"]


def test_compare_rejects_same_ids(logged_in_user):
    client = logged_in_user["client"]
    resp = client.get("/api/v1/assessments/compare?from=7&to=7")
    assert resp.status_code == 400
    assert "different" in resp.get_json()["error"]


def test_compare_unknown_or_foreign_assessment_is_404(
    logged_in_user, second_user
):
    client = logged_in_user["client"]
    mine = _upload_and_run(client)

    resp = client.get(f"/api/v1/assessments/compare?from={mine}&to=999999")
    assert resp.status_code == 404

    # second user creates their own assessment; `mine` stays invisible to them
    theirs = _upload_and_run(second_user, "theirs.csv")
    resp = second_user.get(
        f"/api/v1/assessments/compare?from={mine}&to={theirs}"
    )
    assert resp.status_code == 404
