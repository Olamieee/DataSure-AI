"""Dataset blueprint: upload, view, assess, clean, download, delete."""
from __future__ import annotations

import io
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..assessment import load_dataset_dataframe, run_assessment
from ..datasets.ingest import dataset_preview, dataframe_schema
from ..models import Assessment, CleaningOperation, Dataset, db
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
    datasets = (
        Dataset.query.filter_by(user_id=current_user.id)
        .order_by(Dataset.name.asc())
        .all()
    )
    selected_id = request.args.get("dataset_id", type=int)
    selected = None
    assessments = []
    if selected_id:
        selected = db.session.get(Dataset, selected_id)
        if selected is None or selected.user_id != current_user.id:
            abort(404)
    else:
        selected = next(iter(datasets), None)
    if selected is not None:
        assessments = (
            selected.assessments.order_by(Assessment.created_at.desc()).limit(50).all()
        )
    return render_template(
        "datasets/history_all.html",
        datasets=datasets,
        selected=selected,
        assessments=assessments,
    )


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
        "schema": schema,
        "preview": preview,
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
    upload_dir = user_upload_dir(current_app.instance_path, dataset.user_id)
    delete_file(upload_dir / dataset.storage_filename)
    db.session.delete(dataset)
    db.session.commit()
    flash("Dataset deleted.", "info")
    return redirect(url_for("main.dashboard"))


@bp.route("/<int:dataset_id>/download")
@login_required
def download(dataset_id: int):
    dataset = _owned_dataset(dataset_id)
    path = user_upload_dir(current_app.instance_path, dataset.user_id) / dataset.storage_filename
    if not path.exists():
        abort(404)
    download_name = _download_name(dataset)
    return send_file(path, as_attachment=True, download_name=download_name)


def _download_name(dataset: Dataset) -> str:
    stem = Path(dataset.original_filename).stem or "dataset"
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in stem)
    suffix = "_v{version}".format(version=dataset.storage_version) if dataset.storage_version > 1 else ""
    return f"{safe}{suffix}{dataset.extension}"


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
    return render_template(
        "datasets/history.html", dataset=dataset, operations=operations,
        assessments=assessments,
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
