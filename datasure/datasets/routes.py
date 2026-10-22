"""Dataset blueprint: upload, view, assess, clean, download, delete."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..assessment import load_dataset_dataframe, run_assessment
from ..profiling.profile import ProfilingTimeout
from ..datasets.ingest import dataset_preview, dataframe_schema
from ..models import Assessment, CleaningOperation, Dataset, SchemaContract, ValidationRule, db
from ..storage import delete_file, sanitize_display_name, user_upload_dir
from .ingest import DatasetParseError, parse_uploaded_dataset

bp = Blueprint("datasets", __name__)


def _owned_dataset(dataset_id: int) -> Dataset:
    """Fetch a dataset owned by the current user, else 404."""
    dataset = db.session.get(Dataset, dataset_id)
    if dataset is None or dataset.user_id != current_user.id:
        abort(404)
    return dataset


@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        file_storage = request.files.get("file")
        if file_storage is None or not file_storage.filename:
            flash("Choose a CSV, TSV or Excel file to upload.", "danger")
            return render_template("datasets/upload.html"), 400
        try:
            (df, storage_filename, extension, sha256, rows, columns) = parse_uploaded_dataset(
                file_storage=file_storage,
                allowed_extensions=set(current_app.config["ALLOWED_EXTENSIONS"]),
                instance_path=current_app.instance_path,
                user_id=current_user.id,
                max_rows=current_app.config["MAX_ROWS"],
                max_columns=current_app.config["MAX_COLUMNS"],
            )
        except DatasetParseError as exc:
            message = str(exc)
            if exc.hint:
                message = f"{message} Hint: {exc.hint}"
            flash(message, "danger")
            return render_template("datasets/upload.html"), 400

        display_name = sanitize_display_name(file_storage.filename)
        duplicate = (
            Dataset.query.filter_by(user_id=current_user.id, sha256=sha256)
            .order_by(Dataset.created_at.desc(), Dataset.id.desc())
            .first()
        )
        dataset = Dataset(
            user_id=current_user.id,
            name=display_name,
            storage_filename=storage_filename,
            original_filename=display_name,
            extension=extension,
            size_bytes=int((Path(current_app.instance_path) / "uploads" / f"user_{current_user.id}" / storage_filename).stat().st_size),
            sha256=sha256,
            row_count=rows,
            column_count=columns,
            status="parsed",
        )
        db.session.add(dataset)
        db.session.commit()
        if duplicate is not None:
            flash(
                f"Note: you already uploaded identical file content as "
                f"'{duplicate.name}' (dataset #{duplicate.id}).",
                "warning",
            )
        flash("Dataset uploaded successfully. Run an assessment below.", "success")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))

    return render_template("datasets/upload.html")


@bp.route("/")
@login_required
def list_datasets():
    return redirect(url_for("main.dashboard"))


@bp.route("/history")
@login_required
def history_all():
    """Cross-dataset assessment history for the current user."""
    from ..pagination import DEFAULT_PAGE_SIZE, paginate_stable

    datasets = (
        Dataset.query.filter_by(user_id=current_user.id)
        .order_by(Dataset.name.asc())
        .all()
    )
    selected_id = request.args.get("dataset_id", type=int)
    selected = None
    page_state = None
    if selected_id:
        selected = db.session.get(Dataset, selected_id)
        if selected is None or selected.user_id != current_user.id:
            abort(404)
    else:
        selected = next(iter(datasets), None)
    if selected is not None:
        page = request.args.get("page", 1, type=int)
        page_state = paginate_stable(
            selected.assessments.order_by(Assessment.created_at.desc(),
                                          Assessment.id.desc()),
            page=page,
            per_page=DEFAULT_PAGE_SIZE,
        )
        assessments = page_state["items"]
    else:
        assessments = []
    return render_template(
        "datasets/history_all.html",
        datasets=datasets,
        selected=selected,
        assessments=assessments,
        page=page_state,
    )


def _quality_trend(dataset: Dataset, max_points: int = 8) -> list[dict]:
    """Oldest-to-newest quality scores with per-step deltas (for the detail page)."""
    rows = (
        dataset.assessments.order_by(Assessment.created_at.asc(),
                                     Assessment.id.asc()).all()
    )
    trend: list[dict] = []
    previous: float | None = None
    for row in rows[-max_points:]:
        delta = None if previous is None else round(
            row.quality_score - previous, 1
        )
        trend.append(
            {"assessment_id": row.id, "score": row.quality_score,
             "created_at": row.created_at, "delta": delta}
        )
        previous = row.quality_score
    return trend


@bp.route("/<int:dataset_id>")
@login_required
def detail(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    latest = (
        dataset.assessments.order_by(Assessment.created_at.desc()).first()
    )
    df = None
    schema = None
    preview = None
    try:
        df = load_dataset_dataframe(dataset)
        schema = dataframe_schema(df)
        preview = dataset_preview(df, current_app.config["PREVIEW_ROWS"])
    except DatasetParseError as exc:
        flash(f"Stored file could not be read: {exc}", "warning")
    context = {
        "dataset": dataset,
        "latest_assessment": latest,
        "quality_trend": _quality_trend(dataset),
        "schema": schema,
        "preview": preview,
        "user_contracts": (
            SchemaContract.query.filter_by(user_id=current_user.id)
            .order_by(SchemaContract.name.asc())
            .all()
        ),
        "user_rules": (
            ValidationRule.query.filter_by(user_id=current_user.id)
            .order_by(ValidationRule.name.asc())
            .all()
        ),
        "max_upload_mb": int(current_app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024)),
        "registrations": None,
    }
    return render_template("datasets/detail.html", **context)


@bp.route("/<int:dataset_id>/assess", methods=["POST"])
@login_required
def assess(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    target = (request.form.get("target_column") or "").strip() or None
    label = (request.form.get("label") or "").strip() or None
    validated_target = None
    if target:
        try:
            df = load_dataset_dataframe(dataset)
        except DatasetParseError as exc:
            flash(f"Stored file could not be read: {exc}", "warning")
            return redirect(url_for("datasets.detail", dataset_id=dataset.id))
        if target not in df.columns:
            flash(f"Target column '{target}' is not present in the dataset.", "danger")
            return redirect(url_for("datasets.detail", dataset_id=dataset.id))
        validated_target = target
    try:
        assessment = run_assessment(dataset, target_column=validated_target, label=label)
    except DatasetParseError as exc:
        flash(f"Assessment failed: {exc}", "danger")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    except ProfilingTimeout as exc:
        flash(
            f"Analysis stopped: {exc} Try a smaller dataset or ask an "
            "administrator to raise the profiling time budget.", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    except Exception as exc:  # unexpected analysis failure
        current_app.logger.exception("Assessment crashed for dataset %s", dataset.id)
        flash(f"Assessment failed unexpectedly: {type(exc).__name__}. The issue was logged.", "danger")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    flash(f"Assessment completed in {assessment.duration_ms} ms.", "success")
    return redirect(url_for("datasets.assessment", dataset_id=dataset.id, assessment_id=assessment.id))


@bp.route("/<int:dataset_id>/assessments/<int:assessment_id>")
@login_required
def assessment(dataset_id: int, assessment_id: int):
    dataset = _owned_dataset(dataset_id)
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None or assessment.dataset_id != dataset.id:
        abort(404)
    previous = (
        Assessment.query.filter(Assessment.dataset_id == dataset.id,
                                Assessment.id < assessment.id)
        .order_by(Assessment.id.desc())
        .first()
    )
    return render_template("datasets/assessment.html",
                           dataset=dataset, assessment=assessment, previous=previous)


@bp.route("/<int:dataset_id>/assessments/<int:assessment_id>/report")
@login_required
def assessment_report(dataset_id: int, assessment_id: int):
    """Downloadable quality report (HTML by default, JSON with ?format=json)."""
    dataset = _owned_dataset(dataset_id)
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None or assessment.dataset_id != dataset.id:
        abort(404)
    operations = (
        dataset.cleaning_operations.order_by(CleaningOperation.created_at.asc()).all()
    )
    from ..reports import generate_html_report, generate_json_report

    report_format = request.args.get("format", "html").lower()
    if report_format == "json":
        content = generate_json_report(dataset, assessment, operations)
        return send_file(
            io.BytesIO(content.encode("utf-8")),
            as_attachment=True,
            download_name=f"datasure_report_dataset{dataset.id}_assessment{assessment.id}.json",
            mimetype="application/json",
        )
    content = generate_html_report(dataset, assessment, operations, current_user)
    return send_file(
        io.BytesIO(content.encode("utf-8")),
        as_attachment=True,
        download_name=f"datasure_report_dataset{dataset.id}_assessment{assessment.id}.html",
        mimetype="text/html",
    )


@bp.route("/<int:dataset_id>/delete", methods=["POST"])
@login_required
def delete(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    remove_dataset(dataset, current_user.id)
    flash("Dataset deleted.", "info")
    return redirect(url_for("main.dashboard"))


def remove_dataset(dataset: Dataset, actor_id: int) -> None:
    """Shared deletion path for the web view and the API.

    Deletes the stored file, records the audit event and removes the row
    (including dependent assessments, cleaning ops and rule results).
    """
    upload_dir = user_upload_dir(current_app.instance_path, dataset.user_id)
    delete_file(upload_dir / dataset.storage_filename)
    from ..audit import record_audit

    record_audit("dataset_deleted", actor_id, dataset_id=dataset.id,
                 name=dataset.name)
    db.session.delete(dataset)
    db.session.commit()


@bp.route("/<int:dataset_id>/download")
@login_required
def download(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    path = user_upload_dir(current_app.instance_path, dataset.user_id) / dataset.storage_filename
    if not path.exists():
        abort(404)
    download_name = _download_name(dataset)
    return send_file(path, as_attachment=True, download_name=download_name)


@bp.route("/<int:dataset_id>/export/<export_kind>.csv")
@login_required
def export_csv(dataset_id: int, export_kind: str):
    """Download a CSV export: latest assessment findings, stats or history."""
    if export_kind not in {"issues", "stats", "history"}:
        abort(404)
    dataset = _owned_dataset(dataset_id)
    if export_kind == "history":
        history_rows = _history_rows(dataset)
        if history_rows is None:
            flash("No cleaning operations recorded yet.", "info")
            return redirect(url_for("datasets.cleaning_history",
                                    dataset_id=dataset.id))
        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL,
                            lineterminator="\r\n")
        for row in history_rows:
            writer.writerow(row)
        download_name = _download_name(dataset).replace(
            dataset.extension.lstrip(".") or "csv", "_history.csv"
        )
        return Response(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={download_name}"},
        )
    assessment = (
        Assessment.query.filter_by(dataset_id=dataset.id)
        .order_by(Assessment.created_at.desc())
        .first()
    )
    if assessment is None:
        flash("Run an assessment first; exports summarise the latest assessment.", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))

    rows = _export_rows(assessment, export_kind)
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
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


def _csv_safe(value) -> object:
    """Neutralise CSV formula injection: '=1+1' must never execute in Excel."""
    if isinstance(value, str) and value[:1] in {"=", "+", "@"}:
        return "'" + value
    return value


def _export_rows(assessment: Assessment, export_kind: str) -> list[list]:
    """Plain tabular rows for CSV export (strings, no nested types)."""
    if export_kind == "issues":
        header = ["kind", "severity", "columns", "message"]
        rows = [header]
        for issue in assessment.issues_json or []:
            rows.append([
                str(issue.get("kind", "")),
                str(issue.get("severity", "")),
                ", ".join(str(c) for c in issue.get("columns", []) or []),
                str(issue.get("message", "")),
            ])
        return [[_csv_safe(cell) for cell in row] for row in rows]

    # stats export: one row per column of the profile
    header = [
        "column", "dtype", "kind", "non_null", "missing", "missing_pct",
        "unique", "constant", "is_identifier",
    ]
    rows = [header]
    for column in (assessment.profile_json or {}).get("columns", []):
        stats = column.get("stats") or {}
        rows.append([
            str(column.get("name", "")),
            str(column.get("pandas_dtype", "")),
            str(column.get("kind", "")),
            str(column.get("non_null", "")),
            str(column.get("missing", "")),
            str(column.get("missing_pct", "")),
            str(column.get("unique", "")),
            str(bool(column.get("constant", False))),
            str(bool(column.get("is_identifier", False))),
            *(str(stats[key]) if key in stats else "" for key in
              ("min", "max", "mean", "std", "median")),
        ])
    header += ["min", "max", "mean", "std", "median"]
    rows[0] = header
    return [[_csv_safe(cell) for cell in row] for row in rows]


def _history_rows(dataset: Dataset) -> list[list] | None:
    """Tabular rows of the dataset's cleaning-operation history, oldest first."""
    operations = (
        dataset.cleaning_operations.order_by(
            CleaningOperation.created_at.asc(), CleaningOperation.id.asc()
        ).all()
    )
    if not operations:
        return None
    header = [
        "when", "operation", "rows_before", "rows_after",
        "columns_before", "columns_after", "cells_changed", "success",
    ]
    rows = [header]
    for op in operations:
        rows.append([
            op.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            op.operation,
            op.rows_before,
            op.rows_after,
            op.columns_before,
            op.columns_after,
            op.cells_changed,
            "yes" if op.success else "no",
        ])
    return [[_csv_safe(cell) for cell in row] for row in rows]


