# Deployment

This document describes a production deployment of DataSure AI: environment,
WSGI server, reverse proxy, HTTPS, backups and operational checks. It is
written for the maintainers; nothing here has been executed against paid
infrastructure.

## 1. Prerequisites

- Python 3.12+ (the CI matrix tests 3.12 and 3.13).
- A Linux or Windows host, or a container platform.
- A PostgreSQL server for multi-user, multi-process deployments
  (SQLite is acceptable for single-user or evaluation instances).

## 2. Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATASURE_SECRET_KEY` | **Yes (production)** | Flask secret for session signing. Generate: `python -c "import secrets; print(secrets.token_hex(32))"`. Treat like a password; rotate carefully. |
| `DATASURE_DATABASE_URL` | recommended | `postgresql+psycopg://user:pass@host/db`. Unset = default SQLite under the instance path. |
| `DATASURE_INSTANCE_PATH` | recommended | Directory holding the DB, `uploads/` and `reports/`. Must be writable and backed up. |
| `DATASURE_MAX_UPLOAD_MB` | optional | Upload size cap, default `50`. |
| `DATASURE_MAX_ROWS` / `DATASURE_MAX_COLUMNS` | optional | Shape caps, default `500000` / `400`. |
| `DATASURE_PROFILE_TIME_BUDGET_SECONDS` | optional | Profiling wall-time budget, default `120`. |
| `DATASURE_LOG_FORMAT` | optional | `text` (default) or `json`; JSON emits one object per log line with level, logger, message and the request correlation id — convenient for log aggregators. |
| `DATASURE_CONFIG` | optional | `production` (default) or `development`. |

## 3. Install

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# PostgreSQL driver (only if using PostgreSQL):
pip install "psycopg[binary]"
```

## 4. Run with a WSGI server

The repo ships `wsgi.py` exposing `application`. Examples:

```bash
# Waitress (pure Python, works on Windows and Linux)
.venv/bin/python -m waitress --listen=127.0.0.1:8000 --threads=8 wsgi:application

# gunicorn (Linux)
gunicorn --workers 4 --bind 127.0.0.1:8000 wsgi:application
```

- Keep the app bound to `127.0.0.1`; a reverse proxy terminates TLS and serves
  the public interface.
- Size workers to the instance (profiling is CPU-bound but bounded by the
  `DATASURE_PROFILE_TIME_BUDGET_SECONDS` budget, oversized uploads are rejected
  early by the streamed scan before full parsing).
- The login rate limiter is in-process: with several workers, each limits
  independently. For strict cross-worker limits, front the app with a proxy
  feature (e.g. nginx `limit_req`) or a shared Redis store.

## 5. Reverse proxy and HTTPS

Example nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name datasure.example.com;

    ssl_certificate     /etc/letsencrypt/live/datasure.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/datasure.example.com/privkey.pem;

    client_max_body_size 55m;   # above DATASURE_MAX_UPLOAD_MB

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

Notes:

- Production config forces `SESSION_COOKIE_SECURE`; HTTPS is therefore
  effectively required.
- The app labels cookies `SameSite=Lax` and `HttpOnly` and stamps
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` on responses.
- Behind a proxy, per-address rate limiting sees the proxy IP. Prefer proxy-side
  limits or a real-IP middleware if that matters to your deployment.

## 6. Database migrations

Schema evolution is version-tracked: `datasure/migrations.py` applies numbered
steps recorded in the `schema_state` table before `create_all()` runs (which
still adds any missing *tables* on first run). A failing migration aborts
startup loudly instead of starting against an untracked schema. To add a
schema change, append a `(version, name, function)` tuple to `MIGRATIONS`
there — never edit an already-shipped step. Back up the database before
upgrading (Section 8).

Migration plumbing is dialect-aware as of 2026-10: the progress lookup uses
the SQLAlchemy inspector (no backend-specific catalog queries) and column
additions go through the shared `add_column(engine, table, statement)`
helper, so steps written with plain `VARCHAR ...` definitions work on both
SQLite and PostgreSQL. Automated coverage is still SQLite-only end to end —
PostgreSQL deployments should run one boot on a staging copy first (Section 8
backup applies).

## 7. Data retention and deletion

- Deleting a dataset removes its stored file, rows in related tables
  (assessments, cleaning operations, contract links) and its audit events'
  dataset link (`ON DELETE SET NULL`). User-initiated deletion is the primary
  retention mechanism.
- Users can download their complete account contents (dataset metadata and
  history, contracts, rules, audit trail) from **Settings → Storage → "Export
  all my data (JSON)"** at `/settings/export`; the API mirrors single resources
  via `/api/v1/me` and per-dataset downloads.
- Uploaded files live solely under `<instance>/uploads/user_<id>/` with
  server-generated UUID names; the original filename is only stored for display
  and download naming.

## 8. Backups

- Back up the whole instance directory (database + uploads + reports). The
  uploads file tree is content-addressable by UUID names; back up within the
  same backup job as the DB so they stay consistent.
- For PostgreSQL, use `pg_dump` in the same schedule.

## 9. Operational checks

After each deploy:

1. `GET /api/v1/health` → `{"status": "ok", ...}` and `GET /healthz` →
   `200 ok` / `503 degraded` (both unauthenticated).
2. `flask check-config` in the deployment shell: reports the effective
   secret-key state (never the value), database origin, upload limits and
   instance-path writability; exits non-zero when deploying would fail.
3. Register a scratch account, upload a small CSV, run one assessment, delete
   the dataset.
4. Confirm `X-Request-ID` appears on responses (used for log/error
   correlation).
5. Check the log stream contains no dataset contents, passwords or API key
   material (see `docs/ARCHITECTURE.md` for the logging guarantees).

## 10. User and audit administration

- `flask create-user <username> <email>` (password prompted securely) or
  `flask list-users` for an account inventory with dataset counts.
- `flask reset-password --username=<name>` (new password prompted securely)
  when a user loses access — no email flow exists, so this is run on the
  server by an operator and audited as `password_reset_cli`.
- Audit events (uploads, deletions, cleanings, key management) are visible to
  each user on `/settings/activity`. Apply a retention window with
  `flask prune-audits --days=90` (runs from cron/Task Scheduler as needed).

## 11. Known deployment caveats (honest list)

- Migration SQL is written for SQLite and PostgreSQL (shared `add_column`
  helper, inspector-based progress lookup), but automated tests exercise the
  framework end-to-end on SQLite only — run one boot against a PostgreSQL
  staging copy before production upgrades.
- Rate limiting is per worker process (Section 4).
- No email flows: forgotten passwords are recovered by an operator running
  `flask reset-password --username=<name>` on the server (audited as
  `password_reset_cli`); the web password change page requires the current
  password.
- The app serves its own static files; a CDN is unnecessary, but proxy-side
  caching of `/static/*` is fine.
