"""Tests for dataset ingestion and upload security."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from datasure.datasets.ingest import (
    DatasetParseError,
    dataframe_schema,
    dataset_preview,
    load_dataframe,
    parse_uploaded_dataset,
)
from datasure.storage import safe_extension, sanitize_display_name

from tests.conftest import make_upload_bytes

# ---------------------------------------------------------------- safe_extension
def test_safe_extension_accepts_allowed():
    assert safe_extension("a.csv", {".csv", ".xlsx"}) == ".csv"


def test_safe_extension_rejects_disallowed():
    with pytest.raises(ValueError, match="Unsupported file type"):
        safe_extension("payload.exe", {".csv"})


def test_safe_extension_rejects_hidden_extension():
    with pytest.raises(ValueError, match="Unsupported file type"):
        safe_extension(".htaccess", {".csv"})


def test_sanitize_display_name_strips_path_traversal():
    name = "../../..\\Windows\\system32\\evil.exe"
    cleaned = sanitize_display_name(name)
    assert ".." not in cleaned
    assert "/" not in cleaned
    assert "\\" not in cleaned


def test_sanitize_display_name_empty():
    assert sanitize_display_name("") == "unnamed_dataset"


# ---------------------------------------------------------------- load_dataframe
def test_load_csv(utf8_csv: Path):
    df = load_dataframe(utf8_csv, ".csv", 10_000, 100)
    assert list(df.columns) == ["name", "age", "city", "salary"]
    assert len(df) == 3


@pytest.fixture()
def utf8_csv(tmp_path):
    path = tmp_path / "people.csv"
    path.write_text("name,age,city,salary\nAnn,30,Paris,100\nBob,31,London,200\nCy,32,Rome,300\n",
                    encoding="utf-8")
    return path


@pytest.fixture()
def cp1252_csv(tmp_path):
    path = tmp_path / "accents.csv"
    path.write_bytes("name,city\nJosé,Mexico\nAñez,Madrid\n".encode("cp1252"))
    return path


@pytest.fixture()
def semicolon_csv(tmp_path):
    path = tmp_path / "semi.csv"
    path.write_text("name;age\nAnn;30\nBob;31\nCy;32\n", encoding="utf-8")
    return path


@pytest.fixture()
def headerless_csv(tmp_path):
    path = tmp_path / "header_extra.csv"
    path.write_text(",,\nname,age\nAnn,30\n", encoding="utf-8")
    return path


@pytest.fixture()
def dup_column_csv(tmp_path):
    path = tmp_path / "dup.csv"
    path.write_text("a,b,a\n1,2,3\n4,5,6\n", encoding="utf-8")
    return path


def test_load_csv_utf8(utf8_csv):
    df = load_dataframe(utf8_csv, ".csv", 10_000, 100)
    assert list(df.columns) == ["name", "age", "city", "salary"]
    assert len(df) == 3


def test_load_csv_encoding_fallback(cp1252_csv):
    df = load_dataframe(cp1252_csv, ".csv", 10_000, 100)
    # utf-8-sig decoding of 0xE9 fails, so cp1252 fallback must succeed
    assert "name" in df.columns
    assert len(df) == 2


def test_load_csv_delimiter_sniffing(semicolon_csv):
    df = load_dataframe(semicolon_csv, ".csv", 10_000, 100)
    assert set(df.columns) >= {"name", "age"}


def test_load_csv_unnamed_headers(headerless_csv):
    df = load_dataframe(headerless_csv, ".csv", 10_000, 100)
    assert all(name != "" for name in df.columns)
    assert df.iloc[0]["name" if "name" in df.columns else df.columns[0]]


def test_load_csv_duplicate_column_names(dup_column_csv):
    df = load_dataframe(dup_column_csv, ".csv", 10_000, 100)
    lowered = [c.lower() for c in df.columns]
    assert len(lowered) == len(set(lowered))


def test_load_csv_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DatasetParseError, match="empty"):
        load_dataframe(path, ".csv", 10_000, 100)


def test_load_csv_row_limit(tmp_path):
    path = tmp_path / "big.csv"
    path.write_text("a\n" + "\n".join(str(i) for i in range(10)), encoding="utf-8")
    with pytest.raises(DatasetParseError, match="exceeding"):
        load_dataframe(path, ".csv", 5, 100)


def test_load_csv_column_limit(tmp_path):
    path = tmp_path / "wide.csv"
    path.write_text(",".join(f"c{i}" for i in range(10)) + "\n" + ",".join("x" for _ in range(10)),
                    encoding="utf-8")
    with pytest.raises(DatasetParseError, match="columns"):
        load_dataframe(path, ".csv", 10_000, 5)


def test_load_missing_file(tmp_path):
    with pytest.raises(DatasetParseError, match="could not be found"):
        load_dataframe(tmp_path / "missing.csv", ".csv", 10_000, 100)


# ---------------------------------------------------------------- parse + upload flow
def test_parse_uploaded_dataset_rejects_bad_extension(app, tmp_path):
    class FakeFile:
        filename = "report.pdf"
        def save(self, dest):
            dest.write_bytes(b"x")

    with pytest.raises(DatasetParseError, match="Unsupported file type"):
        parse_uploaded_dataset(
            FakeFile(), {".csv", ".tsv", ".xlsx", ".xls"}, str(tmp_path), 1, 10_000, 100
        )


def test_parse_uploaded_dataset_rejects_bad_content(app, tmp_path):
    class FakeFile:
        filename = "binary.csv"
        def save(self, dest):
            dest.write_bytes(bytes(range(256)) * 50)

    with pytest.raises(DatasetParseError):
        parse_uploaded_dataset(
            FakeFile(), {".csv", ".tsv", ".xlsx", ".xls"}, str(tmp_path), 1, 10_000, 100
        )


# ---------------------------------------------------------------- upload endpoint security
def test_upload_rejects_disallowed_extension(app, logged_in_user):
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"<html></html>"), "page.html")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert b"Unsupported file type" in resp.data


def test_upload_empty_file_rejected(app, logged_in_user):
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b""), "empty.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_anonymous_redirect(client):
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2"), "x.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_upload_corrupt_excel(app, logged_in_user):
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (io.BytesIO(b"this is not really excel"), "broken.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert b"Traceback" not in resp.data  # no stack traces leaked to users
    assert b"Could not parse" in resp.data


# ---------------------------------------------------------------- schema/preview
def test_dataset_preview_handles_nan():
    df = pd.DataFrame({"a": [1.0, None], "b": ["x", "y"]})
    table = dataset_preview(df, 5)
    assert table[0] == ["a", "b"]
    assert table[1][1] == "x"
    assert table[2][0] is None


def test_dataframe_schema_kinds():
    df = pd.DataFrame({
        "num": [1, 2, 3],
        "text": ["a", "b", "c"],
    })
    schema = dataframe_schema(df)
    kinds = {entry["name"]: entry["kind"] for entry in schema}
    assert kinds["num"] == "numeric"
    assert kinds["text"] in {"categorical", "text"}