def _download_name(dataset: Dataset) -> str:
    stem = Path(dataset.original_filename).stem or "dataset"
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in stem)
    suffix = "_v{version}".format(version=dataset.storage_version) if dataset.storage_version > 1 else ""
    return f"{safe}{suffix}{dataset.extension}"


def _latest_assessment(dataset: Dataset) -> Assessment | None:
    return (
        Assessment.query.filter_by(dataset_id=dataset.id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .first()
    )


def normalise_tags(raw: str) -> list[str] | None:
    """Comma-separated, trimmed, de-duplicated tags (case-insensitive dedupe).

    Returns ``None`` when the result would be too large to store.
    """
    seen: list[str] = []
    for chunk in (raw or "").split(","):
        tag = chunk.strip()[:40]
        if tag and tag.lower() not in {s.lower() for s in seen}:
            seen.append(tag)
    if len(seen) > 10 or len(",".join(seen)) > 300:
        return None
    return seen


def _tags_route(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    raw = request.form.get("tags") or ""
    tags = normalise_tags(raw)
    if tags is None:
        flash("Too many tags: at most 10 tags of 40 characters each.", "danger")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    dataset.tags = ",".join(tags)
    db.session.commit()
    if tags:
        flash(f"Tags updated: {', '.join(tags)}", "info")
    else:
        flash("Tags cleared.", "info")
    return redirect(url_for("datasets.detail", dataset_id=dataset.id))


@bp.route("/<int:dataset_id>/tags", methods=["POST"])
@login_required
def set_tags(dataset_id: int):
    """Replace the dataset's free-form tags."""
    return _tags_route(dataset_id)


def _markdown_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _dictionary_markdown(dataset: Dataset, assessment: Assessment) -> str:
    """Render the latest profile as a human-readable Markdown dictionary."""
    from datetime import datetime, timezone

    columns = (assessment.profile_json or {}).get("columns", [])
    lines = [
        f"# Data dictionary: {dataset.name}",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} from "
        f"assessment #{assessment.id} "
        f"({dataset.row_count} rows, {dataset.column_count} columns).",
        "",
        "| Column | Type | Kind | Non-null | Missing | Unique | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for column in columns:
        stats = column.get("stats") or {}
        notes: list[str] = []
        if column.get("constant"):
            notes.append("constant")
        if column.get("is_identifier"):
            notes.append("likely identifier")
        if stats.get("min") is not None and column.get("kind") == "numeric":
            notes.append(f"range {stats['min']} … {stats['max']}")
        non_null = column.get("non_null", "")
        missing = column.get("missing", "")
        missing_pct = column.get("missing_pct")
        missing_cell = (
            f"{missing} ({missing_pct}%)" if missing_pct is not None else missing
        )
        lines.append(
            "| {name} | {dtype} | {kind} | {non_null} | {missing} | {unique} | {notes} |".format(
                name=_markdown_escape(str(column.get("name", ""))),
                dtype=_markdown_escape(str(column.get("pandas_dtype", ""))),
                kind=_markdown_escape(str(column.get("kind", ""))),
                non_null=non_null,
                missing=missing_cell,
                unique=column.get("unique", ""),
                notes=_markdown_escape("; ".join(notes)),
            )
        )
    lines.append("")
    lines.append(
        "Types are pandas dtypes observed while assessing data quality; "
        "'kind' is the heuristic profile family. No dataset values are "
        "included in the dictionary."
    )
    return "\n".join(lines)


@bp.route("/<int:dataset_id>/dictionary")
@login_required
def data_dictionary(dataset_id: int):
    """Download the data dictionary (Markdown, or ?format=json)."""
    dataset = _owned_dataset(dataset_id)
    assessment = _latest_assessment(dataset)
    if assessment is None:
        flash("Run an assessment first; the dictionary is built from the profile.", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))

    columns = (assessment.profile_json or {}).get("columns", [])
    if request.args.get("format") == "json":
        payload = {
            "dataset": dataset.name,
            "dataset_id": dataset.id,
            "assessment_id": assessment.id,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "columns": columns,
        }
        response = jsonify(payload)
        download_name = _download_name(dataset).replace(
            dataset.extension.lstrip(".") or "csv", "_dictionary.json"
        )
        response.headers["Content-Disposition"] = (
            f"attachment; filename={download_name}"
        )
        return response

    markdown = _dictionary_markdown(dataset, assessment)
    download_name = _download_name(dataset).replace(
        dataset.extension.lstrip(".") or "csv", "_dictionary.md"
    )
    return Response(
        markdown,
        mimetype="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={download_name}"},
    )


