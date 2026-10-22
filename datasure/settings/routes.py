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


@bp.get("/activity")
@login_required
def activity():
    """Your audit trail: recorded actions only you can see."""
    from ..models import AuditEvent
    from ..pagination import paginate_stable

    page = request.args.get("page", 1, type=int)
    result = paginate_stable(
        AuditEvent.query.filter_by(user_id=current_user.id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()),
        page=page,
        per_page=25,
    )
    return render_template(
        "settings/activity.html",
        events=result["items"],
        page=result,
    )
