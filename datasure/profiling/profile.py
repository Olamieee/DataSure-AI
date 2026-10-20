"""Dataset profiling engine.

`profile_dataset(df)` produces a fully JSON-serialisable analysis covering
missingness, duplicates, schema/type issues, descriptive statistics, cardinality,
outliers and formatting anomalies. Every finding is a *measurement*, not a
judgement - downstream modules (issues, scoring) turn measurements into advice.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .outliers import iqr_bounds, iqr_outliers, zscore_outliers

# Thresholds (kept module-level so docs and tests can reference them).
HIGH_CARDINALITY_RATIO = 0.95     # unique/non-null rows ratio flagged as suspicious
LOW_CARDINALITY_MAX = 20          # categories considered "low cardinality"
SUSPICIOUS_SKEW = 3.0
STRING_DATE_PATTERN_MIN = 0.60    # fraction of cells that must look like dates


class ProfilingTimeout(RuntimeError):
    """Raised when profiling exceeds its wall-time budget."""


def profile_dataset(df: pd.DataFrame, time_budget_seconds: float | None = None) -> dict:
    """Build a complete JSON-ready profile snapshot of `df`.

    Args:
        time_budget_seconds: optional hard wall-time budget. Profiling checks
            the elapsed time at every phase boundary and aborts with
            ProfilingTimeout when exceeded, so a pathological dataset cannot
            monopolise a worker. `None` disables the budget entirely.
    """
    started = time.perf_counter()

    def _check_budget(phase: str) -> None:
        if time_budget_seconds is None:
            return
        elapsed = time.perf_counter() - started
        if elapsed > time_budget_seconds:
            raise ProfilingTimeout(
                f"Analysis stopped after {elapsed:.1f}s exceeded the "
                f"{time_budget_seconds:.1f}s budget during {phase}.")

    rows, columns = map(int, df.shape)
    profile: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "overview": {
            "rows": rows,
            "columns": columns,
            "cells": rows * columns,
            "memory_bytes": int(df.memory_usage(deep=True).sum()),
        },
        "columns": [],
        "missingness": None,
        "duplicates": None,
        "schema": None,
        "cardinality": None,
    }
    for column in df.columns:
        profile["columns"].append(analyse_column(column, df[column]))
        _check_budget("column profiling")
    profile["missingness"] = analyse_missingness(df)
    _check_budget("missingness analysis")
    profile["duplicates"] = analyse_duplicates(df)
    _check_budget("duplicate analysis")
    profile["schema"] = analyse_schema(df)
    _check_budget("schema analysis")
    profile["cardinality"] = analyse_cardinality(df)
    _check_budget("cardinality analysis")
    return profile


# ---------------------------------------------------------------------------
# Column level analysis
# ---------------------------------------------------------------------------
def analyse_column(name: str, series: pd.Series) -> dict:
    non_null = int(series.notna().sum())
    missing = int(series.isna().sum())
    try:
        unique = int(series.nunique(dropna=True))
    except TypeError:  # unhashable payloads (dict/list cells) - count by repr instead
        unique = int(series.dropna().astype(str).nunique())
    analysis: dict = {
        "name": str(name),
        "pandas_dtype": str(series.dtype),
        "kind": classify_kind(series),
        "non_null": non_null,
        "missing": missing,
        "missing_pct": round(100.0 * missing / len(series), 2) if len(series) else 0.0,
        "unique": unique,
        "constant": unique <= 1 and non_null > 0,
        "is_identifier": bool(
            unique > 0 and non_null > 4 and unique == non_null and non_null == len(series)
        ),
    }

    if analysis["kind"] == "numeric":
        analysis.update(_numeric_analysis(series))
    elif analysis["kind"] in {"categorical", "boolean", "datetime"}:
        analysis.update(_categorical_analysis(series))
    if analysis["kind"] in {"mixed", "text"}:
        analysis.update(mixed_analysis(series))
    return analysis


def classify_kind(series: pd.Series) -> str:
    """Infer a practical kind for a column: numeric/boolean/datetime/text/categorical/mixed."""
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    non_null = series.dropna()
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return "mixed"
    if non_null.empty:
        return "categorical"
    python_types = non_null.map(type)
    typed_counts = python_types.value_counts()
    # A column that genuinely mixes incompatible python types (e.g. str + dict):
    # dominant type share below 90% -> treat as mixed rather than text.
    if len(typed_counts) > 1 and typed_counts.iloc[0] / typed_counts.sum() < 0.9:
        return "mixed"
    string_values = non_null.astype(str)
    coerced = pd.to_numeric(string_values, errors="coerce")
    if coerced.notna().mean() >= 0.9:
        return "numeric"
    if looks_like_dates(string_values):
        return "datetime"
    if int(string_values.nunique()) <= LOW_CARDINALITY_MAX * 10:
        return "categorical"
    return "text"


def looks_like_dates(strings: pd.Series) -> bool:
    sample = strings.head(200)
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed", dayfirst=False)
    ratio = float(parsed.notna().mean()) if len(sample) else 0.0
    return ratio >= STRING_DATE_PATTERN_MIN


def _numeric_analysis(series: pd.Series) -> dict:
    """Descriptive statistics plus IQR/Z-score outlier counts for a numeric column."""
    clean = pd.to_numeric(series.dropna(), errors="coerce")
    clean = clean[clean.notna()].astype(float)
    analysis: dict = {"invalid_non_numeric": 0}
    if clean.empty:
        analysis["stats"] = None
        analysis["skew"] = None
        analysis["outliers"] = {"iqr_count": 0, "iqr_lower": None, "iqr_upper": None,
                                "zscore_count": 0}
        return analysis

    bounds = iqr_bounds(clean)
    analysis["stats"] = {
        "min": _safe_float(clean.min()),
        "max": _safe_float(clean.max()),
        "mean": _safe_float(clean.mean()),
        "std": _safe_float(clean.std(ddof=1)),
        "q1": _safe_float(clean.quantile(0.25)),
        "median": _safe_float(clean.median()),
        "q3": _safe_float(clean.quantile(0.75)),
    }
    analysis["skew"] = _safe_float(clean.skew())
    analysis["outliers"] = {
        "iqr_count": iqr_outliers(clean),
        "iqr_lower": bounds[0] if bounds else None,
        "iqr_upper": bounds[1] if bounds else None,
        "zscore_count": zscore_outliers(clean),
    }
    return analysis


def _categorical_analysis(series: pd.Series) -> dict:
    clean = series.dropna()
    counts = clean.astype(str).value_counts()
    top = counts.head(10)
    top_records = [
        {"value": str(value)[:60], "count": int(count), "pct": round(100 * count / max(len(series), 1), 2)}
        for value, count in top.items()
    ]
    string_mask = clean.map(type).eq(str)
    if string_mask.any():
        as_str = clean[string_mask].astype(str)
        whitespace_issues = int((as_str != as_str.str.strip()).sum())
    else:
        whitespace_issues = 0
    analysis = {
        "top_values": top_records[:10],
        "category_count": int(clean.astype(str).nunique()),
        "class_imbalance_ratio": (
            round(float(top.min() / max(top.max(), 1)), 3) if len(top) >= 2 else None
        ),
        "whitespace_issue_count": whitespace_issues,
    }
    return analysis


def mixed_analysis(series: pd.Series) -> dict:
    clean = series.dropna()
    types = clean.map(type).value_counts().to_dict()
    counts = {type_name.__name__: int(count) for type_name, count in types.items()}
    advice: dict = {"python_types": counts}
    if counts.get("str"):
        as_str = clean[clean.map(type).eq(str)].astype(str)
        advice["blank_string_count"] = int((as_str.str.strip() == "").sum())
        advice["del_after_strip"] = int((as_str != as_str.str.strip()).sum())
    return advice


def _safe_float(value) -> float | None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Dataset level analysis
# ---------------------------------------------------------------------------
def analyse_missingness(df: pd.DataFrame) -> dict:
    missing_cells = int(df.isna().sum().sum())
    total_cells = int(df.shape[0] * df.shape[1])
    per_column = [
        {"column": str(column), "missing": int(df[column].isna().sum()),
         "pct": round(100.0 * df[column].isna().sum() / max(len(df), 1), 2)}
        for column in df.columns
        if df[column].isna().any()
    ]
    per_column.sort(key=lambda entry: entry["pct"], reverse=True)
    rows_missing_all = int(df.isna().all(axis=1).sum())
    rows_fully_complete = int(df.notna().all(axis=1).sum())
    return {
        "total_cells": total_cells,
        "missing_cells": missing_cells,
        "missing_pct": round(100.0 * missing_cells / max(total_cells, 1), 2),
        "columns_with_missing": per_column,
        "rows_missing_all": rows_missing_all,
        "rows_fully_complete": rows_fully_complete,
    }


def analyse_duplicates(df: pd.DataFrame) -> dict:
    """Count duplicate rows (in any form) and columns whose values are identical."""
    try:
        duplicate_rows = int(df.duplicated(keep=False).sum())
    except TypeError:  # e.g. dict/list payload columns that are not hashable
        duplicate_rows = 0

    duplicate_columns: list[str] = []
    try:
        # Compare value representations as strings: robust to NaN placement and dtype.
        representations = {
            column: df[column].fillna("<NA>").map(str) for column in df.columns
        }
        constant_columns = {
            column for column, repr_series in representations.items()
            if repr_series.nunique() <= 1
        }
        columns = list(df.columns)
        for i, col_a in enumerate(columns):
            if col_a in duplicate_columns or col_a in constant_columns:
                continue
            for col_b in columns[i + 1:]:
                if col_b in duplicate_columns or col_b in constant_columns:
                    continue
                if representations[col_a].equals(representations[col_b]):
                    duplicate_columns.append(str(col_b))
    except Exception:
        # Column-level duplication stays advisory; never fail a profile here.
        pass
    return {
        "duplicate_rows": duplicate_rows,
        "duplicate_row_pct": round(100.0 * duplicate_rows / max(len(df), 1), 2),
        "duplicate_columns": duplicate_columns,
    }


def analyse_schema(df: pd.DataFrame) -> dict:
    suspicious: list[dict] = []
    for column in df.columns:
        if column in (df.select_dtypes(include=[np.number]).columns):
            continue
        object_series = df[column].dropna()
        if object_series.empty:
            continue
        numeric_coerce = pd.to_numeric(object_series, errors="coerce")
        looks_numeric = numeric_coerce.notna()
        if pd.api.types.is_numeric_dtype(df[column]):
            continue
        if looks_numeric.mean() >= 0.80 and object_series.astype(str).nunique() > 4:
            # Stored as text although almost every value parses as a number.
            suspicious.append(
                {"column": str(column), "issue": "numeric_storage",
                 "affected_pct": round(100.0 * looks_numeric.mean(), 2)}
            )
    return {"suspicious_type_storage": suspicious}


def analyse_cardinality(df: pd.DataFrame) -> dict:
    high: list[str] = []
    low: list[str] = []
    constant: list[str] = []
    for column in df.columns:
        non_null = int(df[column].notna().sum())
        if non_null == 0:
            constant.append(str(column))
            continue
        unique = _safe_nunique(df[column])
        ratio = unique / non_null
        if unique <= 1:
            constant.append(str(column))
        elif ratio >= HIGH_CARDINALITY_RATIO and unique > LOW_CARDINALITY_MAX:
            high.append(str(column))
        elif unique <= LOW_CARDINALITY_MAX:
            low.append(str(column))
    return {"high_cardinality": high, "low_cardinality": low, "constant": constant}


def _safe_nunique(series: pd.Series) -> int:
    """nunique that survives unhashable cell payloads (dicts, lists)."""
    try:
        return int(series.dropna().astype(str).nunique())
    except Exception:
        return 0
