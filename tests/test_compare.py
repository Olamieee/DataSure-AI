"""Tests for assessment comparison: scores, issue deltas, compatibility."""
from __future__ import annotations

import io


def _upload_csv(client, content: str, name: str = "compare.csv") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(content.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.data[:200]
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


CLEAN_CSV = "name,age\nA,29\nB,30\nC,31\nD,32\n"


def _assess(client, dataset_id: int, label: str):
    resp = client.post(
        f"/datasets/{dataset_id}/assess", data={"label": label},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_identical_assessments_show_zero_deltas(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_csv(client, CLEAN_CSV)
    id_a = _assess(client, dataset_id, "a")
    id_b = _assess(client, dataset_id, "b")
    resp = client.get(f"/datasets/{dataset_id}/compare?from={id_a}&to={id_b}")
    assert resp.status_code == 200
    assert b"no change" in resp.data
    assert b"No new issues were introduced" in resp.data
    assert b"No issue severity changed" in resp.data


def test_improved_assessment_shows_progress(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_csv(client, CLEAN_CSV)
    from datasure.models import Assessment, db
    with app.app_context():
        # simulate an earlier, worse assessment
        worse = db.session.get(Assessment, _assess(client, dataset_id, "later"))
        worse.quality_score = worse.quality_score - 20
        worse.scores_json["overall"] = worse.scores_json["overall"] - 20
        for dimension in worse.scores_json["dimensions"].values():
            dimension["score"] = max(dimension["score"] - 20, 0)
        db.session.commit()
        ids = db.session.query(Assessment.id).filter_by(dataset_id=dataset_id).all()
        id_b = _assess(client, dataset_id, "now")
        worse_id = min(idx for (idx,) in ids)
    resp = client.get(f"/datasets/{dataset_id}/compare?from={worse_id}&to={id_b}")
    assert resp.status_code == 200
    assert b"improved" in resp.data


def test_degraded_assessment_shows_regression_and_new_issues(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_csv(client, CLEAN_CSV)
    id_first = _assess(client, dataset_id, "clean start")

    # overwrite stored file with a messier version (simulating cleaning gone wrong)
    from pathlib import Path
    from datasure.models import Dataset, db
    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        path = Path(app.instance_path) / "uploads" / f"user_{logged_in_user['user_id']}" / dataset.storage_filename
    path.write_text("name,age\nA,\nC,\nD,32\nE,99\nA,29\n", encoding="utf-8")
    id_second = _assess(client, dataset_id, "after damage")
    resp = client.get(f"/datasets/{dataset_id}/compare?from={id_first}&to={id_second}")
    assert resp.status_code == 200
    assert b"degraded" in resp.data


def test_incompatible_schema_warned(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_csv(client, CLEAN_CSV)
    id_first = _assess(client, dataset_id, "original")
    from datasure.models import Assessment, Dataset

    # modify stored file to have different columns
    from pathlib import Path
    from datasure.models import Dataset, db
    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        path = Path(app.instance_path) / "uploads" / f"user_{logged_in_user['user_id']}" / dataset.storage_filename
    path.write_text("name,age,city\nA,29,X\nB,30,Y\nC,31,Z\nD,32,X\n", encoding="utf-8")
    id_second = _assess(client, dataset_id, "with city column")
    resp = client.get(f"/datasets/{dataset_id}/compare?from={id_first}&to={id_second}")
    assert resp.status_code == 200
    assert b"structure changed" in resp.data
    assert b"city" in resp.data


def test_compare_requires_two_assessments(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_csv(client, CLEAN_CSV)
    resp = client.get(f"/datasets/{dataset_id}/compare", follow_redirects=True)
    assert b"Choose two assessments to compare" in resp.data
    resp = client.get("/datasets/999/compare?from=1&to=2", follow_redirects=False)
    assert resp.status_code == 404


def test_cross_dataset_compare_blocked(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    dataset_id = _upload_csv(client, CLEAN_CSV)
    id_a = _assess(client, dataset_id, "first")
    # second user uploads and assesses own dataset N2
    own_id = _upload_csv(second_user, CLEAN_CSV, "other.csv")
    id_b = _assess(second_user, own_id, "their")
    resp = second_user.get(
        f"/datasets/{dataset_id}/compare?from={id_a}&to={id_b}"
    )
    assert resp.status_code == 404  # dataset and/or assessment not theirs


def test_compare_selects_include_all(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload_csv(client, CLEAN_CSV)
    _assess(client, dataset_id, "one")
    _assess(client, dataset_id, "two")
    resp = client.get(f"/datasets/history?dataset_id={dataset_id}")
    assert resp.status_code == 200
    assert b"Compare two assessments" in resp.data
