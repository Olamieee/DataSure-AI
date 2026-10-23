"""REST API v1 (read-oriented, JSON only).

Authentication: session cookie (browser) or API key via `X-API-Key` header.
API keys are per-user, regenerable, stored only as SHA-256 hashes.
Endpoints never return other users' data and never echo dataset contents.
"""
from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, request
from flask_login import current_user

from ..assessment import load_dataset_dataframe
from ..datasets.ingest import DatasetParseError
from ..models import (
    Assessment,
    CleaningOperation,
    Dataset,
    SchemaContract,
    ValidationRule,
    db,
)
from ..profiling.profile import ProfilingTimeout

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


def _own_contract(contract_id: int) -> SchemaContract:
    user = _api_user()
    contract = db.session.get(SchemaContract, contract_id)
    if contract is None or contract.user_id != user.id:
        raise ApiError("contract not found", 404)
    return contract


def _contract_summary(contract: SchemaContract) -> dict:
    return {
        "id": contract.id,
        "name": contract.name,
        "description": contract.description,
        "column_count": len(contract.contract_json.get("columns", [])),
        "created_at": contract.created_at.isoformat(),
    }


@bp.post("/datasets/<int:dataset_id>/contract")
def create_contract_from_dataset(dataset_id: int):
    """Generate a schema-contract snapshot from an owned dataset.

    Body (JSON, all fields optional): ``{"name": "...", "description": "..."}``.
    ``name`` defaults to the dataset name. Mirrors the web flow: the contract
    is built from the currently stored file's columns.
    """
    from ..contracts.engine import contract_from_dataframe

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise ApiError("body must be a JSON object", 400)

    dataset = _own_dataset(dataset_id)
    try:
        df = load_dataset_dataframe(dataset)
    except DatasetParseError as exc:
        raise ApiError(str(exc), 422)

    name = str(payload.get("name") or dataset.name).strip()[:120]
    description = str(payload.get("description") or "").strip()[:500] or (
        f"Generated from '{dataset.name}' "
        f"({df.shape[0]} rows × {df.shape[1]} columns)."
    )
    record = SchemaContract(
        user_id=_api_user().id,
        name=name,
        description=description,
        contract_json=contract_from_dataframe(df, name),
    )
    db.session.add(record)
    db.session.commit()
    return jsonify(
        {"created": True, "contract_summary": _contract_summary(record)}
    ), 201


@bp.get("/contracts")
def list_contracts():
    user = _api_user()
    from ..pagination import clamp_page_size, paginate_stable

    page = request.args.get("page", 1, type=int)
    per_page = clamp_page_size(request.args.get("per_page", type=int))
    result = paginate_stable(
        SchemaContract.query.filter_by(user_id=user.id)
        .order_by(SchemaContract.created_at.desc(), SchemaContract.id.desc()),
        page=page,
        per_page=per_page,
    )
    return jsonify(
        {
            "page": result["page"],
            "per_page": result["per_page"],
            "total": result["total"],
            "next_page": result["next_num"] if result["has_next"] else None,
            "contracts": [_contract_summary(c) for c in result["items"]],
        }
    )


@bp.get("/contracts/<int:contract_id>")
def get_contract(contract_id: int):
    contract = _own_contract(contract_id)
    payload = _contract_summary(contract)
    payload["contract"] = contract.contract_json
    return jsonify(payload)


@bp.post("/contracts/<int:contract_id>/validate")
def validate_contract(contract_id: int):
    """Run contract validation against an owned dataset's stored data.

    Body: JSON {"dataset_id": <int>}. Returns the violation list (empty means
    the dataset satisfies the contract) and updates the dataset's stored
    contract flags exactly like the web flow does.
    """
    contract = _own_contract(contract_id)
    payload = request.get_json(silent=True) or {}
    dataset_id = payload.get("dataset_id")
    if not isinstance(dataset_id, int):
        raise ApiError("body must be JSON with an integer 'dataset_id'", 400)
    dataset = _own_dataset(dataset_id)
    try:
        df = load_dataset_dataframe(dataset)
    except DatasetParseError as exc:
        raise ApiError(str(exc), 422)

    from ..contracts.engine import validate_dataframe as _validate

    violations = _validate(df, contract.contract_json)
    dataset.contract_id = contract.id
    dataset.contract_passed = not violations
    db.session.commit()
    return jsonify(
        {
            "contract_id": contract.id,
            "contract_name": contract.name,
            "dataset_id": dataset.id,
            "passed": not violations,
            "violations": violations,
        }
    )


