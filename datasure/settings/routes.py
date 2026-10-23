"""Account settings: API key management.

Keys are shown in full exactly once, at creation. Only names, hash digests
(safely truncated) and usage timestamps are ever rendered.
"""
from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..auth.apikeys import create_key, get_owned_key, list_keys, revoke_key

bp = Blueprint("settings", __name__)


@bp.before_request
def _login_required():
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()


@bp.get("/api-keys")
@login_required
def api_keys():
    keys = list_keys(current_user)
    return render_template("settings/api_keys.html", keys=keys,
                           max_keys_error=None)


@bp.post("/api-keys")
@login_required
def create_api_key():
    name = (request.form.get("name") or "").strip()[:80]
    try:
        record, raw = create_key(current_user, name)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("settings.api_keys"))
    keys = list_keys(current_user)
    flash("API key created. Copy it now - it will not be shown again.", "success")
    return render_template(
        "settings/api_keys.html",
        keys=keys,
        new_key=raw,
        new_key_name=record.name,
        max_keys_error=None,
    )


@bp.post("/api-keys/<int:key_id>/revoke")
@login_required
def revoke_api_key(key_id: int):
    record = get_owned_key(current_user, key_id)
    if record is None:
        flash("API key not found.", "danger")
        return redirect(url_for("settings.api_keys"))
    if not record.is_active():
        flash("That API key is already revoked.", "info")
        return redirect(url_for("settings.api_keys"))
    revoke_key(current_user, key_id)
    flash(f"API key '{record.name}' revoked.", "info")
    return redirect(url_for("settings.api_keys"))


@bp.get("/storage")
@login_required
def storage():
    """Storage usage summary for your account."""
    from sqlalchemy import func

    from ..models import Dataset

    base_query = Dataset.query.filter_by(user_id=current_user.id)
    totals = base_query.with_entities(
        func.count(Dataset.id).label("count"),
        func.coalesce(func.sum(Dataset.size_bytes), 0).label("bytes"),
    ).one()
    biggest = (
        base_query.order_by(Dataset.size_bytes.desc(), Dataset.id.desc()).first()
    )
    return render_template(
        "settings/storage.html",
        dataset_count=totals.count,
        bytes_used=int(totals.bytes),
        biggest=biggest,
        upload_mb=current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
    )


@bp.get("/activity")
@login_required
def activity():
    """Your audit trail: recorded actions only you can see."""
    from ..audit import ALLOWED_ACTIONS
    from ..models import AuditEvent
    from ..pagination import paginate_stable

    page = request.args.get("page", 1, type=int)
    action = (request.args.get("action") or "").strip()[:64]
    base_query = AuditEvent.query.filter_by(user_id=current_user.id)
    if action:
        base_query = base_query.filter(AuditEvent.action == action)
    result = paginate_stable(
        base_query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()),
        page=page,
        per_page=25,
    )
    return render_template(
        "settings/activity.html",
        events=result["items"],
        page=result,
        action=action,
        allowed_actions=sorted(ALLOWED_ACTIONS),
    )


@bp.get("/export")
@login_required
def export_data():
    """Download everything your account contains as one JSON bundle.

    Datasets appear as metadata + stored values preview only (the full files
    are downloadable separately per dataset); everything else is complete.
    No other user's data is ever included.
    """
    import io
    import json as _json
    from datetime import datetime, timezone

    from flask import Response, send_file

    from ..assessment import load_dataset_dataframe
    from ..datasets.ingest import DatasetParseError
    from ..models import (
        Assessment,
        AuditEvent,
        CleaningOperation,
        Dataset,
        SchemaContract,
        ValidationRule,
    )

    datasets = (
        Dataset.query.filter_by(user_id=current_user.id)
        .order_by(Dataset.id.asc())
        .all()
    )
    dataset_payloads = []
    for dataset in datasets:
        preview: dict = {}  # columns + a few rows, when the file still parses
        try:
            df = load_dataset_dataframe(dataset)
            preview = {"columns": [str(c) for c in df.columns],
                       "rows": df.head(5).astype(str).values.tolist()}
        except DatasetParseError:
            preview = {"error": "stored file could not be read"}
        dataset_payloads.append({
            "id": dataset.id,
            "name": dataset.name,
            "original_filename": dataset.original_filename,
            "extension": dataset.extension,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "size_bytes": dataset.size_bytes,
            "sha256": dataset.sha256,
            "status": dataset.status,
            "is_cleaned": dataset.is_cleaned,
            "tags": [t for t in (dataset.tags or "").split(",") if t],
            "created_at": dataset.created_at.isoformat(),
            "assessments": [
                {
                    "id": a.id,
                    "quality_score": a.quality_score,
                    "created_at": a.created_at.isoformat(),
                    "label": a.label,
                }
                for a in dataset.assessments.order_by(Assessment.id.asc()).all()
            ],
            "cleaning_operations": [
                {"id": op.id, "operation": op.operation,
                 "success": op.success,
                 "created_at": op.created_at.isoformat()}
                for op in dataset.cleaning_operations
                .order_by(CleaningOperation.id.asc()).all()
            ],
            "preview": preview,
        })
    payload = {
        "generator": "DataSure AI data export",
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "account": {
            "username": current_user.username,
            "created_at": current_user.created_at.isoformat(),
        },
        "datasets": dataset_payloads,
        "contracts": [
            {"id": c.id, "name": c.name, "description": c.description,
             "created_at": c.created_at.isoformat(),
             "contract_json": c.contract_json}
            for c in SchemaContract.query.filter_by(user_id=current_user.id)
            .order_by(SchemaContract.id.asc()).all()
        ],
        "rules": [
            {"id": r.id, "name": r.name, "rule_type": r.rule_type,
             "rule_json": r.rule_json,
             "created_at": r.created_at.isoformat()}
            for r in ValidationRule.query.filter_by(user_id=current_user.id)
            .order_by(ValidationRule.id.asc()).all()
        ],
        "audit_events": [
            {"id": e.id, "action": e.action,
             "dataset_id": e.dataset_id,
             "created_at": e.created_at.isoformat()}
            for e in AuditEvent.query.filter_by(user_id=current_user.id)
            .order_by(AuditEvent.id.asc()).all()
        ],
    }
    body = _json.dumps(payload, ensure_ascii=False, indent=2)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return send_file(
        io.BytesIO(body.encode("utf-8")),
        as_attachment=True,
        download_name=f"datasure_export_{current_user.username}_{stamp}.json",
        mimetype="application/json",
    )
