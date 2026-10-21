"""Accessibility structure tests: landmarks, skip link, table captions."""
from __future__ import annotations

import io

from datasure.models import Assessment, db


def test_base_template_has_skip_link_and_landmarks(client):
    resp = client.get("/login")
    text = resp.data.decode("utf-8")
    assert 'href="#main-content"' in text
    # skip link appears before the navbar in the document
    assert text.index("Skip to main content") < text.index("<nav")
    assert 'aria-label="Primary"' in text
    assert '<main class="container pb-5" id="main-content">' in text
    assert '<footer' in text  # existing footer landmark kept


def test_report_tables_have_captions_and_scoped_headers(app, logged_in_user):
    client = logged_in_user["client"]
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b,c\n1,x,3\n2,y,4\n1,x,5\n"), "report.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    client.post(
        f"/datasets/{dataset_id}/clean/apply",
        data={"operation": "drop_duplicate_rows", "param_keep": "first"},
        follow_redirects=True,
    )
    client.post(f"/datasets/{dataset_id}/assess", data={}, follow_redirects=True)
    with app.app_context():
        assessment_id = (
            Assessment.query.filter_by(dataset_id=dataset_id)
            .order_by(Assessment.id.desc()).first().id
        )
    resp = client.get(f"/datasets/{dataset_id}/assessments/{assessment_id}/report")
    text = resp.data.decode("utf-8")
    # every data table has a caption and a scoped header row
    assert text.count("<caption") == 3  # dimensions, column stats, cleaning
    assert text.count("<caption") == text.count("<thead>")
    assert 'scope="col"' in text
    assert "<thead>" in text and "<tbody>" in text


def test_report_chart_images_have_descriptive_alt(app, logged_in_user):
    client = logged_in_user["client"]
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,x\n2,y\n"), "alt.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    client.post(f"/datasets/{dataset_id}/assess", data={}, follow_redirects=True)
    with app.app_context():
        assessment_id = (
            Assessment.query.filter_by(dataset_id=dataset_id)
            .order_by(Assessment.id.desc()).first().id
        )
    resp = client.get(f"/datasets/{dataset_id}/assessments/{assessment_id}/report")
    text = resp.data.decode("utf-8")
    assert 'alt="Chart for ' in text
    assert '<img src="data:' in text  # embedded chart images remain data URIs


def test_report_is_valid_standalone_html(app, logged_in_user):
    """Report page must keep its own doctype/head since it renders standalone."""
    client = logged_in_user["client"]
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,x\n"), "standalone.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    client.post(f"/datasets/{dataset_id}/assess", data={}, follow_redirects=True)
    with app.app_context():
        assessment_id = (
            Assessment.query.filter_by(dataset_id=dataset_id)
            .order_by(Assessment.id.desc()).first().id
        )
    resp = client.get(f"/datasets/{dataset_id}/assessments/{assessment_id}/report")
    text = resp.data.decode("utf-8")
    assert text.lstrip().lower().startswith("<!doctype html>")
    assert "<html lang=\"en\">" in text
    # no stray template leakage from the caption refactor
    assert "{%" not in text and "}}" not in text

