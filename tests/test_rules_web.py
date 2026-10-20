"""Web tests for reusable validation rules: CRUD, running, isolation."""
from __future__ import annotations

import io

from datasure.models import ValidationRule, db


def _upload(client, content: bytes, name: str = "rulesdata.csv") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(content), name)},
        content_type="multipart/form-data", follow_redirects=False,
    )
    assert resp.status_code == 302, resp.data[:200]
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _create_rule(client, name: str, rule_type: str, **fields) -> "object":
    data = {"name": name, "rule_type": rule_type, "severity": "error", **fields}
    resp = client.post("/rules/create", data=data, follow_redirects=True)
    assert resp.status_code == 200
    return resp


CSV = b"name,age,city,start,end,id\nA,29,London,2024-01-01,2024-06-01,1\nB,30,Paris,2024-02-01,2024-02-01,2\nC,31,Atlantis,2024-03-01,2024-12-01,2\nD,120,Lisbon,2024-04-01,2024-03-15,4\n"


def test_create_numeric_range_rule(app, logged_in_user):
    client = logged_in_user["client"]
    page = _create_rule(client, "age bounded", "numeric_range",
                        column="age", min="0", max="110")
    assert b"age bounded" in page.data
    with app.app_context():
        rule = db.session.query(ValidationRule).filter_by(name="age bounded").one()
        assert rule.rule_json["min"] == 0.0 and rule.rule_json["max"] == 110.0


def test_create_column_comparison_rule(app, logged_in_user):
    client = logged_in_user["client"]
    _create_rule(client, "end after start", "column_comparison",
                 left="start", operator="<=", right="end")
    with app.app_context():
        rule = db.session.query(ValidationRule).filter_by(
            name="end after start").one()
        assert rule.rule_json["operator"] == "<="


def test_malformed_rule_rejected_with_message(app, logged_in_user):
    client = logged_in_user["client"]
    resp = _create_rule(client, "bad bounds", "numeric_range", column="age",
                        min="not-a-number", max="110")
    assert b"must be a number" in resp.data
    resp = _create_rule(client, "bad op", "column_comparison", left="start",
                        operator="exec(", right="end")
    assert b"free-form expressions are not permitted" in resp.data
    with app.app_context():
        assert db.session.query(ValidationRule).filter(
            ValidationRule.name.like("bad%")).count() == 0


def test_run_rules_on_dataset_mixed_results(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, CSV)
    _create_rule(client, "age sane", "numeric_range", column="age", min="0", max="110")
    _create_rule(client, "known cities", "allowed_values", column="city",
                 values="London, Paris, Lisbon")
    rules = []
    with app.app_context():
        rules = db.session.query(ValidationRule).order_by(ValidationRule.id).all()
        rule_ids = [str(rule.id) for rule in rules]
    resp = client.post(
        f"/rules/run/{dataset_id}", data={"rule_ids": rule_ids},
        follow_redirects=True,
    )
    page = resp.data.decode("utf-8")
    assert "age sane" in page and "known cities" in page
    # age 120 out of 0..110 and city Atlantis not allowed -> both flagged
    assert "failed" in page
    assert "outside the accepted range" in page
    assert "outside the allowed set" in page


def test_run_requires_selection(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, CSV)
    resp = client.post(f"/rules/run/{dataset_id}", data={}, follow_redirects=True)
    assert b"Select at least one rule" in resp.data


def test_run_blocks_cross_user_rules(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, CSV, "mine.csv")
    _create_rule(client, "my rule", "not_null", column="age")
    with app.app_context():
        rule_id = db.session.query(ValidationRule).one().id
    # another user cannot run someone else's rule on their own dataset
    own_dataset = _upload(second_user, CSV, "theirs.csv")
    resp = second_user.post(
        f"/rules/run/{own_dataset}", data={"rule_ids": [str(rule_id)]},
        follow_redirects=True,
    )
    assert b"Select at least one rule" in resp.data


def test_rules_page_requires_login(client):
    resp = client.get("/rules/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_delete_rule_owned_only(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    _create_rule(client, "target", "unique", column="id")
    with app.app_context():
        rule_id = db.session.query(ValidationRule).one().id
    assert second_user.post(f"/rules/{rule_id}/delete",
                            follow_redirects=False).status_code == 404
    client.post(f"/rules/{rule_id}/delete", follow_redirects=True)
    with app.app_context():
        assert db.session.query(ValidationRule).count() == 0
