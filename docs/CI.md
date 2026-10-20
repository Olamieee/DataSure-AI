# Continuous Integration

## GitHub Actions workflow (`.github/workflows/tests.yml`)

- **Triggers:** every push and pull request to `main`.
- **Permissions:** `contents: read` only — the workflow cannot write to the
  repository or access any secrets.
- **Matrix:** runs the full pytest suite on Python 3.12 and 3.13 on Ubuntu.
- **Steps:** checkout → setup-python with pip caching →
  `pip install -r requirements.txt` → `python -m pytest -q`.
- **Environment:** `DATASURE_INSTANCE_PATH` points at a runner temp directory so
  the SQLite database, uploads and generated reports never touch the checkout;
  `DATASURE_SECRET_KEY` is a non-secret placeholder required by the production
  config path (unit tests use TESTING anyway).
- **No secrets:** there are secure credentials nowhere in the workflow file or
  environment; the project has no third-party service dependencies in CI.

## Running the same checks locally

```powershell
.\.venv\Scripts\python.exe -m pytest
```

A green CI run and a green local run use the same configuration: the tests
create isolated in-memory databases and temporary instance paths, so they are
order-independent and repeatable.
