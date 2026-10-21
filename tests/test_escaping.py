"""Regression tests: user-supplied labels and cells never reach HTML raw."""
from __future__ import annotations

import io

PAYLOAD_FILE = (
    b"a,b\n1,<script>alert(1)</script>\n2,<img src=x onerror=alert(2)>\n"
)
LABEL = '<script>alert("label")</script>'


def _upload_file(client, content: bytes = PAYLOAD_FILE, name: str = "cells.csv") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(content), name)},
        content_type="multipart/form-data", follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _current_assessment_id(app, dataset_id: int) -> int:
    from datasure.models import Assessment, db

    with app.app_context():
        return (
            Assessment.query.filter_by(dataset_id=dataset_id)
            .order_by(Assessment.id.desc())
            .first()
            .id
        )


def test_dataset_name_escaped_everywhere(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_file(client)
    for path in (
        f"/datasets/{dataset_id}",
        f"/datasets/{dataset_id}/clean",
        "/dashboard",
        "/datasets/history",
    ):
        resp = client.get(path)
        text = resp.data.decode("utf-8")
        assert "<script>alert" not in text, f"raw script leaked on {path}"


def test_assessment_page_escapes_labels(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_file(client)
    resp = client.post(f"/datasets/{dataset_id}/assess",
                       data={"label": LABEL}, follow_redirects=False)
    assert resp.status_code == 302
    assessment_id = _current_assessment_id(app, dataset_id)
    resp = client.get(f"/datasets/{dataset_id}/assessments/{assessment_id}")
    text = resp.data.decode("utf-8")
    assert '<script>alert("label")</script>' not in text
    assert "&lt;script&gt;alert(&#34;label&#34;)&lt;/script&gt;" in text


def test_cleaning_preview_escapes_cells(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_file(client)
    resp = client.post(
        f"/datasets/{dataset_id}/clean/preview",
        data={"operation": "sort_values", "param_column": "a",
              "param_ascending": "true"},
        follow_redirects=True,
    )
    text = resp.data.decode("utf-8")
    assert "<script>alert(1)</script>" not in text
    assert "<img src=x onerror" not in text


def test_history_page_escapes_labels(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_file(client)
    client.post(f"/datasets/{dataset_id}/assess", data={"label": LABEL},
                follow_redirects=True)
    resp = client.get("/datasets/history")
    text = resp.data.decode("utf-8")
    assert '<script>alert("label")</script>' not in text  # never raw executable
    assert "&lt;script&gt;" in text                      # rendered escaped


def test_html_report_page_escapes_content(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_file(client)
    client.post(f"/datasets/{dataset_id}/assess", data={}, follow_redirects=True)
    assessment_id = _current_assessment_id(app, dataset_id)
    resp = client.get(f"/datasets/{dataset_id}/assessments/{assessment_id}/report")
    text = resp.data.decode("utf-8")
    assert "<script>alert(1)</script>" not in text
