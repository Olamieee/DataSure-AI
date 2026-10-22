"""REST API CSV exports of assessment issues and column statistics."""
from __future__ import annotations

import io


def _upload_and_run_assessment(client):
    csv = "name,age,city,salary\nA,29,London,48000\nB,39,Paris,52000\nC,,Paris,\n"
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), "export_src.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    resp = client.post(f"/api/v1/datasets/{dataset_id}/assessments", json={})
    assert resp.status_code == 201, resp.data
    return resp.get_json()["id"]


def test_issues_export_csv(logged_in_user):
    client = logged_in_user["client"]
    assessment_id = _upload_and_run_assessment(client)
    resp = client.get(f"/api/v1/assessments/{assessment_id}/export/issues.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition and "issues.csv" in disposition
    first_line = resp.data.split(b"\r\n")[0]
    assert first_line == b"kind,severity,columns,message"


def test_stats_export_csv(logged_in_user):
    client = logged_in_user["client"]
    assessment_id = _upload_and_run_assessment(client)
    resp = client.get(f"/api/v1/assessments/{assessment_id}/export/stats.csv")
    assert resp.status_code == 200
    header = resp.data.split(b"\r\n")[0].decode()
    assert header.startswith(
        "column,dtype,kind,non_null,missing,missing_pct,unique"
    )
    body = resp.data.decode("utf-8", errors="replace")
    assert "age" in body  # one row per column of the profile


def test_unknown_export_kind_is_404(logged_in_user):
    client = logged_in_user["client"]
    assessment_id = _upload_and_run_assessment(client)
    resp = client.get(
        f"/api/v1/assessments/{assessment_id}/export/totally-bogus.csv"
    )
    assert resp.status_code == 404
    assert "unknown export kind" in resp.get_json()["error"]


def test_exports_require_assessment_scoping(logged_in_user, second_user):
    client = logged_in_user["client"]
    assessment_id = _upload_and_run_assessment(client)

    resp = second_user.get(f"/api/v1/assessments/{assessment_id}/export/issues.csv")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "assessment not found"

    resp = client.get(
        f"/api/v1/assessments/{assessment_id}/export/issues.csv",
    )
    assert resp.status_code == 200  # own assessment stays accessible


def test_export_requires_auth(app, logged_in_user):
    from datasure.auth.apikeys import create_key
    from datasure.models import User, db

    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        _record, raw = create_key(user, "export key")
    assessment_id = _upload_and_run_assessment(logged_in_user["client"])
    anonymous = app.test_client()  # no cookies, no headers

    resp = anonymous.get(f"/api/v1/assessments/{assessment_id}/export/issues.csv")
    assert resp.status_code == 401
    resp = anonymous.get(
        f"/api/v1/assessments/{assessment_id}/export/issues.csv",
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
