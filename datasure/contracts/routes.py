"""Schema contract management pages and dataset validation runs."""
from __future__ import annotations

from flask import (
    Blueprint,
    Response,
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
from .engine import contract_from_dataframe, summarise_contract, validate_dataframe
from ..models import Dataset, SchemaContract, db

bp = Blueprint("contracts", __name__)


def _owned_contract(contract_id: int) -> SchemaContract:
    contract = db.session.get(SchemaContract, contract_id)
    if contract is None or contract.user_id != current_user.id:
        abort(404)
    return contract


@bp.get("/")
@login_required
def list_contracts():
    from ..pagination import DEFAULT_PAGE_SIZE, paginate_stable

    page = request.args.get("page", 1, type=int)
    result = paginate_stable(
        SchemaContract.query.filter_by(user_id=current_user.id)
        .order_by(SchemaContract.created_at.desc(), SchemaContract.id.desc()),
        page=page,
        per_page=DEFAULT_PAGE_SIZE,
    )
    return render_template(
        "contracts/list.html", contracts=result["items"], page=result
    )


@bp.post("/create/<int:dataset_id>")
@login_required
def create_from_dataset(dataset_id: int):
    """Generate a new contract snapshot from an owned dataset's schema."""
    dataset = db.session.get(Dataset, dataset_id)
    if dataset is None or dataset.user_id != current_user.id:
        abort(404)
    name = (request.form.get("name") or "").strip()[:120]
    description = (request.form.get("description") or "").strip()[:500]
    if not name:
        flash("Give the contract a name.", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    try:
        df = load_dataset_dataframe(dataset)
    except DatasetParseError as exc:
        flash(f"Stored file could not be read: {exc}", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    record = SchemaContract(
        user_id=current_user.id,
        name=name,
        description=description or
        f"Generated from '{dataset.name}' ({df.shape[0]} rows × {df.shape[1]} columns).",
        contract_json=contract_from_dataframe(df, name),
    )
    db.session.add(record)
    db.session.commit()
    flash(f"Contract '{name}' created from this dataset.", "success")
    return redirect(url_for("contracts.detail", contract_id=record.id))


@bp.get("/<int:contract_id>")
@login_required
def detail(contract_id: int):
    contract = _owned_contract(contract_id)
    return render_template(
        "contracts/detail.html",
        contract=contract,
        rows=summarise_contract(contract.contract_json),
        datasets_used=contract.datasets.all(),
    )


@bp.get("/<int:contract_id>/export.schema.json")
@login_required
def export_json_schema(contract_id: int):
    """Download the contract as a portable JSON Schema (draft 2020-12)."""
    import json as _json

    from .schema_export import contract_to_json_schema

    contract = _owned_contract(contract_id)
    schema = contract_to_json_schema(contract.contract_json or {})
    schema["title"] = contract.name or schema["title"]

    safe = "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in contract.name
    )[:80] or "contract"
    body = _json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    return Response(
        body,
        mimetype="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename={safe}_schema.json"
            )
        },
    )


@bp.post("/<int:contract_id>/delete")
@login_required
def delete(contract_id: int):
    contract = _owned_contract(contract_id)
    name = contract.name
    db.session.delete(contract)
    from ..audit import record_audit

    record_audit("contract_deleted", current_user.id, name=name)
    db.session.commit()
    flash("Contract deleted. Uploaded datasets that used it are unaffected.", "info")
    return redirect(url_for("contracts.list_contracts"))


@bp.post("/validate/<int:dataset_id>")
@login_required
def validate_dataset(dataset_id: int):
    """Validate an owned dataset against a chosen contract (on demand)."""
    dataset = db.session.get(Dataset, dataset_id)
    if dataset is None or dataset.user_id != current_user.id:
        abort(404)
    contract_id = request.form.get("contract_id", type=int)
    contract = _owned_contract(contract_id or -1)
    try:
        df = load_dataset_dataframe(dataset)
    except DatasetParseError as exc:
        flash(f"Stored file could not be read: {exc}", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    violations = validate_dataframe(df, contract.contract_json)
    dataset.contract_id = contract.id
    dataset.contract_passed = not violations
    db.session.commit()
    if violations:
        return render_template(
            "contracts/violations.html",
            dataset=dataset,
            contract=contract,
            violations=violations,
        )
    flash(f"Dataset satisfies contract '{contract.name}'.", "success")
    return redirect(url_for("datasets.detail", dataset_id=dataset.id))
