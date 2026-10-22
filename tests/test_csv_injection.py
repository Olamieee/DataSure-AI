"""CSV formula-injection guard on exports."""
from __future__ import annotations

import io


def _upload_and_assess(client, name: str, csv: str) -> int:
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


def test_stats_export_neutralises_formula_column_name(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_assess(
        client, "formula.csv", "=1+1,ok\n1,2\n2,3\n"
    )

    resp = client.get(f"/datasets/{dataset_id}/export/stats.csv")
    assert resp.status_code == 200
    body = resp.data.decode()
    # the dangerous cell is guarded with a leading apostrophe
    assert "'=1+1" in body
    # and never appears as a bare leading formula
    for line in body.splitlines():
        if line and not line.startswith(("column,", "kind,")):
            for cell in line.split(","):
                if cell and cell != '"=1+1"':
                    assert not cell.startswith("=1+1"), line


def test_api_issues_export_is_guarded(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_assess(
        client, "formula_issues.csv", "=2+2,b\n1,2\n2,3\n"
    )
    assessment_id = client.get(
        f"/api/v1/datasets/{dataset_id}"
    ).get_json()["latest_assessment_id"]

    resp = client.get(f"/api/v1/assessments/{assessment_id}/export/issues.csv")
    assert resp.status_code == 200
    body = resp.data.decode()
    # any issue message or column list must not start with an executable char
    assert "kind,severity,columns,message" in body  # header untouched
    for line in body.splitlines()[1:]:
        if not line.strip():
            continue
        assert not line.startswith("=")


def test_small_numbers_are_not_guarded(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_assess(
        client, "harmless.csv", "a,b\n1,-3\n2,+5\n"
    )

    resp = client.get(f"/datasets/{dataset_id}/export/stats.csv")
    body = resp.data.decode()
    # negative values start with '-' and must pass through untouched
    assert "'-3" not in body and "'+5" not in body
