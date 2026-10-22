"""Schema migration framework: bookkeeping, idempotence, failure abort."""
from __future__ import annotations

from datetime import datetime
from unittest import mock

from sqlalchemy import text

from datasure.extensions import db
from datasure.migrations import current_version, run_pending_migrations
from datasure.models import SchemaState


def _recorded_versions():
    rows = db.session.execute(
        text("SELECT version FROM schema_state ORDER BY version")
    ).fetchall()
    return [row[0] for row in rows]


def test_fresh_app_records_baseline(app):
    with app.app_context():
        assert _recorded_versions() == [1]
        assert current_version() == 1
        row = db.session.query(SchemaState).one()
        assert row.name == "baseline"


def test_rerunning_is_idempotent(app):
    with app.app_context():
        assert run_pending_migrations(app) == []  # nothing to do the second time
        assert _recorded_versions() == [1]


def test_legacy_database_without_bookkeeping_is_marked(app):
    """A pre-framework database gains its baseline marker on the next boot."""
    with app.app_context():
        db.session.execute(text("DELETE FROM schema_state"))
        db.session.commit()
        assert current_version() == 0

        applied = run_pending_migrations(app)
        assert applied == [(1, "baseline")]
        assert _recorded_versions() == [1]


def test_second_boot_on_same_database_is_up_to_date(tmp_path, monkeypatch):
    monkeypatch.setenv("DATASURE_SECRET_KEY", "migration-test-key-1234567890")
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path / "boot-i"))

    from datasure import create_app

    first = create_app("production")
    second = create_app("production")
    assert second  # boot twice without failure against the same schema
    with first.app_context():
        assert current_version() == 1


def test_failing_migration_rolls_back_and_raises(app):
    """An intermediate failure must abort loudly and leave state untouched."""
    def exploding_step(db_obj, engine):
        raise RuntimeError("forced bookkeeping failure for testing")

    with app.app_context():
        with mock.patch(
            "datasure.migrations.MIGRATIONS",
            [(1, "baseline", lambda a, b: None), (2, "boom", exploding_step)],
        ):
            import pytest

            from datasure.migrations import MIGRATIONS as _  # noqa
            with pytest.raises(RuntimeError, match="bookkeeping failure"):
                run_pending_migrations(app)
        # state is untouched: still baseline only, no version 2 row
        assert _recorded_versions() == [1]
        assert current_version() == 1


def test_progress_uses_utc_timestamps(app):
    with app.app_context():
        row = db.session.query(SchemaState).one()
        assert isinstance(row.applied_at, datetime)
        assert (datetime.utcnow() - row.applied_at).total_seconds() < 3600 or (
            row.applied_at.tzinfo is not None
            and (
                datetime.now(row.applied_at.tzinfo) - row.applied_at
            ).total_seconds()
            < 3600
        )