# --------------------------------------------------------------------- rules
def _rule_summary(rule: ValidationRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "rule": rule.rule_json,
        "created_at": rule.created_at.isoformat(),
    }


@bp.get("/rules")
def list_rules():
    user = _api_user()
    from ..pagination import clamp_page_size, paginate_stable

    page = request.args.get("page", 1, type=int)
    per_page = clamp_page_size(request.args.get("per_page", type=int))
    result = paginate_stable(
        ValidationRule.query.filter_by(user_id=user.id)
        .order_by(ValidationRule.created_at.desc(), ValidationRule.id.desc()),
        page=page,
        per_page=per_page,
    )
    return jsonify(
        {
            "page": result["page"],
            "per_page": result["per_page"],
            "total": result["total"],
            "next_page": result["next_num"] if result["has_next"] else None,
            "rules": [_rule_summary(r) for r in result["items"]],
        }
    )


@bp.post("/rules")
def create_rule():
    """Create a validation rule from a JSON definition (never evaluated as code)."""
    user = _api_user()
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()[:120]
    if not name:
        raise ApiError("name is required", 400)
    rule_type = payload.get("rule_type") or ""
    rule_json = payload.get("rule")
    if not isinstance(rule_json, dict):
        raise ApiError("'rule' must be a JSON object", 400)
    from ..rules.engine import RuleDefinitionError, normalise_rule

    try:
        normalised = normalise_rule(rule_type, rule_json)
    except RuleDefinitionError as exc:
        raise ApiError(str(exc), 422)
    record = ValidationRule(
        user_id=user.id, name=name, rule_type=rule_type, rule_json=normalised
    )
    db.session.add(record)
    db.session.commit()
    return jsonify(_rule_summary(record)), 201


@bp.post("/datasets/<int:dataset_id>/rules/run")
def run_rules_on_dataset(dataset_id: int):
    """Run selected rules against an owned dataset's stored data.

    Body: JSON {"rule_ids": [<int>, ...]} – every id must belong to the
    caller. Results mirror the web run: one pass/fail summary per rule.
    """
    dataset = _own_dataset(dataset_id)
    user = _api_user()
    payload = request.get_json(silent=True) or {}
    ids = payload.get("rule_ids")
    if not isinstance(ids, list) or not ids or not all(
        isinstance(value, int) for value in ids
    ):
        raise ApiError(
            "body must include a non-empty 'rule_ids' list of integers", 400
        )
    wanted = set(ids)
    rules = (
        ValidationRule.query.filter(
            ValidationRule.user_id == user.id,
            ValidationRule.id.in_(wanted),
        )
        .order_by(ValidationRule.created_at.desc(), ValidationRule.id.desc())
        .all()
    )
    if {r.id for r in rules} != wanted:
        raise ApiError("one or more selected rules do not exist", 404)
    try:
        df = load_dataset_dataframe(dataset)
    except DatasetParseError as exc:
        raise ApiError(str(exc), 422)
    from ..rules.engine import run_rules as _run

    results = _run(df, rules)
    failed = sum(1 for result in results if not result["passed"])
    return jsonify(
        {
            "dataset_id": dataset.id,
            "passed": len(results) - failed,
            "failed": failed,
            "results": results,
        }
    )


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "service": "datasure-ai", "api_version": "v1"})


@bp.get("/datasets")
def list_datasets():
    user = _api_user()
    from ..pagination import paginate_stable

    page = request.args.get("page", 1, type=int)
    per_page = clamp_api_page_size()
    result = paginate_stable(
        Dataset.query.filter_by(user_id=user.id)
        .order_by(Dataset.updated_at.desc(), Dataset.id.desc()),
        page=page,
        per_page=per_page,
    )
    return jsonify(
        {
            "page": result["page"],
            "per_page": result["per_page"],
            "total": result["total"],
            "has_next": result["has_next"],
            # cursor for clients: appending ?page=N+1 lists the next slice
            "next_page": result["next_num"] if result["has_next"] else None,
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
                    "tags": [t for t in (d.tags or "").split(",") if t],
                    "created_at": d.created_at.isoformat(),
                }
                for d in result["items"]
            ],
        }
    )


