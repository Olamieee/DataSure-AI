# Continuous Integration

## GitHub Actions workflow (`.github/workflows/tests.yml`)

- **Triggers:** every push and pull request to `main`.
- **Permissions:** `contents: read` only — the workflow cannot write to the
  repository or access any secrets.
- **Matrix:** runs the full pytest suite on Python 3.12 and 3.13 on Ubuntu.
- **PostgreSQL job:** a service-container smoke test (`scripts/pg_smoke.py`
  on PostgreSQL 16) verifies the app boots, migrations record state, a second
  boot is up to date and user registration works on the real engine. The
  psycopg driver is installed only in this job, not in the pytest matrix.
- **Steps:** checkout → setup-python with pip caching →
  `pip install -r requirements.txt` → `python -m pytest -q`.
- **Environment:** `DATASURE_INSTANCE_PATH` points at a runner temp directory so
  the SQLite database, uploads and generated reports never touch the checkout;
  `DATASURE_SECRET_KEY` is a non-secret placeholder required by the production
  config path (unit tests use TESTING anyway). Job-level credentials for the
  Postgres smoke (`DATASURE_DATABASE_URL`) are fixture-only: both ports are
  inside the ephemeral job and never reused or published.
- **No secrets:** there are secure credentials nowhere in the workflow file or
  environment; the project has no third-party service dependencies in CI.

## Running the same checks locally

```powershell
.\.venv\Scripts\python.exe -m pytest
```

A green CI run and a green local run use the same configuration: the tests
create isolated in-memory databases and temporary instance paths, so they are
order-independent and repeatable.
