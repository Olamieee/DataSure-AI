"""Transparent dataset quality scoring.

IMPORTANT METHODOLOGY NOTE
--------------------------
These scores are *heuristic indicators*, computed from clearly documented
formulas and thresholds. They are NOT scientifically validated measures of
"dataset quality": quality is application-specific and no generic scalar can
fully capture it. The scores exist to guide review, not to replace judgement.

Every dimension returns: score (0-100), formula, the exact inputs used and a
breakdown of each penalty applied, so any score can be recomputed by hand.

Weights (configurable constants below):
    completeness       30%
    uniqueness         15%
    validity           25%
    consistency        20%
    distribution       10%
"""
from __future__ import annotations

import math

WEIGHTS = {
    "completeness": 0.30,
    "uniqueness": 0.15,
    "validity": 0.25,
    "consistency": 0.20,
    "distribution": 0.10,
}


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def compute_scores(profile: dict) -> dict:
    """Compute the five quality dimensions plus a weighted overall score."""
    scorers = {
        "completeness": score_completeness,
        "uniqueness": score_uniqueness,
        "validity": score_validity,
        "consistency": score_consistency,
        "distribution": score_distribution,
    }
    dimensions = {name: scorer(profile) for name, scorer in scorers.items()}
    overall = _clamp(
        math.fsum(dimensions[name]["score"] * WEIGHTS[name] for name in WEIGHTS)
    )
    return {
        "overall": overall,
        "weights": WEIGHTS,
        "dimensions": dimensions,
        "disclaimer": (
            "Scores are heuristic indicators computed from documented formulas with "
            "fixed thresholds. They are not scientifically validated measures of data "
            "quality and should always be reviewed alongside the underlying issues."
        ),
    }


def score_completeness(profile: dict) -> dict:
    missing = profile["missingness"]
    total = max(missing["total_cells"], 1)
    score = _clamp(100.0 * (1.0 - missing["missing_cells"] / total))
    return {
        "score": score,
        "formula": "100 * (1 - missing_cells / total_cells)",
        "inputs": {
            "missing_cells": missing["missing_cells"],
            "total_cells": missing["total_cells"],
        },
        "breakdown": [],
    }


def score_uniqueness(profile: dict) -> dict:
    duplicates = profile["duplicates"]
    rows = max(profile["overview"]["rows"], 1)
    columns = max(profile["overview"]["columns"], 1)
    row_frac = duplicates["duplicate_rows"] / rows
    column_frac = len(duplicates["duplicate_columns"]) / columns
    loss = 0.7 * row_frac + 0.3 * column_frac
    return {
        "score": _clamp(100.0 * (1.0 - loss)),
        "formula": "100 * (1 - (0.7 * duplicate_row_ratio + 0.3 * duplicate_column_ratio))",
        "inputs": {
            "duplicate_rows": duplicates["duplicate_rows"],
            "duplicate_row_ratio": round(row_frac, 4),
            "duplicate_columns": duplicates["duplicate_columns"],
            "duplicate_column_ratio": round(column_frac, 4),
        },
        "breakdown": [
            {"penalty": round(70.0 * row_frac, 1), "cause": "duplicate rows"},
            {"penalty": round(30.0 * column_frac, 1), "cause": "duplicate columns"},
        ],
    }


def _penalty(items: int, per_instance: int, label: str) -> dict:
    return {"penalty": items * per_instance, "cause": f"{items:,} {label}"}


def score_validity(profile: dict) -> dict:
    penalties: list[dict] = []
    schema = profile.get("schema", {}).get("suspicious_type_storage", [])
    if schema:
        penalties.append(_penalty(len(schema), 6, "columns stored as text though numeric"))
    for entry in profile["columns"]:
        if entry["kind"] == "mixed":
            penalties.append(_penalty(1, 4, f"mixed-type column '{entry['name']}'"))
        if entry.get("python_types", {}).get("dict") or entry.get("python_types", {}).get("list"):
            penalties.append(_penalty(1, 4, f"nested structures in '{entry['name']}'"))
    empty_columns = [entry for entry in profile["columns"] if entry["non_null"] == 0]
    if empty_columns:
        penalties.append(_penalty(len(empty_columns), 6, "completely empty columns"))
    # Impossible numeric ranges (e.g. negative ages) are reported as NaN/inf guard.
    for entry in profile["columns"]:
        stats = entry.get("stats")
        if stats and (stats.get("std") is None or (math.isnan(stats["std"]) if stats["std"] else False)):
            penalties.append(_penalty(1, 4, f"unstable numeric statistics in '{entry['name']}'"))
    total = _clamp(100.0 - math.fsum(penalised["penalty"] for penalised in penalties))
    return {
        "score": total,
        "formula": ("100 - sum of penalties: 6 per numeric-as-text column, 4 per mixed-type "
                    "column or nested structure, 6 per empty column, 4 per unstable column"),
        "inputs": {},
        "breakdown": penalties,
    }


def score_consistency(profile: dict) -> dict:
    penalties: list[dict] = []
    whitespace_columns = [
        entry for entry in profile["columns"] if entry.get("whitespace_issue_count")
    ]
    if whitespace_columns:
        penalties.append(
            _penalty(len(whitespace_columns), 3, "columns with leading/trailing whitespace")
        )
    outlier_pairs = 0
    for entry in profile["columns"]:
        outliers = entry.get("outliers") or {}
        if outliers.get("iqr_count", 0) > 0:
            outlier_pairs += 1
    if outlier_pairs:
        penalties.append(_penalty(outlier_pairs, 2, "numeric columns with IQR outliers"))
    schema_issues = profile.get("schema", {}).get("suspicious_type_storage", [])
    if schema_issues:
        penalties.append(_penalty(len(schema_issues), 3, "inconsistent value formats"))
    total = _clamp(100.0 - math.fsum(p["penalty"] for p in penalties))
    return {
        "score": total,
        "formula": ("100 - sum of penalties: 3 per column whose values need whitespace "
                    "normalisation, 2 per numeric column with Tukey outliers, 3 per column "
                    "with inconsistent value formats"),
        "inputs": {},
        "breakdown": penalties,
    }


def score_distribution(profile: dict) -> dict:
    penalties: list[dict] = []
    for entry in profile["columns"]:
        if entry["kind"] != "numeric":
            continue
        skew = entry.get("skew")
        if skew is not None and abs(skew) >= 3.0:
            penalties.append(_penalty(1, 2, f"highly skewed column '{entry['name']}'"))
    for entry in profile["columns"]:
        ratio = entry.get("class_imbalance_ratio")
        if ratio is not None and entry.get("unique", 0) in range(2, 21) and ratio <= 0.05:
            penalties.append(
                _penalty(1, 3, f"heavily imbalanced categorical column '{entry['name']}'")
            )
    for entry in profile["columns"]:
        if entry["kind"] == "categorical" and entry["non_null"] > 1:
            top = entry.get("top_values", [])
            if top and len(top) == 1 and (top[0]["pct"] >= 99.0):
                penalties.append(_penalty(1, 2, f"quasi-constant category column '{entry['name']}'"))
    total = _clamp(100.0 - math.fsum(p["penalty"] for p in penalties))
    return {
        "score": total,
        "formula": ("100 - sum of penalties: 2 per numerically skewed column (|skew| >= 3), "
                    "3 per heavily imbalanced categorical column (2-20 categories, minority "
                    "<= 5% of majority), 2 per quasi-constant category column"),
        "inputs": {},
        "breakdown": penalties,
    }
