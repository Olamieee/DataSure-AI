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


def test_fresh_app_records_all_steps(app):
    with app.app_context():
        assert _recorded_versions() == [1, 2]
        assert current_version() == 2
        ratio = db.session.query(SchemaState).order_by(SchemaState.version)
        names = [row.name for row in ratio.all()]
        assert names == ["baseline", "add_dataset_tags"]


def test_rerunning_is_idempotent(app):
    with app.app_context():
        assert run_pending_migrations(app) == []  # nothing to do the second time
        assert _recorded_versions() == [1, 2]


def test_legacy_bookkeeping_is_reapplied(app):
    """A pre-framework database gains all step markers on the next boot."""
    with app.app_context():
        db.session.execute(text("DELETE FROM schema_state"))
        db.session.commit()
        assert current_version() == 0

        applied = run_pending_migrations(app)
        assert applied == [(1, "baseline"), (2, "add_dataset_tags")]
        assert _recorded_versions() == [1, 2]


def test_second_boot_on_same_database_is_up_to_date(tmp_path, monkeypatch):
    monkeypatch.setenv("DATASURE_SECRET_KEY", "migration-test-key-1234567890")
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path / "boot-i"))

    from datasure import create_app

    first = create_app("production")
    second = create_app("production")
    assert second  # boot twice without failure against the same schema
    with first.app_context():
        assert current_version() == 2  # runs the baseline and tags steps


def test_legacy_database_gains_the_tags_column(tmp_path, monkeypatch):
    """A pre-framework database without datasets.tags is migrated on boot."""
    from sqlalchemy import create_engine, text

    monkeypatch.setenv("DATASURE_SECRET_KEY", "migration-test-key-1234567890")
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path / "legacy-i"))
    db_file = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE datasets ("
            " id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,"
            " name VARCHAR(200) NOT NULL,"
            " storage_filename VARCHAR(160) NOT NULL,"
            " original_filename VARCHAR(255) NOT NULL,"
            " extension VARCHAR(10) NOT NULL,"
            " size_bytes INTEGER NOT NULL, sha256 VARCHAR(64) NOT NULL)"
        ))
    monkeypatch.setenv("DATASURE_DATABASE_URL", f"sqlite:///{db_file}")

    from datasure import create_app

    app = create_app("production")
    with app.app_context():
        assert current_version() == 2
        insp = db.inspect(db.engine)
        names = [c["name"] for c in insp.get_columns("datasets")]
        assert "tags" in names


def test_failing_migration_rolls_back_and_raises(app):
    """An intermediate failure must abort loudly and leave state untouched."""
    def exploding_step(db_obj, engine):
        raise RuntimeError("forced bookkeeping failure for testing")

    with app.app_context():
        with mock.patch(
            "datasure.migrations.MIGRATIONS",
            [(1, "baseline", lambda a, b: None),
             (2, "add_dataset_tags", lambda a, b: None),
             (3, "boom", exploding_step)],
        ):
            import pytest

            with pytest.raises(RuntimeError, match="bookkeeping failure"):
                run_pending_migrations(app)
        # state is untouched: no phantom version 3 row after the rollback
        assert _recorded_versions() == [1, 2]
        assert current_version() == 2


def test_progress_uses_timestamps_close_to_now(app):
    with app.app_context():
        from datetime import datetime

        from datasure.models import _utcnow

        rows = db.session.query(SchemaState).order_by(SchemaState.version)
        for row in rows:
            assert isinstance(row.applied_at, datetime)
            now = _utcnow().replace(tzinfo=None)  # naive UTC
            assert abs((now - row.applied_at).total_seconds()) < 3600
