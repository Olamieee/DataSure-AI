"""Cleaning operation registry and engine.

Rules:
- Operations are deterministic, parameter-validated transforms listed in REGISTRY.
- The engine NEVER mutates the stored original file; cleaned files get new names.
- Every run is recorded in CleaningOperation with before/after shapes.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Individual operations
# ---------------------------------------------------------------------------
def op_drop_duplicate_rows(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    return df.drop_duplicates(keep=params.get("keep", "first"))


def op_drop_missing_rows(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    columns = _columns(df, params)
    how = params.get("how", "any")
    if how not in ("any", "all"):
        raise ValueError("'how' must be 'any' or 'all'.")
    return df.dropna(subset=columns or None, how=how)


def op_drop_columns(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    columns = params.get("columns") or []
    unknown = [c for c in columns if c not in df.columns]
    if unknown:
        raise ValueError(f"Unknown column(s): {', '.join(unknown)}")
    return df.drop(columns=columns)


def op_fill_numeric(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    columns = _columns(df, params)
    strategy = params.get("strategy", "median")
    if strategy not in ("median", "mean", "zero"):
        raise ValueError("strategy must be 'median', 'mean' or 'zero'.")
    result = df.copy()
    for column in columns:
        if strategy == "median":
            result[column] = result[column].fillna(result[column].median())
        elif strategy == "mean":
            result[column] = result[column].fillna(result[column].mean())
        else:
            result[column] = result[column].fillna(0)
    return result


def op_fill_categorical(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    columns = _columns(df, params)
    strategy = params.get("strategy", "mode")
    if strategy not in ("mode", "missing", "static"):
        raise ValueError("strategy must be 'mode', 'missing' or 'static'.")
    result = df.copy()
    for column in columns:
        if strategy == "mode":
            mode = result[column].mode(dropna=True)
            fill_value = mode.iloc[0] if not mode.empty else "missing"
            result[column] = result[column].fillna(fill_value)
        else:
            result[column] = result[column].fillna("missing" if strategy == "missing" else
                                                   params.get("fill_value", ""))
    return result


def op_standardize_string_values(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    columns = _columns(df, params)
    result = df.copy()
    for column in columns:
        if result[column].map(type).eq(str).any():
            result[column] = result[column].str.strip()
    return result


def op_clip_outliers_iqr(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    columns = _columns(df, params)
    factor = float(params.get("factor", 1.5))
    if factor <= 0:
        raise ValueError("factor must be a positive number.")
    result = df.copy()
    for column in columns:
        series = pd.to_numeric(result[column], errors="coerce")
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower, upper = q1 - factor * iqr, q3 + factor * iqr
        result[column] = result[column].clip(lower=lower, upper=upper)
    return result


def op_drop_empty_columns(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    return df.dropna(axis=1, how="all")


def op_drop_constant_columns(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    constant = [column for column in df.columns if df[column].nunique(dropna=True) <= 1]
    return df.drop(columns=constant)


def op_convert_numeric(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    columns = params.get("columns") or []
    unknown = [c for c in columns if c not in df.columns]
    if unknown:
        raise ValueError(f"Unknown column(s): {', '.join(unknown)}")
    result = df.copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
REGISTRY: dict[str, dict[str, Any]] = {
    "drop_duplicate_rows": {
        "label": "Remove duplicate rows",
        "params": [
            {"name": "keep", "type": "choice", "choices": ["first", "last"],
             "default": "first", "required": False},
        ],
        "apply": op_drop_duplicate_rows,
        "description": "Deletes repeat rows, keeping the first (or last) occurrence.",
    },
    "drop_missing_rows": {
        "label": "Drop rows with missing values",
        "params": [
            {"name": "columns", "type": "multi_column", "required": False},
            {"name": "how", "type": "choice", "choices": ["any", "all"], "default": "any",
             "required": False},
        ],
        "apply": op_drop_missing_rows,
        "description": "Removes rows where any/all selected column(s) are missing.",
    },
    "drop_columns": {
        "label": "Drop columns",
        "params": [{"name": "columns", "type": "multi_column", "required": True}],
        "apply": op_drop_columns,
        "description": "Removes selected columns entirely (destructive; keep originals).",
    },
    "fill_numeric": {
        "label": "Fill missing numeric values",
        "params": [
            {"name": "columns", "type": "multi_column", "required": True},
            {"name": "strategy", "type": "choice", "choices": ["median", "mean", "zero"],
             "default": "median", "required": False},
        ],
        "apply": op_fill_numeric,
        "description": "Imputes missing numeric cells with column median, mean or zero.",
    },
    "fill_categorical": {
        "label": "Fill missing categorical values",
        "params": [
            {"name": "columns", "type": "multi_column", "required": True},
            {"name": "strategy", "type": "choice", "choices": ["mode", "missing", "static"],
             "default": "mode", "required": False},
        ],
        "apply": op_fill_categorical,
        "description": "Imputes missing text cells with the mode, the token 'missing', or a custom value.",
    },
    "standardize_strings": {
        "label": "Trim whitespace in text columns",
        "params": [{"name": "columns", "type": "multi_column", "required": True}],
        "apply": op_standardize_string_values,
        "description": "Removes leading/trailing whitespace from text columns.",
    },
    "clip_outliers_iqr": {
        "label": "Clip numeric outliers (IQR)",
        "params": [
            {"name": "columns", "type": "multi_column", "required": True},
            {"name": "factor", "type": "number", "default": 1.5, "required": False},
        ],
        "apply": op_clip_outliers_iqr,
        "description": "Limits extreme numeric values to Tukey 1.5*IQR bracket.",
    },
    "drop_empty_columns": {
        "label": "Drop completely empty columns",
        "params": [],
        "apply": op_drop_empty_columns,
        "description": "Removes columns with no values at all.",
    },
    "drop_constant_columns": {
        "label": "Drop constant columns",
        "params": [],
        "apply": op_drop_constant_columns,
        "description": "Removes columns whose value never changes.",
    },
    "convert_to_numeric": {
        "label": "Convert text column to numeric",
        "params": [{"name": "columns", "type": "multi_column", "required": True}],
        "apply": op_convert_numeric,
        "description": "Coerces text columns to numbers; non-parsable values become missing.",
    },
}


def _columns(df: pd.DataFrame, params: dict) -> list[str]:
    columns = params.get("columns") or []
    unknown = [c for c in columns if c not in df.columns]
    if unknown:
        raise ValueError(f"Unknown column(s): {', '.join(unknown)}")
    return list(columns)


def validate_params(operation: str, params: dict) -> dict:
    """Validate argument values for an operation against its registry entry."""
    entry = REGISTRY.get(operation)
    if entry is None:
        raise ValueError(f"Unknown cleaning operation '{operation}'.")
    provided = params or {}
    validated: dict = {}
    for spec in entry["params"]:
        name = spec["name"]
        if name in provided and provided[name] not in (None, ""):
            value = provided[name]
        elif spec.get("required"):
            raise ValueError(f"Parameter '{name}' is required for {operation}.")
        else:
            value = spec.get("default")
        if value is None:
            continue
        if spec["type"] == "choice":
            if value not in spec["choices"]:
                raise ValueError(f"'{name}' must be one of: {', '.join(spec['choices'])}.")
        elif spec["type"] == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"'{name}' must be a number.")
        elif spec["type"] == "multi_column":
            if isinstance(value, str):
                value = [item.strip() for item in value.split(",") if item.strip()]
            if not isinstance(value, list) or not value:
                raise ValueError(f"'{name}' must be a non-empty list of column names.")
        validated[name] = value
    return validated


def apply_operation(df: pd.DataFrame, operation: str, params: dict) -> pd.DataFrame:
    """Apply one cleaning operation. Raises ValueError on bad input."""
    validated = validate_params(operation, params)
    return REGISTRY[operation]["apply"](df, validated)


def suggest_operations(df: pd.DataFrame, profile: dict) -> list[dict]:
    """Deterministic, issue-driven suggestions (operation + ready-to-use params)."""
    suggestions: list[dict] = []
    duplicates = profile["duplicates"]
    missingness = profile["missingness"]
    cardinality = profile["cardinality"]

    if duplicates["duplicate_rows"] > 0:
        suggestions.append(
            {"operation": "drop_duplicate_rows", "params": {"keep": "first"},
             "reason": f"{duplicates['duplicate_rows']:,} duplicate row(s) detected."}
        )
    for entry in profile["columns"]:
        if entry["kind"] == "numeric" and entry.get("missing", 0) > 0:
            suggestions.append(
                {"operation": "fill_numeric",
                 "params": {"columns": [entry["name"]], "strategy": "median"},
                 "reason": f"{entry['name']}: {entry['missing']:,} missing numeric cells."}
            )
        elif entry["kind"] in {"categorical", "text", "boolean"} and entry.get("missing", 0) > 0:
            suggestions.append(
                {"operation": "fill_categorical",
                 "params": {"columns": [entry["name"]], "strategy": "missing"},
                 "reason": f"{entry['name']}: {entry['missing']:,} missing text cells."}
            )
        if entry.get("whitespace_issue_count", 0) > 0:
            suggestions.append(
                {"operation": "standardize_strings", "params": {"columns": [entry["name"]]},
                 "reason": f"{entry['name']}: whitespace to trim."}
            )
        if entry["non_null"] == 0:
            suggestions.append(
                {"operation": "drop_empty_columns", "params": {},
                 "reason": f"{entry['name']} has no data."}
            )
    numeric_as_text = profile.get("schema", {}).get("suspicious_type_storage", [])
    for entry in numeric_as_text:
        suggestions.append(
            {"operation": "convert_to_numeric", "params": {"columns": [entry["column"]]},
             "reason": f"{entry['column']} is numeric but stored as text."}
        )
    if missingness["rows_missing_all"] > 0:
        suggestions.append(
            {"operation": "drop_missing_rows", "params": {"how": "all"},
             "reason": f"{missingness['rows_missing_all']:,} fully empty rows."}
        )

    # de-dup suggestions by (operation, params)
    seen: set = set()
    unique_suggestions = []
    for suggestion in suggestions:
        key = (suggestion["operation"], json.dumps(suggestion["params"], sort_keys=True))
        if key not in seen:
            seen.add(key)
            unique_suggestions.append(suggestion)
    return unique_suggestions