@bp.get("/datasets/<int:dataset_id>/columns")
def get_dataset_columns(dataset_id: int):
    """Column-level dictionary from the latest assessment's profile."""
    dataset = _own_dataset(dataset_id)
    latest = (
        Assessment.query.filter_by(dataset_id=dataset.id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )
    if latest is None:
        raise ApiError("no assessment for this dataset yet", 404)
    columns = (latest.profile_json or {}).get("columns", [])
    return jsonify(
        {
            "dataset_id": dataset.id,
            "assessment_id": latest.id,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "columns": columns,
        }
    )


@bp.get("/datasets/<int:dataset_id>/trend")
def dataset_trend(dataset_id: int):
    """Chronological quality trajectory across all of this dataset's runs."""
    dataset = _own_dataset(dataset_id)
    rows = (
        Assessment.query.filter_by(dataset_id=dataset.id)
        .order_by(Assessment.created_at.asc(), Assessment.id.asc())
        .all()
    )
    return jsonify(
        {
            "dataset_id": dataset.id,
            "points": [
                {
                    "assessment_id": row.id,
                    "at": row.created_at.isoformat(),
                    "quality_score": row.quality_score,
                    "issue_count": len(row.issues_json or []),
                }
                for row in rows
            ],
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
        "tags": [t for t in (dataset.tags or "").split(",") if t],
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
    except ProfilingTimeout as exc:
        raise ApiError(f"assessment stopped: {exc}", 503)
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


@bp.get("/assessments/<int:assessment_id>/export/<export_kind>.csv")
def export_assessment_csv(assessment_id: int, export_kind: str):
    """CSV export of an assessment's issues or per-column statistics.

    Mirrors the web downloads so scheduled API clients can export the exact
    same artefacts the browser offers.
    """
    if export_kind not in {"issues", "stats", "history"}:
        raise ApiError("unknown export kind; use 'issues', 'stats' or 'history'", 404)
    user = _api_user()
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None or assessment.user_id != user.id:
        raise ApiError("assessment not found", 404)
    import csv as _csv
    import io as _io

    from ..datasets.routes import _download_name

    if export_kind == "history":
        from ..datasets.routes import _history_rows

        rows = _history_rows(assessment.dataset) or [["when", "operation"]]
        dataset = assessment.dataset
    else:
        from ..datasets.routes import _export_rows

        rows = _export_rows(assessment, export_kind)
        dataset = db.session.get(Dataset, assessment.dataset_id)
    buffer = _io.StringIO()
    writer = _csv.writer(buffer, quoting=_csv.QUOTE_MINIMAL, lineterminator="\r\n")
    for row in rows:
        writer.writerow(row)
    download_name = _download_name(dataset).replace(
        dataset.extension.lstrip(".") or "csv", f"_{export_kind}.csv"
    )
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={download_name}"},
    )


@bp.get("/assessments/compare")
def compare_assessments_endpoint():
    """Compare two of your assessments (any order, any owned datasets).

    Query params: `from` and `to` (assessment ids). Returns the same
    comparison structure the web compare page renders.
    """
    from_id = request.args.get("from", type=int)
    to_id = request.args.get("to", type=int)
    if not from_id or not to_id:
        raise ApiError(
            "provide integer query params 'from' and 'to' (assessment ids)",
            400,
        )
    if from_id == to_id:
        raise ApiError("'from' and 'to' must be different assessments", 400)
    user = _api_user()
    assessment_from = db.session.get(Assessment, from_id)
    assessment_to = db.session.get(Assessment, to_id)
    for assessment in (assessment_from, assessment_to):
        if assessment is None or assessment.user_id != user.id:
            raise ApiError("assessment not found", 404)
    from ..profiling.compare import compare_assessments as _compare

    result = _compare(assessment_from, assessment_to)
    return jsonify(
        {
            "from": from_id,
            "to": to_id,
            "comparison": result,
        }
    )


@bp.get("/datasets/<int:dataset_id>/assessments")
def list_assessments(dataset_id: int):
    dataset = _own_dataset(dataset_id)
    from ..pagination import DEFAULT_PAGE_SIZE, clamp_page_size, paginate_stable

    page = request.args.get("page", 1, type=int)
    per_page = clamp_page_size(request.args.get("per_page", type=int))
    result = paginate_stable(
        dataset.assessments.order_by(Assessment.created_at.desc(),
                                     Assessment.id.desc()),
        page=page,
        per_page=per_page,
    )
    return jsonify({
        "page": result["page"],
        "per_page": result["per_page"],
        "total": result["total"],
        "next_page": result["next_num"] if result["has_next"] else None,
        "assessments": [_assessment_summary(a) for a in result["items"]],
    })


@bp.get("/assessments/<int:assessment_id>/report")
def get_assessment_report(assessment_id: int):
    """The full JSON data-quality report as one download-shaped payload.

    Same generator as the web report download (`?format=json`), returned with
    an attachment disposition so scripts can persist it directly.
    """
    from datetime import datetime, timezone

    from flask import Response

    from ..reports import generate_json_report

    user = _api_user()
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None or assessment.user_id != user.id:
        raise ApiError("assessment not found", 404)
    dataset = db.session.get(Dataset, assessment.dataset_id)
    operations = (
        dataset.cleaning_operations
        .order_by(CleaningOperation.created_at.asc())
        .all()
    )
    content = generate_json_report(dataset, assessment, operations)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    name = (
        f"report_dataset{dataset.id}_assessment{assessment.id}_{stamp}.json"
    )
    return Response(
        content,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={name}"},
    )


@bp.get("/datasets/<int:dataset_id>/cleaning")
def cleaning_history(dataset_id: int):
    dataset = _own_dataset(dataset_id)
    from ..pagination import clamp_page_size, paginate_stable

    page = request.args.get("page", 1, type=int)
    per_page = clamp_page_size(request.args.get("per_page", type=int))
    result = paginate_stable(
        CleaningOperation.query.filter_by(dataset_id=dataset.id)
        .order_by(CleaningOperation.created_at.desc(), CleaningOperation.id.desc()),
        page=page,
        per_page=per_page,
    )
    return jsonify(
        {
            "page": result["page"],
            "per_page": result["per_page"],
            "total": result["total"],
            "next_page": result["next_num"] if result["has_next"] else None,
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
                for op in result["items"]
            ],
        }
    )


def clamp_api_page_size() -> int:
    from ..pagination import DEFAULT_PAGE_SIZE, clamp_page_size

    return clamp_page_size(request.args.get("per_page", type=int),
                           DEFAULT_PAGE_SIZE)


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


# --------------------------------------------------------------------- files
@bp.delete("/datasets/<int:dataset_id>")
def delete_dataset(dataset_id: int):
    """Permanently delete an owned dataset, its stored file and history."""
    from ..datasets.routes import remove_dataset

    dataset = _own_dataset(dataset_id)
    payload = {"id": dataset.id, "name": dataset.name,
               "file_removed": dataset.storage_filename}
    remove_dataset(dataset, _api_user().id)
    return jsonify({"deleted": True, "dataset": payload})


@bp.get("/datasets/<int:dataset_id>/file")
def download_dataset_file(dataset_id: int):
    """Download the currently stored file of an owned dataset.

    This is the exact stored copy (the cleaned version when the dataset has
    been processed), fetched with an attachment disposition so scripts can
    pull back their data.
    """
    from flask import current_app, send_file

    from ..datasets.routes import _download_name, user_upload_dir

    dataset = _own_dataset(dataset_id)
    path = user_upload_dir(current_app.instance_path, dataset.user_id) / (
        dataset.storage_filename
    )
    if not path.exists():
        from ..audit import record_audit

        record_audit(
            "dataset_file_missing", _api_user().id, dataset_id=dataset.id
        )
        raise ApiError("stored file is missing", 404)
    return send_file(
        path,
        as_attachment=True,
        download_name=_download_name(dataset),
    )


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
