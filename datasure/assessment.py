"""Assessment orchestration: profile a dataset, detect issues, score it, store results.

This is the main entry point used by web routes and the REST API alike, so both
paths stay consistent.
"""
from __future__ import annotations

import time
from typing import Any

from flask import current_app

from .extensions import db
from .models import Assessment, Dataset
from .profiling.leakage import analyse_target_leakage, numeric_correlations
from .profiling.profile import profile_dataset
from .profiling.scoring import compute_scores
from .profiling.issues import build_issues


def run_assessment(dataset: Dataset, *, target_column: str | None = None,
                   label: str | None = None) -> Assessment:
    """Run a full assessment for `dataset`. Returns the stored Assessment row.

    Never mutates dataset contents. Reading failures surface as OSError/ValueError
    which the caller converts into user-facing messages.
    """
    started = time.perf_counter()
    from .storage import user_upload_dir
    from .datasets.ingest import load_dataframe

    path = _dataset_path(current_app, dataset)
    df = load_dataframe(
        path,
        dataset.extension,
        current_app.config["MAX_ROWS"],
        current_app.config["MAX_COLUMNS"],
    )

    profile = profile_dataset(df)
    leakage = analyse_target_leakage(df, target_column)
    strong_pairs, _all_pairs = numeric_correlations(df)
    if strong_pairs:
        for col_a, others in strong_pairs.items():
            for col_b in others:
                if col_a < col_b:  # report each pair once
                    leakage.setdefault("info", []).append(
                        {"kind": "redundant_feature_pair", "columns": [col_a, col_b]}
                    )
    issues = build_issues(profile, leakage)
    scores = compute_scores(profile)

    assessment = Assessment(
        dataset_id=dataset.id,
        user_id=dataset.user_id,
        quality_score=scores["overall"],
        scores_json=scores,
        issues_json=issues,
        profile_json=profile,
        row_count=profile["overview"]["rows"],
        column_count=profile["overview"]["columns"],
        target_column=target_column,
        duration_ms=int((time.perf_counter() - started) * 1000),
        label=label or None,
    )
    db.session.add(assessment)
    db.session.commit()
    return assessment


def _dataset_path(app, dataset: Dataset):
    from pathlib import Path

    from .storage import user_upload_dir

    uploads = Path(user_upload_dir(app.instance_path, dataset.user_id))
    return uploads / dataset.storage_filename


def load_dataset_dataframe(dataset: Dataset):
    """Load the CURRENT stored file of a dataset (original or latest cleaned)."""
    from flask import current_app

    from .datasets.ingest import load_dataframe

    path = _dataset_path(current_app, dataset)
    return load_dataframe(
        path,
        dataset.extension,
        current_app.config["MAX_ROWS"],
        current_app.config["MAX_COLUMNS"],
    )
