"""Data dictionary downloads: Markdown and JSON, built from the profile."""
from __future__ import annotations

import io
import json


def _upload_and_run(client, name: str = "dict_src.csv") -> int:
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


def test_dictionary_markdown_download(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_run(client)

    resp = client.get(f"/datasets/{dataset_id}/dictionary")
    assert resp.status_code == 200
    assert resp.mimetype == "text/markdown"
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition and "_dictionary.md" in disposition
    body = resp.data.decode()
    assert "# Data dictionary:" in body
    assert "| name |" in body and "| age |" in body
    assert "| Column | Type | Kind | Non-null | Missing | Unique | Notes |" in body
    # never includes dataset values, only column metadata
    assert "London" not in body


def test_dictionary_json_download(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_run(client)

    resp = client.get(f"/datasets/{dataset_id}/dictionary?format=json")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["dataset_id"] == dataset_id
    assert payload["row_count"] == 2
    names = [column["name"] for column in payload["columns"]]
    assert names == ["name", "age", "city", "salary"]


def test_dictionary_requires_assessment_first(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_run(client)

    resp = client.get(f"/datasets/{dataset_id}/dictionary")
    assert resp.status_code == 200

    # a dataset without any assessment redirects with a warning
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("a,b\n1,2\n".encode()), "no_assess.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    resp = client.get(f"/datasets/{dataset_id}/dictionary", follow_redirects=True)
    body = resp.data.decode("utf-8", errors="replace")
    assert "Run an assessment first" in body


def test_dictionary_is_scoped(uploaded_messy_dataset, second_user):
    dataset_id = uploaded_messy_dataset["dataset_id"]
    resp = second_user.get(f"/datasets/{dataset_id}/dictionary")
    assert resp.status_code == 404


def test_dictionary_button_on_detail_page(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_run(client)
    resp = client.get(f"/datasets/{dataset_id}")
    assert "Data dictionary" in resp.data.decode("utf-8", errors="replace")
