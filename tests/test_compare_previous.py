"""Assessment page: 'Compare with previous run' affordance."""
from __future__ import annotations

import io


def _upload_and_run(client, name: str, csv: str, runs: int = 1) -> tuple[int, int]:
    """Upload one dataset and run `runs` assessments on it; returns (dataset_id, latest_assessment_id)."""
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    latest = None
    for _ in range(runs):
        resp = client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})
        assert resp.status_code == 201, resp.data
        latest = resp.get_json()["id"]
    return dataset_id, latest


def test_first_run_has_no_compare_link(logged_in_user):
    client = logged_in_user["client"]
    dataset_id, assessment_id = _upload_and_run(client, "first.csv", "a,b\n1,2\n")
    body = client.get(
        f"/datasets/{dataset_id}/assessments/{assessment_id}"
    ).data.decode("utf-8", errors="replace")
    assert "Compare with previous run" not in body


def test_second_run_links_to_previous(logged_in_user):
    client = logged_in_user["client"]
    dataset_id, first_id = _upload_and_run(
        client, "one.csv", "a,b\n1,2\n"
    )
    # second assessment on the SAME dataset
    resp = client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})
    assert resp.status_code == 201
    second_id = resp.get_json()["id"]

    body = client.get(
        f"/datasets/{dataset_id}/assessments/{second_id}"
    ).data.decode("utf-8", errors="replace")
    # href attributes escape '&' as &amp;
    assert (
        f"/datasets/{dataset_id}/compare?from={first_id}&amp;to={second_id}" in body
    )
    assert "Compare with previous run" in body

    # the link itself works
    compare = client.get(
        f"/datasets/{dataset_id}/compare?from={first_id}&to={second_id}",
        follow_redirects=True,
    )
    assert compare.status_code == 200
