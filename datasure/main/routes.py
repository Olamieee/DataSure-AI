from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from ..extensions import db
from ..models import Dataset

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    from ..pagination import DEFAULT_PAGE_SIZE, paginate_stable
    page = request.args.get("page", 1, type=int)
    counts = (
        db.session.query(func.count(Dataset.id))
        .filter_by(user_id=current_user.id)
        .scalar()
    )
    result = paginate_stable(
        Dataset.query.filter_by(user_id=current_user.id)
        .order_by(Dataset.updated_at.desc()),
        page=page,
        per_page=DEFAULT_PAGE_SIZE,
    )
    datasets = result["items"]
    latest_scores = {
        dataset.id: latest_score_for(dataset) for dataset in datasets
    }
    totals = {"datasets": counts}
    return render_template(
        "main/dashboard.html",
        datasets=datasets,
        latest_scores=latest_scores,
        page=result,
        totals=totals,
    )


def latest_score_for(dataset: Dataset) -> float | None:
    latest = (
        dataset.assessments.filter_by(user_id=current_user.id)
        .order_by(Assessment.created_at.desc())
        .first()
    )
    return latest.quality_score if latest else None


from ..models import Assessment  # noqa: E402  (needed by latest_score_for)
