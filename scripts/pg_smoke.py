"""Boot DataSure AI against a real PostgreSQL server; verify migrations.

Run in CI (`.github/workflows/tests.yml`, job `postgres`) where a PostgreSQL
service container is available. Locally the same script works against any
Postgres reachable via ``DATASURE_DATABASE_URL``.

Checks:
1. ``create_app("production")`` migrates and boots on PostgreSQL.
2. Every model table exists afterwards (create_all completed).
3. A second boot against the same database is up to date (idempotence).
4. A user can actually register through the app (schema is writable).
"""
from __future__ import annotations

import os
import tempfile
import urllib.parse

TABLES = {
    "users", "datasets", "assessments", "cleaning_operations",
    "schema_contracts", "validation_rules", "audit_events", "api_keys",
    "schema_state",
}


def main() -> None:
    url = os.environ.get("DATASURE_DATABASE_URL", "")
    assert "postgres" in urllib.parse.urlparse(url).scheme, (
        "this smoke test must run against a PostgreSQL server"
    )
    os.environ["DATASURE_INSTANCE_PATH"] = tempfile.mkdtemp(prefix="pg-smoke-")
    os.environ.setdefault("DATASURE_SECRET_KEY", "ci-only-not-a-secret")

    from datasure import create_app
    from datasure.extensions import db
    from datasure.migrations import (
        LATEST_VERSION,
        current_version,
        run_pending_migrations,
    )

    app = create_app("production")
    with app.app_context():
        assert run_pending_migrations(app) == []  # create_app already ran them
        assert current_version() == LATEST_VERSION
        actual = set(db.inspect(db.engine).get_table_names())
        missing = TABLES - actual
        assert not missing, f"missing tables after boot: {sorted(missing)}"

    second = create_app("production")  # same database, fresh boot
    with second.app_context():
        assert run_pending_migrations(second) == []  # nothing pending

    resp = app.test_client().post("/register", data={
        "username": "smoke_user", "email": "smoke@example.com",
        "password": "smokepassword1", "confirm_password": "smokepassword1",
    }, follow_redirects=False)
    assert resp.status_code == 302, getattr(resp, "data", resp)

    with app.app_context():
        from datasure.models import User

        assert User.query.filter_by(username="smoke_user").one()

    print("PostgreSQL smoke OK (boots, migrates, registers)")


if __name__ == "__main__":
    main()
