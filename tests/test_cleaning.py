"""Cleaning engine registry and operation behaviour tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from datasure.cleaning.engine import (
    REGISTRY,
    apply_operation,
    suggest_operations,
    validate_params,
)
from datasure.profiling.profile import profile_dataset


SUGGEST_DF = pd.DataFrame({
    "num": [1.0, 2.0, None],
    "cat": [" x", "x ", None],
    "const": [5, 5, 5],
    "empty": [None, None, None],
})


# ------------------------------------------------------------------ validate_params
def test_validate_params_rejects_unknown_operation():
    with pytest.raises(ValueError, match="Unknown cleaning operation"):
        validate_params("delete_everything", {})


def test_validate_params_missing_required_column():
    with pytest.raises(ValueError, match="required"):
        validate_params("drop_columns", {})


def test_validate_params_unknown_column_name():
    with pytest.raises(ValueError, match="Unknown column"):
        apply_operation(pd.DataFrame({"a": [1]}), "drop_columns", {"columns": ["ghost"]})


def test_validate_params_bad_choice():
    with pytest.raises(ValueError, match="must be one of"):
        validate_params("drop_duplicate_rows", {"keep": "middle"})


def test_validate_params_bad_number():
    with pytest.raises(ValueError, match="must be a number"):
        validate_params("clip_outliers_iqr", {"columns": ["a"], "factor": "fast"})


def test_validate_params_string_columns_split():
    validated = validate_params("drop_columns", {"columns": "a, b"})
    assert validated["columns"] == ["a", "b"]


# ------------------------------------------------------------------ operations
def test_drop_duplicate_rows(app):
    df = pd.DataFrame({"a": [1, 1, 2], "b": [1, 1, 3]})
    result = apply_operation(df, "drop_duplicate_rows", {"keep": "first"})
    assert len(result) == 2


def test_drop_missing_rows_any(app):
    df = pd.DataFrame({"a": [1, None, 3], "b": [1, 2, 3]})
    result = apply_operation(df, "drop_missing_rows", {"columns": ["a"], "how": "any"})
    assert len(result) == 2


def test_drop_columns(app):
    df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
    result = apply_operation(df, "drop_columns", {"columns": ["a", "c"]})
    assert list(result.columns) == ["b"]


def test_fill_numeric_strategies(app):
    df = pd.DataFrame({"a": [1.0, None, 3.0]})
    median = apply_operation(df, "fill_numeric", {"columns": ["a"], "strategy": "median"})
    zero = apply_operation(df, "fill_numeric", {"columns": ["a"], "strategy": "zero"})
    mean = apply_operation(df, "fill_numeric", {"columns": ["a"], "strategy": "mean"})
    assert median["a"].isna().sum() == 0
    assert float(median["a"].iloc[1]) == pytest.approx(2.0)
    assert float(zero["a"].iloc[1]) == 0.0
    assert float(mean["a"].iloc[1]) == pytest.approx(2.0)


def test_fill_categorical(app):
    df = pd.DataFrame({"c": ["x", None, "x"]})
    mode = apply_operation(df, "fill_categorical", {"columns": ["c"], "strategy": "mode"})
    assert (mode["c"] == "x").all()


def test_standardize_strings(app):
    df = pd.DataFrame({"s": [" x", "y ", " z", "w"]})
    result = apply_operation(df, "standardize_strings", {"columns": ["s"]})
    assert not (result["s"] != result["s"].str.strip()).any()


def test_clip_outliers_iqr(app):
    df = pd.DataFrame({"v": [1, 2, 3, 4, 5, 1000]})
    result = apply_operation(df, "clip_outliers_iqr", {"columns": ["v"], "factor": 1.5})
    assert float(result["v"].max()) < 100.0


def test_drop_empty_columns(app):
    df = pd.DataFrame({"a": [1, 2], "empty": [None, None]})
    result = apply_operation(df, "drop_empty_columns", {})
    assert list(result.columns) == ["a"]


def test_drop_constant_columns(app):
    df = pd.DataFrame({"a": [1, 2], "const": [1, 1]})
    result = apply_operation(df, "drop_constant_columns", {})
    assert list(result.columns) == ["a"]


def test_convert_to_numeric(app):
    df = pd.DataFrame({"t": ["1", "2", "oops"]})
    result = apply_operation(df, "convert_to_numeric", {"columns": ["t"]})
    assert result["t"].isna().sum() == 1


def test_operations_registry_is_complete():
    for name, entry in REGISTRY.items():
        assert callable(entry["apply"])
        assert entry["label"] and entry["description"]
        for spec in entry["params"]:
            assert spec["type"] in {"choice", "number", "multi_column", "text"}
            assert spec["name"]


def test_all_operations_are_json_metadata_safe():
    import json

    for name, entry in REGISTRY.items():
        json.dumps({"name": name, "params": entry["params"]})


# ------------------------------------------------------------------ suggest_operations
def test_suggestions_generated_for_problems():
    suggestions = suggest_operations(SUGGEST_DF, profile_dataset(SUGGEST_DF))
    operations = {s["operation"] for s in suggestions}
    assert "fill_numeric" in operations
    assert "fill_categorical" in operations
    assert "standardize_strings" in operations
    assert "drop_empty_columns" in operations


def test_no_suggestions_for_clean_data():
    clean = pd.DataFrame({"a": [1, 2, 3, 4], "b": ["x", "y", "x", "y"]})
    suggestions = suggest_operations(clean, profile_dataset(clean))
    assert suggestions == []
