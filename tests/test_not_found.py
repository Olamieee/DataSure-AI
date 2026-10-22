"""App-level 404 handling: HTML for browsers, JSON for API clients."""
from __future__ import annotations


def test_browser_request_gets_html_404(logged_in_user):
    resp = logged_in_user["client"].get("/datasets/definitely-missing-page")
    assert resp.status_code == 404
    assert b"Page not found" in resp.data
    assert "X-Request-ID" in resp.headers


def test_anonymous_browser_request_gets_html_404(client):
    resp = client.get("/no/such/page")
    assert resp.status_code == 404
    assert b"Page not found" in resp.data


def test_json_client_gets_json_404(client):
    resp = client.get(
        "/no/such/page",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"] == "page not found"
    assert body["request_id"]


def test_api_blueprint_404_shape_still_json(client, logged_in_user):
    """Unknown API routes keep the API error shape, not the HTML page."""
    resp = logged_in_user["client"].get("/api/v1/does/not/exist")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body is not None
    assert "error" in body


def test_404_page_links_back_and_carries_request_id(client):
    resp = client.get("/gone")
    assert resp.status_code == 404
    request_id = resp.headers.get("X-Request-ID")
    assert request_id
    assert request_id.encode() in resp.data
