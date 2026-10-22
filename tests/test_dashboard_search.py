"""Dashboard search: case-insensitive name filter with scoping."""
from __future__ import annotations

import io


def _upload(client, name: str, csv: str = "name,age\nA,29\n") -> None:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_search_filters_by_name_substring(logged_in_user):
    client = logged_in_user["client"]
    _upload(client, "sales 2024.csv", "name,age\nA,29\n")
    _upload(client, "payroll data.csv", "name,age\nB,41\n")
    _upload(client, "Sales archive.csv", "name,age\nC,33\n")

    resp = client.get("/dashboard?q=sales", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert "sales 2024.csv" in body
    assert "Sales archive.csv" in body
    assert "payroll data.csv" not in body


def test_search_is_case_insensitive(logged_in_user):
    client = logged_in_user["client"]
    _upload(client, "Q4 Metrics.csv")
    resp = client.get("/dashboard?q=q4", follow_redirects=True)
    assert "Q4 Metrics.csv" in resp.data.decode("utf-8", errors="replace")


def test_search_no_matches_shows_friendly_state(logged_in_user):
    client = logged_in_user["client"]
    _upload(client, "regular.csv")
    resp = client.get("/dashboard?q=zebra", follow_redirects=True)
    body = resp.data.decode("utf-8", errors="replace")
    assert "No datasets match" in body
    assert "zebra" in body


def test_empty_query_lists_all(logged_in_user):
    client = logged_in_user["client"]
    _upload(client, "one.csv")
    _upload(client, "two.csv")
    resp = client.get("/dashboard", follow_redirects=True)
    body = resp.data.decode("utf-8", errors="replace")
    assert "one.csv" in body and "two.csv" in body


def test_search_is_scoped_to_owner(uploaded_messy_dataset, second_user):
    _upload(uploaded_messy_dataset["client"], "only_theirs.csv")

    resp = second_user.get("/dashboard?q=only_theirs", follow_redirects=True)
    body = resp.data.decode("utf-8", errors="replace")
    assert "only_theirs.csv" not in body


def test_search_wildcards_are_escaped(logged_in_user):
    client = logged_in_user["client"]
    _upload(client, "regular.csv")
    # a bare % would match everything without autoescape
    resp = client.get("/dashboard?q=%", follow_redirects=True)
    body = resp.data.decode("utf-8", errors="replace")
    assert "No datasets match" in body


def test_pagination_links_preserve_search(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    for i in range(25):
        _upload(client, f"report {i}.csv")

    resp = client.get("/dashboard?q=report", follow_redirects=True)
    body = resp.data.decode("utf-8", errors="replace")
    assert "q=report" in body  # next-page links keep the query
