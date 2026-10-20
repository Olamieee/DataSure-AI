"""Target-leakage and suspicious feature-relationship detection.

These detectors produce **warnings only**: they highlight patterns that
frequently indicate train/test leakage or problematic feature construction,
and cannot confirm leakage without knowledge of the analysis pipeline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NUMERIC_CORRELATION_WARNING = 0.95   # near-perfect numeric agreement
HIGH_CORRELATION_INFO = 0.85         # redundant but not necessarily leakage


def _infer_target_kind(target: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(target) and target.nunique(dropna=True) > 20:
        return "regression"
    return "classification"


def numeric_correlations(df: pd.DataFrame) -> tuple[dict[str, list[str]], list[tuple[str, str, float]]]:
    """Return (strong_pairs, all_pairs) for numeric columns."""
    numeric = df.select_dtypes(include=[np.number])
    if numeric.shape[1] < 2 or numeric.shape[0] < 3:
        return {}, []
    corr = numeric.corr(min_periods=4)
    strong: dict[str, list[str]] = {}
    pairs: list[tuple[str, str, float]] = []
    columns = list(corr.columns)
    for i, col_a in enumerate(columns):
        for col_b in columns[i + 1:]:
            value = corr.iloc[i][col_b]
            if pd.isna(value):
                continue
            pairs.append((col_a, col_b, round(float(value), 3)))
            if abs(value) >= NUMERIC_CORRELATION_WARNING:
                strong.setdefault(col_a, []).append(col_b)
                strong.setdefault(col_b, []).append(col_a)
    return strong, pairs


def analyse_target_leakage(df: pd.DataFrame, target_column: str | None) -> dict:
    """Assess features for potential leakage against `target_column`.

    Only warnings with clear explanations are produced; never hard statements.
    """
    result: dict = {"target": None, "warnings": [], "info": [], "correlation_table": []}
    if not target_column or target_column not in df.columns or df.shape[1] < 2:
        return result
    target = df[target_column]
    if target.isna().all():
        return result

    kind = _infer_target_kind(target)
    result["target"] = {"column": target_column, "kind": kind}

    if kind == "regression":
        selector = df.select_dtypes(include=[np.number])
        if target_column not in selector.columns or selector.shape[1] < 2:
            return result
        corr = selector.corr(min_periods=4)[target_column].drop(target_column)
        for feature, value in corr.items():
            if pd.isna(value):
                continue
            result["correlation_table"].append(
                {"feature": feature, "correlation": round(float(value), 3)}
            )
            if abs(value) >= NUMERIC_CORRELATION_WARNING:
                result["warnings"].append(
                    {
                        "kind": "target_leakage_suspected",
                        "columns": [feature, target_column],
                        "correlation": round(float(value), 3),
                    }
                )
            elif abs(value) >= HIGH_CORRELATION_INFO:
                result["info"].append(
                    {"kind": "feature_correlation", "columns": [feature, target_column],
                     "correlation": round(float(value), 3)}
                )
        return result

    # Classification target: look for features that essentially repeat it.
    encoded = target.astype(str)
    for column in df.columns:
        if column == target_column:
            continue
        feature = df[column]
        if feature.nunique(dropna=True) <= 1:
            continue
        agreement = float((feature.astype(str).values == encoded.values).mean())
        if agreement >= NUMERIC_CORRELATION_WARNING:
            result["warnings"].append(
                {
                    "kind": "target_leakage_suspected",
                    "columns": [column, target_column],
                    "agreement": round(float(agreement), 3),
                }
            )
        else:
            numeric_feature = pd.to_numeric(feature, errors="coerce")
            if numeric_feature.notna().sum() > 10:
                try:
                    groups = feature.astype(str).values
                    target_values = encoded.values
                    frame = pd.DataFrame({"g": groups, "t": target_values})
                    purity = (
                        frame.groupby("g")["t"].agg(lambda s: s.value_counts(normalize=True).iloc[0])
                    )
                    if purity.mean() >= HIGH_CORRELATION_INFO and feature.nunique() <= 50:
                        result["info"].append(
                            {"kind": "feature_determines_target", "columns": [column],
                             "mean_group_purity": round(float(purity.mean()), 3)}
                        )
                except Exception:
                    continue
    return result
