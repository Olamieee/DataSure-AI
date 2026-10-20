"""Web pages for managing and running reusable validation rules."""
from __future__ import annotations

import json

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..assessment import load_dataset_dataframe
from ..datasets.ingest import DatasetParseError
from .engine import COMPARISON_OPERATORS, RULE_TYPES, RuleDefinitionError, \
    normalise_rule, run_rules
from ..models import Dataset, ValidationRule, db

__all__ = ["bp", "COMPARISON_OPERATORS", "RULE_TYPES", "RuleDefinitionError",
           "Dataset", "ValidationRule", "db", "normalise_rule", "run_rules"]


bp = Blueprint("rules", __name__)


def _owned_rule(rule_id: int) -> ValidationRule:
    rule = db.session.get(ValidationRule, rule_id)
    if rule is None or rule.user_id != current_user.id:
        abort(404)
    return rule


@bp.get("/")
@login_required
def list_rules():
    rules = (
        ValidationRule.query.filter_by(user_id=current_user.id)
        .order_by(ValidationRule.created_at.desc())
        .all()
    )
    return render_template("rules/list.html", rules=rules,
                           rule_types=RULE_TYPES)


def _form_to_rule_json() -> tuple[str, dict]:
    """Build (rule_type, rule_json) from the create form fields."""
    rule_type = request.form.get("rule_type") or ""
    if rule_type not in RULE_TYPES:
        raise RuleDefinitionError("Choose a rule type.")
    severity = request.form.get("severity") or "error"
    if rule_type == "numeric_range":
        rule_json: dict = {"column": request.form.get("column", "")}
        for key in ("min", "max"):
            value = request.form.get(key, "").strip()
            if value != "":
                rule_json[key] = value  # numeric parsing handled by normalise_rule
        rule_json["inclusive"] = request.form.get("inclusive") == "on"
    elif rule_type == "allowed_values":
        raw = request.form.get("values", "")
        rule_json = {
            "column": request.form.get("column", ""),
            "values": [value.strip() for value in raw.split(",") if value.strip()],
        }
    elif rule_type == "column_comparison":
        rule_json = {
            "left": request.form.get("left", ""),
            "operator": request.form.get("operator", ""),
            "right": request.form.get("right", ""),
        }
    else:  # unique / not_null
        rule_json = {"column": request.form.get("column", "")}
    rule_json["severity"] = severity
    return rule_type, rule_json


@bp.post("/create")
@login_required
def create_rule():
    name = (request.form.get("name") or "").strip()[:120]
    if not name:
        flash("Give the rule a name.", "warning")
        return redirect(url_for("rules.list_rules"))
    try:
        rule_type, rule_json = _form_to_rule_json()
        normalised = normalise_rule(rule_type, rule_json)
    except RuleDefinitionError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("rules.list_rules"))
    record = ValidationRule(user_id=current_user.id, name=name,
                            rule_type=rule_type, rule_json=normalised)
    db.session.add(record)
    db.session.commit()
    flash(f"Rule '{name}' saved. It is now available to run on any dataset.", "success")
    return redirect(url_for("rules.list_rules"))


@bp.post("/<int:rule_id>/delete")
@login_required
def delete_rule(rule_id: int):
    rule = _owned_rule(rule_id)
    name, rule_type = rule.name, rule.rule_type
    db.session.delete(rule)
    from ..audit import record_audit

    record_audit("rule_deleted", current_user.id, name=name, rule_type=rule_type)
    db.session.commit()
    flash("Rule deleted.", "info")
    return redirect(url_for("rules.list_rules"))


@bp.post("/run/<int:dataset_id>")
@login_required
def run_on_dataset(dataset_id: int):
    """Run the current user's selected rules against an owned dataset."""
    dataset = db.session.get(Dataset, dataset_id)
    if dataset is None or dataset.user_id != current_user.id:
        abort(404)
    rule_ids = request.form.getlist("rule_ids") or request.form.getlist("rule_ids[]")
    try:
        wanted = {int(value) for value in rule_ids}
    except ValueError:
        flash("Invalid rule selection.", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    rules = (
        ValidationRule.query.filter(
            ValidationRule.user_id == current_user.id,
            ValidationRule.id.in_(wanted) if wanted else db.false(),
        ).all()
    ) if wanted else []
    if not rules:
        flash("Select at least one rule to run.", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    try:
        df = load_dataset_dataframe(dataset)
    except DatasetParseError as exc:
        flash(f"Stored file could not be read: {exc}", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    results = run_rules(df, rules)
    failed = sum(1 for result in results if not result["passed"])
    passed = len(results) - failed
    flash(f"Ran {len(results)} rule(s): {passed} passed, {failed} raised issues.",
          "success" if failed == 0 else "warning")
    return render_template(
        "rules/results.html",
        dataset=dataset,
        results=results,
        passed=passed,
        failed=failed,
    )


@bp.get("/api-options")
@login_required
def api_options():
    """Small JSON payload describing the fixed rule registry (for the UI)."""
    return {
        "rule_types": list(RULE_TYPES),
        "operators": sorted(COMPARISON_OPERATORS),
    }


def _rule_payload(rule: ValidationRule) -> str:
    return json.dumps(rule.rule_json, sort_keys=True)