# ---------------------------------------------------------------------------
# Cleaning endpoints
# ---------------------------------------------------------------------------
@bp.route("/<int:dataset_id>/clean")
@login_required
def clean(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    try:
        df = load_dataset_dataframe(dataset)
    except DatasetParseError as exc:
        flash(f"Stored file could not be read: {exc}", "warning")
        return redirect(url_for("datasets.detail", dataset_id=dataset.id))
    from ..profiling.profile import profile_dataset
    from ..cleaning.engine import REGISTRY, suggest_operations

    profile_stub = profile_dataset(df.head(2000)) if len(df) > 2000 else profile_dataset(df)
    suggestions = suggest_operations(df, profile_stub)
    operations = [
        {"name": name, "label": entry["label"], "description": entry["description"],
         "params": entry["params"]}
        for name, entry in REGISTRY.items()
    ]
    return render_template(
        "datasets/clean.html",
        dataset=dataset,
        df=df,
        suggestions=suggestions,
        operations=operations,
    )


@bp.route("/<int:dataset_id>/clean/preview", methods=["POST"])
@login_required
def clean_preview(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    payload = _clean_payload_or_fail(dataset)
    if payload is None:
        return redirect(url_for("datasets.clean", dataset_id=dataset.id))
    operation, params = payload
    try:
        df = load_dataset_dataframe(dataset)
        result = _apply_single(df, operation, params)
    except (DatasetParseError, ValueError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("datasets.clean", dataset_id=dataset.id))
    rows_removed = len(df) - len(result)
    cells_changed = _cells_changed(df, result)
    return render_template(
        "datasets/clean_preview.html",
        dataset=dataset,
        operation=operation,
        params=params,
        rows_before=len(df),
        rows_after=len(result),
        columns_before=df.shape[1],
        columns_after=result.shape[1],
        rows_removed=rows_removed,
        cells_changed=cells_changed,
        preview=dataset_preview(result, 15),
        head_before=dataset_preview(df, 5),
        head_after=dataset_preview(result.head(5), 5),
    )


@bp.route("/<int:dataset_id>/clean/apply", methods=["POST"])
@login_required
def clean_apply(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    payload = _clean_payload_or_fail(dataset)
    if payload is None:
        return redirect(url_for("datasets.clean", dataset_id=dataset.id))
    operation, params = payload
    try:
        df = load_dataset_dataframe(dataset)
        result = _apply_single(df, operation, params)
    except (DatasetParseError, ValueError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("datasets.clean", dataset_id=dataset.id))

    filename = _write_cleaned_file(dataset, result)

    operation_record = CleaningOperation(
        dataset_id=dataset.id,
        user_id=current_user.id,
        operation=operation,
        params_json=params,
        result_filename=filename,
        rows_before=int(len(df)),
        rows_after=int(len(result)),
        columns_before=int(df.shape[1]),
        columns_after=int(result.shape[1]),
        cells_changed=_cells_changed(df, result),
        success=True,
        message="Applied successfully.",
    )
    dataset.storage_filename = filename
    dataset.storage_version += 1
    dataset.is_cleaned = True
    dataset.row_count = int(len(result))
    dataset.column_count = int(result.shape[1])
    dataset.size_bytes = _file_size_bytes(current_app, dataset.user_id, filename)
    db.session.add(operation_record)

    from ..audit import record_audit

    record_audit("cleaning_applied", current_user.id, dataset_id=dataset.id,
                 operation=operation, version=dataset.storage_version + 1)
    db.session.commit()
    flash(f"Cleaning operation '{operation}' applied and recorded.", "success")
    return redirect(url_for("datasets.clean", dataset_id=dataset.id))


@bp.route("/<int:dataset_id>/history")
@login_required
def cleaning_history(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    operations = (
        CleaningOperation.query.filter_by(dataset_id=dataset.id)
        .order_by(CleaningOperation.created_at.desc())
        .all()
    )
    assessments = (
        Assessment.query.filter_by(dataset_id=dataset.id)
        .order_by(Assessment.created_at.desc())
        .all()
    )
    from ..audit import dataset_events

    return render_template(
        "datasets/history.html", dataset=dataset, operations=operations,
        assessments=assessments, audit_events=dataset_events(dataset.id, current_user.id),
    )


@bp.route("/<int:dataset_id>/compare")
@login_required
def compare(dataset_id: int):
    """Side-by-side comparison of two assessments of this dataset."""
    dataset = _owned_dataset(dataset_id)
    id_from = request.args.get("from", type=int)
    id_to = request.args.get("to", type=int)
    if not id_from or not id_to:
        flash("Choose two assessments to compare.", "warning")
        return redirect(url_for("datasets.history_all", dataset_id=dataset.id))
    if id_from == id_to:
        flash("Select two different assessments.", "warning")
        return redirect(url_for("datasets.history_all", dataset_id=dataset.id))
    assessment_from = db.session.get(Assessment, id_from)
    assessment_to = db.session.get(Assessment, id_to)
    if (assessment_from is None or assessment_to is None
            or assessment_from.dataset_id != dataset.id
            or assessment_to.dataset_id != dataset.id):
        abort(404)
    from ..profiling.compare import compare_assessments

    result = compare_assessments(assessment_from, assessment_to)
    return render_template(
        "datasets/compare.html",
        dataset=dataset,
        assessment_from=assessment_from,
        assessment_to=assessment_to,
        result=result,
    )


# helpers --------------------------------------------------------------------
def _clean_payload_or_fail(dataset: Dataset):
    if not request.form.get("operation"):
        flash("Choose a cleaning operation.", "danger")
        return None
    operation = request.form["operation"].strip()
    params: dict = {}
    for key in request.form:
        if key.startswith("param_"):
            params[key[len("param_"):]] = request.form.get(key)
    columns = request.form.getlist("columns")
    if columns:
        params["columns"] = columns

    # Optimistic concurrency: the preview page records which version the user
    # based the operation on. If another action (assessment, earlier apply,
    # background job) changed the dataset since then, apply is refused.
    expected_version = request.form.get("expected_version")
    if expected_version:
        try:
            if int(expected_version) != dataset.storage_version:
                flash(
                    "The dataset changed since this preview was created "
                    f"(currently version {dataset.storage_version}, preview "
                    f"based on version {expected_version}). Re-open the cleaning "
                    "workspace and apply again.",
                    "warning",
                )
                return None
        except ValueError:
            flash("Invalid version reference; re-open the cleaning workspace.",
                  "warning")
            return None
    return operation, params


def _apply_single(df, operation: str, params: dict):
    from ..cleaning.engine import apply_operation

    return apply_operation(df, operation, params)


def _cells_changed(before, after) -> int:
    try:
        same = before.equals(after)
        if same:
            return 0
    except Exception:
        return -1
    changed = 0
    try:
        common_columns = [c for c in before.columns if c in after.columns]
        a = before[common_columns].fillna("<NA>").astype(str)
        b = after[common_columns].fillna("<NA>").astype(str)
        changed = int((a.to_numpy() != b[: len(a)].to_numpy()).sum())
    except Exception:
        changed = -1
    return changed


def _write_cleaned_file(dataset: Dataset, result, ) -> str:
    from ..storage import generate_storage_filename

    upload_dir = user_upload_dir(current_app.instance_path, dataset.user_id)
    filename = generate_storage_filename(dataset.extension)
    destination = upload_dir / filename
    if dataset.extension in {".xlsx", ".xls"}:
        result.to_excel(destination, index=False)
    else:
        delimiter = "\t" if dataset.extension == ".tsv" else ","
        result.to_csv(destination, index=False, sep=delimiter)
    return filename


def _file_size_bytes(app, user_id: int, filename: str) -> int:
    try:
        return (Path(user_upload_dir(app.instance_path, user_id)) / filename).stat().st_size
    except OSError:
        return 0
