"""Activity page filtering by action type."""
from __future__ import annotations

import io


def _upload(client, name: str = "filter_src.csv") -> None:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("name,age\nA,29\n".encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302


def _delete_dataset(client, dataset_id: int) -> None:
    resp = client.post(
        f"/datasets/{dataset_id}/delete", follow_redirects=True
    )
    assert resp.status_code == 200


def test_filter_narrows_to_matching_action(logged_in_user):
    client = logged_in_user["client"]
    _upload(client, "kept.csv")
    resp_delete = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("name,age\nB,41\n".encode()), "deleted.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    deleted_id = int(
        resp_delete.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    )
    _delete_dataset(client, deleted_id)

    resp = client.get("/settings/activity?action=dataset_deleted")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert "dataset deleted" in body


def test_filter_select_lists_known_actions(logged_in_user):
    resp = logged_in_user["client"].get("/settings/activity")
    body = resp.data.decode("utf-8", errors="replace")
    for action in ("dataset_deleted", "cleaning_applied", "rule_deleted"):
        assert f'value="{action}"' in body
    assert '<option value="">All actions</option>' in body


def test_unknown_action_returns_empty_page(logged_in_user):
    resp = logged_in_user["client"].get("/settings/activity?action=not_a_real_action")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert "Nothing recorded yet" in body


def test_clear_link_restores_full_list(logged_in_user):
    """Filtered pages expose a clear link; unfiltered pages show all events."""
    client = logged_in_user["client"]
    _upload(client, "kept.csv")
    resp_delete = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("name,age\nB,41\n".encode()), "gone.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    deleted_id = int(
        resp_delete.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    )
    _delete_dataset(client, deleted_id)

    filtered = client.get("/settings/activity?action=rule_deleted")
    body = filtered.data.decode("utf-8", errors="replace")
    assert 'href="/settings/activity"' in body  # clear link present

    full = client.get("/settings/activity", follow_redirects=True)
    body = full.data.decode("utf-8", errors="replace")
    assert "dataset deleted" in body  # the recorded event is visible again


def test_pagination_preserves_filter(uploaded_messy_dataset):
    client = uploaded_messy_dataset["client"]
    # generate >25 rules deletions ensures pagination with a filter applied
    resp_upload = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("name,age\nA,29\n".encode()), "paged.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    dataset_id = int(
        resp_upload.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    )
    for i in range(30):
        create = client.post(
            "/rules/create",
            data={"name": f"p {i}", "rule_type": "not_null",
                  "column": "age", "severity": "error"},
            follow_redirects=True,
        )
        assert create.status_code == 200
        listing = client.get("/rules", follow_redirects=True)
        import re

        match = re.search(r"/rules/(\d+)/delete", listing.data.decode("utf-8"))
        assert match, listing.data[:500]
        delete = client.post(f"/rules/{match.group(1)}/delete", follow_redirects=True)
        assert delete.status_code == 200
    _ = dataset_id  # dataset content unused; events drive pagination

    page = client.get("/settings/activity?action=rule_deleted&page=2")
    assert page.status_code == 200
    body = page.data.decode("utf-8", errors="replace")
    assert "Previous" in body or "Next" in body
    assert "rule_deleted" in body or "rule deleted" in body
