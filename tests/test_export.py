"""Tests for CSV export of assessment issues and column statistics."""
from __future__ import annotations

import csv
import io


def _upload_and_assess(client, content: bytes, name: str) -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(content), name)},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    resp = client.post(f"/datasets/{dataset_id}/assess", data={}, follow_redirects=False)
    assert resp.status_code == 302
    return dataset_id


def test_issues_export_csv(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_assess(
        client, b"a,b\n1,\n1,\n2,3\n", "messy-a.csv")
    resp = client.get(f"/datasets/{dataset_id}/export/issues.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in resp.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(resp.data.decode("utf-8"))))
    assert rows[0] == ["kind", "severity", "columns", "message"]
    assert len(rows) > 1  # the empty cells in column b produce issues


def test_stats_export_csv_matches_profile_columns(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_assess(
        client, b"a,b,c\n1,x,3\n2,y,4\n3,x,5\n4,y,6\n5,z,7\n", "people.csv")
    resp = client.get(f"/datasets/{dataset_id}/export/stats.csv")
    rows = list(csv.reader(io.StringIO(resp.data.decode("utf-8"))))
    header = rows[0]
    assert header[:9] == ["column", "dtype", "kind", "non_null", "missing",
                          "missing_pct", "unique", "constant", "is_identifier"]
    names = {row[0] for row in rows[1:]}
    assert names == {"a", "b", "c"}
    # numeric column row carries the stats block
    row_a = next(row for row in rows[1:] if row[0] == "a")
    assert row_a[header.index("min")] == "1.0"  # floats round-trip as written


def test_special_characters_are_properly_escaped(app, logged_in_user):
    """Column names with commas/quotes survive the CSV round trip intact."""
    client = logged_in_user["client"]
    tricky = 'weird,"col,name",b\n1,2,3\n4,,6\n'  # missing cell in col,name
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(tricky.encode()), "tricky.csv")},
        content_type="multipart/form-data", follow_redirects=False,
    )
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    client.post(f"/datasets/{dataset_id}/assess", data={}, follow_redirects=True)
    resp = client.get(f"/datasets/{dataset_id}/export/stats.csv")
    rows = list(csv.reader(io.StringIO(resp.data.decode("utf-8"))))
    names = [row[0] for row in rows[1:]]
    assert names == ["weird", "col,name", "b"]  # embedded comma, not split

    resp = client.get(f"/datasets/{dataset_id}/export/issues.csv")
    rows = list(csv.reader(io.StringIO(resp.data.decode("utf-8"))))
    columns_joined = "".join(row[2] for row in rows[1:])
    assert "col,name" in columns_joined  # properly re-quoted in the export


def test_export_without_assessment_redirects(app, logged_in_user):
    client = logged_in_user["client"]
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2\n"), "noassess.csv")},
        content_type="multipart/form-data", follow_redirects=True,
    )
    dataset_id = resp.request.path.rstrip("/").rsplit("/", 1)[-1]
    resp = client.get(f"/datasets/{dataset_id}/export/issues.csv",
                      follow_redirects=True)
    assert b"Run an assessment first" in resp.data


def test_unknown_export_kind_is_404(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_assess(client, b"a,b\n1,2\n", "kindx.csv")
    assert client.get(f"/datasets/{dataset_id}/export/other.csv").status_code == 404


def test_export_is_owner_scoped(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    dataset_id = _upload_and_assess(client, b"a,b\n1,2\n", "private.csv")
    assert second_user.get(f"/datasets/{dataset_id}/export/issues.csv",
                           follow_redirects=False).status_code == 404
