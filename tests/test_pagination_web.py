"""Tests for web pagination on the dashboard and dataset history."""
from __future__ import annotations

import io

from datasure.pagination import clamp_page_size, paginate_stable


def test_clamp_page_size_bounds():
    assert clamp_page_size(None) == 20
    assert clamp_page_size(0) == 1
    assert clamp_page_size(500) == 100
    assert clamp_page_size(7) == 7


def test_paginate_stable_out_of_range_page(app):
    from datasure.models import Dataset
    with app.app_context():
        result = paginate_stable(
            Dataset.query.order_by(Dataset.id), page=99, per_page=2)
        assert result["items"] == []
        assert result["pages"] == 0


def _make_datasets(client, count: int) -> None:
    for index in range(count):
        content = f"a,b\n{index},x\n".encode()
        resp = client.post(
            "/datasets/upload",
            data={"file": (io.BytesIO(content), f"p{index}.csv")},
            content_type="multipart/form-data", follow_redirects=False,
        )
        assert resp.status_code == 302


def test_dashboard_paginates_after_21_datasets(app, logged_in_user):
    client = logged_in_user["client"]
    _make_datasets(client, 21)
    resp = client.get("/dashboard")
    page = resp.data.decode("utf-8")
    assert "Page 1 of 2" in page
    assert "Next" in page
    # newest first: page 1 starts with p20; page 2 holds the oldest single row
    assert b"p20.csv" in resp.data
    resp = client.get("/dashboard?page=2")
    assert b"p0.csv" in resp.data
    assert b"p20.csv" not in resp.data


def test_history_page_pagination(app, logged_in_user):
    client = logged_in_user["client"]
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2\n3,4\n"), "h.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    for index in range(22):
        client.post(f"/datasets/{dataset_id}/assess",
                    data={"label": f"run{index}"}, follow_redirects=True)
    resp = client.get(f"/datasets/history?dataset_id={dataset_id}")
    page = resp.data.decode("utf-8")
    assert "Page 1 of 2" in page
    assert b"run21" in resp.data  # newest first on page 1
    resp = client.get(f"/datasets/history?dataset_id={dataset_id}&page=2")
    assert b"run0" in resp.data
    assert b"run21" not in resp.data
