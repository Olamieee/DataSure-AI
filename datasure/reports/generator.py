"""Downloadable assessment report generation.

Produces a self-contained HTML report (charts embedded as base64 PNG data
URIs, no CDN dependencies) plus a JSON export. Charts are generated locally
with matplotlib using the Agg backend; no external services are involved.
"""
from __future__ import annotations

import base64
import io
import json
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")  # headless rendering, before pyplot import
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from flask import render_template

from ..datasets.ingest import load_dataframe
from ..models import Assessment, CleaningOperation
from ..profiling.leakage import numeric_correlations

MAX_CHART_CATEGORIES = 12
MAX_HISTOGRAMS = 9


def _fig_to_data_uri(fig) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _chart_missingness(df: pd.DataFrame) -> str | None:
    missing = df.isna().mean() * 100
    missing = missing[missing > 0].sort_values()
    if missing.empty:
        return None
    shown = missing.tail(MAX_CHART_CATEGORIES)
    fig, ax = plt.subplots(figsize=(7, max(2, 0.35 * len(shown))))
    ax.barh(shown.index.astype(str), shown.values, color="#dc3545", alpha=0.75)
    ax.set_xlabel("% missing")
    ax.set_title("Missing values by column")
    ax.set_xlim(0, 100)
    return _fig_to_data_uri(fig)


def _chart_dimension_scores(assessment: Assessment) -> str | None:
    scores = assessment.scores_json or {}
    dimensions = scores.get("dimensions") or {}
    if not dimensions:
        return None
    names = list(dimensions.keys())
    values = [dimensions[name]["score"] for name in names]
    colors = ["#198754" if v >= 80 else ("#fd7e14" if v >= 60 else "#dc3545") for v in values]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    bars = ax.barh([n.capitalize() for n in reversed(names)], list(reversed(values)), color=list(reversed(colors)))
    ax.bar_label(bars, fmt="%.1f", padding=3)
    ax.set_xlim(0, 100)
    ax.set_title("Quality dimension scores (heuristic)")
    return _fig_to_data_uri(fig)


def _chart_numeric_distributions(df: pd.DataFrame) -> str | None:
    numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric:
        return None
    columns = numeric[:MAX_HISTOGRAMS]
    shape = (len(columns), 1)
    fig, axes = plt.subplots(*shape, figsize=(7, 2.0 * len(columns)), squeeze=False)
    for ax, column in zip(axes[:, 0], columns):
        data = df[column].dropna()
        if data.empty:
            continue
        ax.hist(data, bins=30, color="#0d6efd", alpha=0.7)
        ax.set_title(str(column), fontsize=9)
        ax.tick_params(labelsize=8)
    fig.suptitle("Numeric distributions", y=1.02, fontsize=11)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def _chart_correlation_heatmap(df: pd.DataFrame) -> str | None:
    numeric = df.select_dtypes(include=[np.number])
    if numeric.shape[1] < 2:
        return None
    corr = numeric.corr(min_periods=4)
    if corr.empty:
        return None
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    image = ax.imshow(corr.to_numpy(), cmap="RdBu", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(corr.index)))
    ax.set_yticklabels(corr.index, fontsize=8)
    ax.set_title("Numeric correlation matrix", fontsize=11)
    fig.colorbar(image, fraction=0.04, pad=0.03)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def build_report_charts(dataset, assessment: Assessment) -> dict[str, str]:
    from pathlib import Path

    from flask import current_app

    try:
        path = (Path(current_app.instance_path) / "uploads" /
                f"user_{dataset.user_id}" / dataset.storage_filename)
        df = load_dataframe(path, dataset.extension,
                            current_app.config["MAX_ROWS"], current_app.config["MAX_COLUMNS"])
    except Exception:
        return {}

    charts: dict[str, str] = {}
    builders = {
        "missingness": _chart_missingness(df),
        "scores": _chart_dimension_scores(assessment),
        "distributions": _chart_numeric_distributions(df),
        "correlations": _chart_correlation_heatmap(df),
    }
    for key, image in builders.items():
        if image:
            charts[key] = image
    return charts


def generate_html_report(dataset, assessment, operations, user, generated_at=None) -> str:
    charts = build_report_charts(dataset, assessment)
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return render_template(
        "datasets/report.html",
        dataset=dataset,
        assessment=assessment,
        charts=charts,
        operations=operations,
        user=user,
        generated_at=generated_at,
    )


def generate_json_report(dataset, assessment, operations) -> str:
    payload = {
        "generator": "DataSure AI",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "sha256": dataset.sha256,
            "storage_version": dataset.storage_version,
            "row_count": assessment.row_count,
            "column_count": assessment.column_count,
        },
        "assessment": {
            "id": assessment.id,
            "created_at": assessment.created_at.isoformat(),
            "quality_score": assessment.quality_score,
            "scores": assessment.scores_json,
            "issues": assessment.issues_json,
            "target_column": assessment.target_column,
            "label": assessment.label,
        },
        "profile": assessment.profile_json,
        "cleaning_operations": [
            {
                "operation": op.operation,
                "params": op.params_json,
                "rows_before": op.rows_before,
                "rows_after": op.rows_after,
                "cells_changed": op.cells_changed,
                "created_at": op.created_at.isoformat(),
            }
            for op in operations
        ],
        "disclaimer": (
            "Scores are heuristic indicators with documented formulas and fixed "
            "thresholds, not scientifically validated measures of dataset quality."
        ),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
