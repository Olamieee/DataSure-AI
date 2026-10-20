"""Large-dataset handling tests: streamed limit scan and bounded parsing."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from datasure.datasets import ingest
from datasure.datasets.ingest import DatasetParseError, load_dataframe


@pytest.fixture()
def force_stream_scan(monkeypatch):
    """Force load_dataframe through the incremental scan path."""
    monkeypatch.setattr(ingest, "CHUNKED_SCAN_THRESHOLD_BYTES", 1)


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False)


def test_oversized_rows_rejected_during_stream_scan(tmp_path, force_stream_scan):
    frame = pd.DataFrame({"a": range(1500), "b": ["x"] * 1500})
    path = tmp_path / "big.csv"
    _write_csv(path, frame)
    with pytest.raises(DatasetParseError, match="limit"):
        load_dataframe(path, ".csv", max_rows=1000, max_columns=400)


def test_quoted_newlines_counted_correctly(tmp_path, force_stream_scan):
    path = tmp_path / "quoted.csv"
    path.write_bytes(b"a,b\n1,\"line one\nline two\"\n2,plain\n")
    df = load_dataframe(path, ".csv", max_rows=2, max_columns=400)
    assert list(df["a"].astype(str).tolist()) == ["1", "2"]


def test_column_limit_enforced_in_scan(tmp_path, force_stream_scan):
    frame = pd.DataFrame({f"col_{i}": [1, 2, 3] for i in range(500)})
    path = tmp_path / "cols.csv"
    _write_csv(path, frame)
    with pytest.raises(DatasetParseError, match="columns"):
        load_dataframe(path, ".csv", max_rows=1000, max_columns=400)


def test_large_file_within_limits_parses_fully(tmp_path, force_stream_scan):
    frame = pd.DataFrame({"a": range(1200), "b": [f"row-{i}" for i in range(1200)]})
    path = tmp_path / "within.csv"
    _write_csv(path, frame)
    df = load_dataframe(path, ".csv", max_rows=5000, max_columns=400)
    assert len(df) == 1200
    assert list(df.columns) == ["a", "b"]


def test_scan_failure_falls_back_to_full_loader(tmp_path, force_stream_scan, monkeypatch):
    """If the advisory scan itself errors, the full loader still handles the file."""
    import pandas as pd

    path = tmp_path / "latin.csv"
    path.write_bytes(b"a,b\ncaf\xe9,x\nna\xefve,y\n")  # latin-1 bytes
    df = load_dataframe(path, ".csv", max_rows=1000, max_columns=400)
    assert len(df) == 2


def test_web_upload_oversized_rows_rejected_with_message(app, logged_in_user, monkeypatch):
    monkeypatch.setattr(ingest, "CHUNKED_SCAN_THRESHOLD_BYTES", 1)
    rows = b"1,x\n" * (500_001 // 1)
    buffering = io.BytesIO(b"a,b\n" + rows)
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (buffering, "toobig.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    page = resp.data.decode("utf-8")
    assert "exceeding the platform limit" in page


def test_web_upload_healthy_large_file_succeeds(app, logged_in_user, monkeypatch):
    monkeypatch.setattr(ingest, "CHUNKED_SCAN_THRESHOLD_BYTES", 1)
    lines = b"a,b\n" + b"".join(f"{i},row{i}\n".encode() for i in range(600))
    resp = logged_in_user["client"].post(
        "/datasets/upload",
        data={"file": (io.BytesIO(lines), "fine.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
