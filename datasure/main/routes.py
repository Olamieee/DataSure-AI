from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

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
    datasets = (
        Dataset.query.filter_by(user_id=current_user.id)
        .order_by(Dataset.updated_at.desc())
        .limit(50)
        .all()
    )
    latest_scores = {
        dataset.id: latest_score_for(dataset) for dataset in datasets
    }
    return render_template("main/dashboard.html", datasets=datasets, latest_scores=latest_scores)


def latest_score_for(dataset: Dataset) -> float | None:
    latest = (
        dataset.assessments.filter_by(user_id=current_user.id)
        .order_by(Assessment.created_at.desc())
        .first()
    )
    return latest.quality_score if latest else None


from ..models import Assessment  # noqa: E402  (needed by latest_score_for)
