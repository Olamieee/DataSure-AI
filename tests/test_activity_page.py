"""The /settings/activity audit viewer: scoping, pagination, content."""
from __future__ import annotations

import io


def _upload(client, name="activity_test.csv"):
    csv = "name,age\nA,29\n"
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _create_rule(client, name):
    return client.post(
        "/rules/create",
        data={"name": name, "rule_type": "not_null", "column": "age",
              "severity": "error"},
        follow_redirects=True,
    )


def _delete_rule(client, rule_id):
    return client.post(f"/rules/{rule_id}/delete", follow_redirects=True)


def test_activity_page_is_private(client, app):
    # registering the anonymous user via the viewer would 302 to login
    resp = client.get("/settings/activity", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_activity_lists_own_actions_with_details(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client)
    _create_rule(client, "not-null-age")
    _delete_rule(client, 1)

    resp = client.get("/settings/activity")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert "rule_deleted" in body
    assert "not-null-age" in body
    assert f"#{dataset_id}"in body or "dataset" in body.lower()


def test_activity_scoped_to_other_users(second_user, uploaded_messy_dataset):
    """User B must not see user A's audit events."""
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    _upload(client, "another_upload.csv")

    resp = second_user.get("/settings/activity")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    # second user has no recorded actions
    assert f"#{dataset_id}" not in body


def test_activity_empty_state(logged_in_user):
    resp = logged_in_user["client"].get("/settings/activity")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert "Nothing recorded yet" in body


def test_activity_nav_link_present(logged_in_user):
    resp = logged_in_user["client"].get("/settings/activity")
    body = resp.data.decode("utf-8", errors="replace")
    assert "/settings/activity" in body
    assert 'aria-label="Primary"' in body  # nav keeps accessibility structure


def test_activity_pagination_links(uploaded_messy_dataset, logged_in_user):
    client = uploaded_messy_dataset["client"]
    for i in range(30):
        _upload(client, f"bulk_{i}.csv")

    page2 = client.get("/settings/activity?page=2")
    assert page2.status_code == 200
    body = page2.data.decode("utf-8", errors="replace")
    assert "Next" in body or "Previous" in body
    assert "page 2" in body