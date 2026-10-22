"""Dataset tags: edit form, validation, dashboard search matching, scoping."""
from __future__ import annotations

import io


def _upload(client, name: str = "tagged.csv") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("name,age\nA,29\n".encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _set_tags(client, dataset_id: int, tags: str):
    return client.post(
        f"/datasets/{dataset_id}/tags",
        data={"tags": tags},
        follow_redirects=True,
    )


def test_tags_are_saved_and_displayed(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)

    resp = _set_tags(client, dataset_id, "  sales , 2024 , q4 ")
    assert resp.status_code == 200
    detail = client.get(f"/datasets/{dataset_id}")
    body = detail.data.decode("utf-8", errors="replace")
    assert "sales" in body and "2024" in body
    assert 'value="sales,2024,q4"' in body  # trimmed, comma-joined

    dashboard = client.get("/dashboard?q=sales")
    assert "tagged.csv" in dashboard.data.decode("utf-8", errors="replace")


def test_tags_dedupe_case_insensitively(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    _set_tags(client, dataset_id, "Finance, finance, FINANCE, reports")
    detail = client.get(f"/datasets/{dataset_id}")
    body = detail.data.decode("utf-8", errors="replace")
    assert "Finance" in body and "reports" in body
    # stored value keeps the first spelling only
    assert 'value="Finance,reports"' in body


def test_tags_cleared_with_empty_value(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    resp = _set_tags(client, dataset_id, "temp")
    assert resp.status_code == 200
    resp = _set_tags(client, dataset_id, "")
    body = resp.data.decode("utf-8", errors="replace")
    assert "Tags cleared." in body
    detail = client.get(f"/datasets/{dataset_id}")
    assert 'value=""' in detail.data.decode("utf-8", errors="replace")


def test_tag_count_and_length_limit(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    resp = _set_tags(
        client, dataset_id,
        "a,b,c,d,e,f,g,h,i,j,k",  # 11 tags > limit of 10
    )
    body = resp.data.decode("utf-8", errors="replace")
    assert "Too many tags" in body
    detail = client.get(f"/datasets/{dataset_id}")
    assert 'value=""' in detail.data.decode("utf-8", errors="replace")


def test_dashboard_search_matches_tags(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, "boring name.csv")
    _set_tags(client, dataset_id, "payroll")

    resp = client.get("/dashboard?q=payroll", follow_redirects=True)
    body = resp.data.decode("utf-8", errors="replace")
    assert "boring name.csv" in body


def test_tags_are_scoped_per_user(uploaded_messy_dataset, second_user):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    _set_tags(client, dataset_id, "mine-only")

    resp = second_user.post(
        f"/datasets/{dataset_id}/tags", data={"tags": "hijack"}
    )
    assert resp.status_code == 404  # not their dataset
    body = resp.data.decode("utf-8", errors="replace")
    assert "hijack" not in body

    detail = client.get(f"/datasets/{dataset_id}")
    assert 'value="mine-only"' in detail.data.decode("utf-8", errors="replace")
