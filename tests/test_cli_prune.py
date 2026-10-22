"""Audit retention: flask prune-audits removes only old events."""
from __future__ import annotations

from datetime import timedelta


def _insert_event(app, action: str, age_days: int) -> int:
    with app.app_context():
        from datasure.extensions import db
        from datasure.models import AuditEvent, _utcnow

        event = AuditEvent(user_id=1, action=action, detail_json={})
        event.created_at = _utcnow().replace(tzinfo=None) - timedelta(
            days=age_days
        )
        db.session.add(event)
        db.session.commit()
        return event.id


def _count_events(app) -> int:
    with app.app_context():
        from datasure.extensions import db
        from datasure.models import AuditEvent

        return int(db.session.query(AuditEvent).count())


def test_prune_deletes_only_events_older_than_window(app):
    old_id = _insert_event(app, "dataset_deleted", age_days=120)
    recent_id = _insert_event(app, "cleaning_applied", age_days=5)

    result = app.test_cli_runner().invoke(args=["prune-audits", "--days", "90"])

    assert result.exit_code == 0, result.output
    assert "Deleted 1 audit event(s)" in result.output
    assert _count_events(app) == 1

    from datasure.extensions import db
    from datasure.models import AuditEvent

    with app.app_context():
        remaining = db.session.query(AuditEvent).all()
        assert [e.id for e in remaining] == [recent_id]
        assert old_id not in [e.id for e in remaining]


def test_default_window_is_ninety_days(app):
    _insert_event(app, "rule_deleted", age_days=91)
    _insert_event(app, "api_key_created", age_days=30)

    result = app.test_cli_runner().invoke(args=["prune-audits"])
    assert result.exit_code == 0
    assert "older than 90 day(s)" in result.output
    assert _count_events(app) == 1


def test_window_boundary_keeps_exactly_n_day_old_events(app):
    _insert_event(app, "contract_deleted", age_days=30)
    _insert_event(app, "rule_deleted", age_days=31)

    result = app.test_cli_runner().invoke(args=["prune-audits", "--days", "31"])
    assert result.exit_code == 0
    assert "Deleted 1 audit event(s)" in result.output
    assert _count_events(app) == 1


def test_refuses_non_positive_retention(app):
    result = app.test_cli_runner().invoke(args=["prune-audits", "--days", "0"])
    assert result.exit_code != 0
    assert _count_events(app) == 0
