"""REST API v1 (read-oriented, JSON only).

Authentication: session cookie (browser) or API key via `X-API-Key` header.
API keys are per-user, regenerable, stored only as SHA-256 hashes.
Endpoints never return other users' data and never echo dataset contents.
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from ..assessment import load_dataset_dataframe
from ..datasets.ingest import DatasetParseError
from ..models import Assessment, CleaningOperation, Dataset, db

bp = Blueprint("api", __name__)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status


@bp.errorhandler(ApiError)
def _handle_api_error(error: ApiError):
    return jsonify({"error": error.message}), error.status


@bp.errorhandler(404)
def _handle_missing(_error):
    return jsonify({"error": "resource not found"}), 404


@bp.before_request
def _authenticate():
    """Session OR API-key authentication for every /api/v1 request."""
    if request.method == "OPTIONS":
        return None
    if request.endpoint == "api.health":
        return None  # health/readiness probes are unauthenticated
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        from ..auth.apikeys import authenticate_key

        result = authenticate_key(api_key)
        if result is None or not result[1].is_active_user:
            raise ApiError("invalid API key", 401)
        request.environ["datasure_api_user"] = result[1]
        return None
    if current_user.is_authenticated:
        return None
    raise ApiError("authentication required: send a valid X-API-Key header "
                   "or log in", 401)


def _api_user() -> User:
    if "datasure_api_user" in request.environ:
        return request.environ["datasure_api_user"]
    return current_user._get_current_object()  # type: ignore[attr-defined]


def _own_dataset(dataset_id: int) -> Dataset:
    user = _api_user()
    dataset = db.session.get(Dataset, dataset_id)
    if dataset is None or dataset.user_id != user.id:
        raise ApiError("dataset not found", 404)
    return dataset


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "datasure-ai", "api_version": "v1"})


@bp.get("/datasets")
def list_datasets():
    user = _api_user()
    datasets = (
        Dataset.query.filter_by(user_id=user.id)
        .order_by(Dataset.updated_at.desc())
        .limit(200)
        .all()
    )
    return jsonify(
        {
            "datasets": [
                {
                    "id": d.id,
                    "name": d.name,
                    "extension": d.extension,
                    "row_count": d.row_count,
                    "column_count": d.column_count,
                    "status": d.status,
                    "size_bytes": d.size_bytes,
                    "storage_version": d.storage_version,
                    "is_cleaned": d.is_cleaned,
                    "created_at": d.created_at.isoformat(),
                }
                for d in datasets
            ]
        }
    )


@bp.get("/datasets/<int:dataset_id>")
def get_dataset(dataset_id: int):
    dataset = _own_dataset(dataset_id)
    latest = dataset.assessments.order_by(Assessment.created_at.desc()).first()
    payload = {
        "id": dataset.id,
        "name": dataset.name,
        "extension": dataset.extension,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "status": dataset.status,
        "size_bytes": dataset.size_bytes,
        "sha256": dataset.sha256,
        "storage_version": dataset.storage_version,
        "is_cleaned": dataset.is_cleaned,
        "created_at": dataset.created_at.isoformat(),
        "latest_assessment_id": latest.id if latest else None,
        "latest_quality_score": latest.quality_score if latest else None,
    }
    return jsonify(payload)


@bp.post("/datasets/<int:dataset_id>/assessments")
def create_assessment(dataset_id: int):
    """Run a new assessment (the main POST operation of the API)."""
    dataset = _own_dataset(dataset_id)
    payload = request.get_json(silent=True) or {}
    target = (payload.get("target_column") or "").strip() or None
    label = (payload.get("label") or "").strip() or None
    try:
        from ..assessment import run_assessment as _run

        assessment = _run(dataset, target_column=target, label=label)
    except DatasetParseError as exc:
        raise ApiError(str(exc), 422)
    except Exception as exc:
        current_app.logger.exception("API assessment crashed for dataset %s", dataset.id)
        raise ApiError("assessment failed unexpectedly; see server logs", 500)
    return jsonify(_assessment_summary(assessment)), 201


@bp.get("/assessments/<int:assessment_id>")
def get_assessment(assessment_id: int):
    user = _api_user()
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None or assessment.user_id != user.id:
        raise ApiError("assessment not found", 404)
    payload = _assessment_summary(assessment)
    payload["profile"] = assessment.profile_json
    return jsonify(payload)


@bp.get("/datasets/<int:dataset_id>/assessments")
def list_assessments(dataset_id: int):
    dataset = _own_dataset(dataset_id)
    rows = dataset.assessments.order_by(Assessment.created_at.desc()).limit(100).all()
    return jsonify({"assessments": [_assessment_summary(a) for a in rows]})


@bp.get("/datasets/<int:dataset_id>/cleaning")
def cleaning_history(dataset_id: int):
    dataset = _own_dataset(dataset_id)
    rows = (
        CleaningOperation.query.filter_by(dataset_id=dataset.id)
        .order_by(CleaningOperation.created_at.desc())
        .limit(100)
        .all()
    )
    return jsonify(
        {
            "operations": [
                {
                    "id": op.id,
                    "operation": op.operation,
                    "params": op.params_json,
                    "rows_before": op.rows_before,
                    "rows_after": op.rows_after,
                    "cells_changed": op.cells_changed,
                    "created_at": op.created_at.isoformat(),
                }
                for op in rows
            ]
        }
    )


@bp.get("/datasets/<int:dataset_id>/preview")
def preview(dataset_id: int):
    """First rows of the stored dataset."""
    from ..datasets.ingest import dataset_preview

    dataset = _own_dataset(dataset_id)
    limit = min(int(request.args.get("rows", "10")), current_app.config["PREVIEW_ROWS"])
    try:
        df = load_dataset_dataframe(dataset)
    except DatasetParseError as exc:
        raise ApiError(str(exc), 422)
    table = dataset_preview(df.head(limit), limit)
    return jsonify({"columns": list(df.columns), "rows": table[1:limit + 1]})


def _assessment_summary(assessment: Assessment) -> dict:
    return {
        "id": assessment.id,
        "dataset_id": assessment.dataset_id,
        "created_at": assessment.created_at.isoformat(),
        "quality_score": assessment.quality_score,
        "target_column": assessment.target_column,
        "label": assessment.label,
        "row_count": assessment.row_count,
        "column_count": assessment.column_count,
        "duration_ms": assessment.duration_ms,
        "scores": assessment.scores_json,
        "issues": assessment.issues_json,
    }
