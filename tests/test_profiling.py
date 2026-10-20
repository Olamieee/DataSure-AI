"""Tests for the profiling engine, outlier detection and leakage analysis."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from datasure.profiling.leakage import analyse_target_leakage
from datasure.profiling.outliers import iqr_bounds, iqr_outliers, zscore_outliers
from datasure.profiling.profile import profile_dataset


def frame_with(**columns) -> pd.DataFrame:
    return pd.DataFrame(columns)


# ------------------------------------------------------------------ outliers
def test_iqr_outliers_counts_extremes():
    data = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 100])
    assert iqr_outliers(data, 1.5) == 1
    assert iqr_outliers(pd.Series(range(10)), 1.5) == 0


def test_iqr_bounds_degenerate_series():
    assert iqr_bounds(pd.Series([2, 2, 2, 2, 2]), 1.5) == (2.0, 2.0)
    assert iqr_bounds(pd.Series([]), 1.5) is None


def test_zscore_outliers_length_guard():
    short = pd.Series([1.0, 2.0, 3.0])
    assert zscore_outliers(short, 3.0) == 0


def test_zscore_outliers_zero_std_is_safe():
    assert zscore_outliers(pd.Series([7, 7, 7, 7, 7, 7, 7, 7, 7]), 3.0) == 0


# ------------------------------------------------------------------ missingness
def test_missingness_counts(app, tmp_path):
    df = frame_with(
        a=[1, None, 3],
        b=["x", "y", "z"],
        c=[None, None, 3.0],
    )
    profile = profile_dataset(df)
    missing = profile["missingness"]
    assert missing["total_cells"] == 9
    assert missing["missing_cells"] == 3
    assert missing["rows_missing_all"] == 0
    columns_by_name = {entry["column"]: entry for entry in missing["columns_with_missing"]}
    assert columns_by_name["a"]["missing"] == 1
    assert columns_by_name["c"]["missing"] == 2
    assert columns_by_name["c"]["pct"] == pytest.approx(66.67, rel=1e-3)


def test_rows_entirely_missing(app):
    df = frame_with(a=[1, 2, None], b=[3, 4, None])
    profile = profile_dataset(df)
    assert profile["missingness"]["rows_missing_all"] == 1


# ------------------------------------------------------------------ duplicates
def test_duplicate_rows_detected():
    df = frame_with(a=[1, 2, 1], b=["x", "y", "x"])
    profile = profile_dataset(df)
    assert profile["duplicates"]["duplicate_rows"] == 2
    assert profile["duplicates"]["duplicate_row_pct"] == pytest.approx(66.67, rel=1e-2)


def test_duplicate_columns_detected():
    df = frame_with(a=[1, 2, 3, 4], copy_of_a=[1, 2, 3, 4], other=[9, 8, 7, 6])
    profile = profile_dataset(df)
    assert "copy_of_a" in profile["duplicates"]["duplicate_columns"]


# ------------------------------------------------------------------ column profiles
def test_constant_column_flagged():
    df = frame_with(a=[1, 2, 3], const=["yes", "yes", "yes"])
    profile = profile_dataset(df)
    assert profile["cardinality"]["constant"] == ["const"]


def test_high_cardinality_identifier_flagged():
    df = frame_with(
        id=[f"user_{i}" for i in range(100)],
        cat=[("a", "b")[i % 2] for i in range(100)],
    )
    profile = profile_dataset(df)
    assert profile["cardinality"]["high_cardinality"] == ["id"]
    assert profile["columns"][0]["is_identifier"] is True


def test_class_imbalance_ratio_recorded():
    df = frame_with(label=["a"] * 90 + ["b"] * 10)
    profile = profile_dataset(df)
    entry = profile["columns"][0]
    assert entry["class_imbalance_ratio"] == pytest.approx(1 / 9, rel=1e-3)


def test_numeric_stats_rounded():
    df = frame_with(x=[1, 2, 3, 4])
    entry = profile_dataset(df)["columns"][0]
    assert entry["stats"]["mean"] == 2.5
    assert entry["stats"]["min"] == 1.0
    assert entry["stats"]["max"] == 4.0


def test_json_representable(app):
    import json

    df = frame_with(
        num=[1.5, np.nan, 3.0],
        text=["x", None, "z"],
        big=[10**12, 10**12 + 1, 10**12 + 2],
    )
    profile = profile_dataset(df)
    assert json.dumps(profile)  # no circular refs or numpy-only scalars


def test_mixed_python_types_in_object_column():
    df = frame_with(mix=["a", 5, "b", {"k": 1}])
    profile = profile_dataset(df)
    assert profile["columns"][0]["python_types"]["str"]
    assert profile["columns"][0]["python_types"]["dict"]


# ------------------------------------------------------------------ leakage
def test_regression_leakage_detected():
    rng = np.random.default_rng(7)
    df = pd.DataFrame({
        "target": rng.normal(size=200),
        "repeats": 0.0,
    })
    df["repeats"] = df["target"] * 1.0 + 1e-12  # numeric copy of target
    result = analyse_target_leakage(df, "target")
    assert result["target"]["kind"] == "regression"
    assert any(w["kind"] == "target_leakage_suspected" for w in result["warnings"])


def test_classification_leakage_detected_by_agreement():
    df = pd.DataFrame({
        "target": ["yes", "no", "yes", "no"] * 25,
        "echo": ["yes", "no", "yes", "no"] * 25,  # identical to target
        "noise": ["a", "b", "c", "d"] * 25,
    })
    result = analyse_target_leakage(df, "target")
    assert any(w["columns"] == ["echo", "target"] for w in result["warnings"])


def test_no_target_no_leakage_findings():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [1, 0, 1]})
    result = analyse_target_leakage(df, None)
    assert result == {"target": None, "warnings": [], "info": [],
                      "correlation_table": []}


def test_unknown_target_ignored():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [1, 0, 1]})
    result = analyse_target_leakage(df, "nonexistent")
    assert result["target"] is None
    assert result["warnings"] == []
