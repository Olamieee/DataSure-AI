"""Explicit schema migrations.

``create_all()`` reliably builds *new* tables but silently ignores *new
columns on existing tables*, so real deployments could drift from the models
without noticing. This framework makes every future schema change an
explicit, numbered step recorded in the database itself:

1. ``create_app`` runs migrations BEFORE ``create_all()`` bookkeeping.
2. Each step is a plain function ``(db, engine)`` guarded by its own
   transaction; a failing step aborts startup loudly instead of guessing.
3. Progress is recorded in the ``schema_state`` table via :class:`MIGRATIONS`
   (step 1 is the marker for databases that predate this framework).

Adding a migration: append a ``(version, name, function)`` tuple with a
monotonically increasing version and never edit an already-shipped step.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .extensions import db

logger = logging.getLogger(__name__)


def _baseline(db_obj: Any, engine: Engine) -> None:
    """Step 1: marker only.

    Existing deployments keep whatever ``create_all()`` already built; fresh
    databases are additionally verified against the metadata below.
    """


MIGRATIONS: list[tuple[int, str, Callable[[Any, Engine], None]]] = [
    (1, "baseline", _baseline),
]

LATEST_VERSION = max(entry[0] for entry in MIGRATIONS)


def current_version() -> int:
    """Highest recorded applied version (0 when the table is absent/empty)."""
    has_table = db.session.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_state'"
        )
    ).fetchone()
    if not has_table:
        return 0
    row = db.session.execute(
        text("SELECT MAX(version) FROM schema_state")
    ).fetchone()
    return int(row[0] or 0)


def _record_step(version: int, name: str) -> None:
    db.session.execute(
        text(
            "INSERT INTO schema_state (version, name, applied_at) "
            "VALUES (:version, :name, CURRENT_TIMESTAMP)"
        ),
        {"version": version, "name": name},
    )


def run_pending_migrations(app) -> list[tuple[int, str]]:
    """Apply every migration newer than the recorded version.

    Returns the list of steps it actually applied (empty when already
    up to date). An unexpected failure raises and aborts startup - the
    application must never run against an untracked schema quietly.
    """
    applied: list[tuple[int, str]] = []
    with app.app_context():
        # schema_state must exist before it can be written to; create just
        # this table so a legacy database gains the bookkeeping immediately.
        db.create_all()
        seen = current_version()
        for version, name, step in MIGRATIONS:
            if version <= seen:
                continue
            logger.info("Applying schema migration %s (%s)", version, name)
            try:
                step(db, db.engine)
                _record_step(version, name)
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception(
                    "Schema migration %s (%s) failed; aborting startup", version, name
                )
                raise
            applied.append((version, name))
    return applied
