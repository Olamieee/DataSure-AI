"""flask db-stats: per-table row counts for ops."""
from __future__ import annotations

import io


def _upload(client, name: str = "stats_src.csv") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("name,age\nA,29\n".encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_db_stats_empty_database(app):
    result = app.test_cli_runner().invoke(args=["db-stats"])
    assert result.exit_code == 0
    for table in ("users", "datasets", "assessments", "audit_events"):
        assert f"{table}: 0" in result.output
    assert "Database is empty." in result.output


def test_db_stats_counts_created_rows(app, logged_in_user):
    client = logged_in_user["client"]
    _upload(client)

    result = app.test_cli_runner().invoke(args=["db-stats"])
    assert result.exit_code == 0
    output = result.output
    assert "users: 1" in output
    assert "datasets: 1" in output
    assert "Database is empty." not in output
