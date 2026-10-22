# DataSure AI

**AI Dataset Quality and Validation Platform** — profile CSV/Excel datasets, detect
data quality problems, score quality transparently, and clean with full audit history.

[![tests](https://github.com/Olamieee/DataSure-AI/actions/workflows/tests.yml/badge.svg)](https://github.com/Olamieee/DataSure-AI/actions/workflows/tests.yml)

DataSure AI helps data scientists, ML engineers, researchers and analysts assess
their datasets *before* using them for analytics or machine learning: it measures
missingness, duplicates, type inconsistencies, distribution problems and suspected
target leakage, then explains what it found, scores quality with disclosed formulas,
and offers guided, non-destructive cleaning.

> **Honesty disclaimer (important):** quality scores are *heuristic indicators*
> computed from documented formulas with fixed thresholds. They are **not**
> scientifically validated measures of dataset quality. Every formula and penalty
> is displayed in the assessment view and in downloadable reports.

## Features

| Area | What it does |
|---|---|
| **Ingestion** | CSV / TSV / XLSX / XLS upload; encoding fallback (UTF-8 → cp1252 → Latin-1); delimiter sniffing; streamed limit scanning for large files; specific user-facing parse errors |
| **Profiling** | Missingness patterns, duplicate rows/columns, constant & high-cardinality columns, mixed types, whitespace issues, descriptive statistics, category distributions — bounded by a configurable wall-time budget |
| **Outliers** | Tukey IQR method and Z-score method per numeric column |
| **Leakage checks** | Near-perfect feature/target correlation or agreement, redundant feature pairs — always reported as *warnings*, never conclusions |
| **Scoring** | Completeness / uniqueness / validity / consistency / distribution, each with formula, inputs and penalty breakdown; weighted overall score |
| **Cleaning** | 10 registered operations with previews and versioned storage; the original upload can never be mutated; stale previews are refused via an optimistic version guard |
| **Contracts & rules** | Schema contracts generated from datasets with readable violations; reusable validation rules (bounds, membership, uniqueness, not-null, cross-column comparisons) with a fixed operator registry — never expression evaluation |
| **Comparison** | Assessment-to-assessment diff: per-dimension score deltas, resolved vs. new issues, severity transitions, schema-change warnings |
| **Reports & exports** | Self-contained HTML report with embedded charts, JSON export, CSV exports of issues and per-column statistics |
| **History & audit** | Per-dataset assessment history with pagination and trend chart, cleaning timeline, and an audit trail for destructive/security-relevant actions |
| **API** | Read-oriented REST API at `/api/v1` with per-user API keys (session or `X-API-Key` auth), page metadata on list endpoints |
| **Security** | CSRF-protected forms, login rate limiting, hashed API key storage shown once, request correlation IDs, structured logging, security headers |

## Architecture

```
datasure/
  __init__.py          app factory, blueprint registration, security headers,
                       request correlation IDs, fail-fast secret key check
  config.py            environment-driven configuration (dev/test/production)
  extensions.py        SQLAlchemy + Flask-Login + CSRF singletons
  models.py            User, ApiKey, Dataset, Assessment, CleaningOperation,
                       SchemaContract, ValidationRule, AuditEvent
  storage.py           UUID-based secure storage, SHA-256, name sanitisation
  assessment.py        orchestration: profile → leakage → issues → scores → store
  pagination.py        shared page helpers (web + API)
  audit.py             allow-listed audit event recording
  contracts/           schema contract engine + management pages
  rules/               validation rule engine (fixed registry) + pages
  auth/                registration, login (rate limited), logout, password change
  datasets/
    ingest.py          robust CSV/TSV/Excel parsing with clear error messages
    routes.py          upload, detail, assess, assess view, report download,
                       clean workspace, preview/apply (version guard), history,
                       comparison, CSV exports, delete
  profiling/
    profile.py         column/missingness/duplicate/schema/cardinality analysis
    outliers.py        IQR + Z-score helpers
    leakage.py         target-leakage warnings + feature correlations
    issues.py          measurements → actionable issues (deterministic rules)
    scoring.py         transparent scoring formulas
    compare.py         assessment-to-assessment comparison engine
  cleaning/engine.py   validated operation registry + suggestion engine
  reports/generator.py HTML/JSON report generation (charts as data URIs)
  api/routes.py        REST API v1
templates/             Bootstrap 5 UI (server-rendered + Chart.js)
tests/                 pytest suite (230+ tests)
```

SQLite is the default store; set `DATASURE_DATABASE_URL` to point at PostgreSQL
(SQLAlchemy URI) for production — the models use standard column types.

## Quickstart

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env

# set your secret key inside .env:
#   DATASURE_SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">

.venv\Scripts\python run.py
# open http://127.0.0.1:5000
```

Run the tests:

```powershell
.venv\Scripts\python -m pytest
```

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `DATASURE_SECRET_KEY` | — (required outside testing) | Session signing key |
| `DATASURE_CONFIG` | `production` | `development` / `production` / `testing` |
| `DATASURE_DATABASE_URL` | `instance/datasure.db` | SQLAlchemy URI |
| `DATASURE_INSTANCE_PATH` | Flask default | Where uploads/reports/db live |
| `DATASURE_MAX_UPLOAD_MB` | `50` | Upload size cap |
| `DATASURE_MAX_ROWS` | `500000` | Row guard for profiling |
| `DATASURE_MAX_COLUMNS` | `400` | Column guard for profiling |
| `DATASURE_PROFILE_TIME_BUDGET_SECONDS` | `120` | Profiling wall-time budget |
| `DATASURE_CHUNKED_SCAN_BYTES` | `5 MB` | Size threshold for streamed limit scanning |

## Security notes

- Storage filenames are server-generated UUIDs; client names are sanitised display metadata only.
- Every dataset/assessment/report route re-checks ownership against the current user.
- Uploads are size-capped (`MAX_CONTENT_LENGTH` + streamed row/column limit scans) and extension-allowlisted.
- API keys are stored only as SHA-256 hashes, shown once at creation; passwords use Werkzeug's scrypt hashes.
- No dataset contents are written to logs; error messages never include stack traces.
- Logout is a POST action; `?next=` redirects accept only same-site relative paths.
- Login attempts are rate limited per username and per client address.
- Every response carries an `X-Request-ID` for log/error correlation.
- More details: `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/CI.md`, `docs/DEPLOYMENT.md`, `CONTRIBUTING.md`.

## API overview (`/api/v1`)

- `GET /health` — unauthenticated readiness probe
- `GET /datasets` — list your datasets (includes tags)
- `DELETE /datasets/<id>` — permanently delete a dataset
- `GET /datasets/<id>` — dataset summary
- `GET /datasets/<id>/columns` — column-level dictionary from the latest profile
- `GET /datasets/<id>/file` — download the currently stored file
- `POST /datasets/<id>/assessments` — run an assessment (`target_column`, `label`)
- `GET /assessments/<id>` — full assessment (scores, issues, profile)
- `GET /assessments/compare?from=<id>&to=<id>` — score deltas and issue changes
- `GET /assessments/<id>/export/<kind>.csv` — export `issues`, `stats` or `history`
- `GET /datasets/<id>/assessments` — assessment history
- `GET /datasets/<id>/cleaning` — cleaning operation log
- `GET /datasets/<id>/preview?rows=10` — first rows
- `GET /contracts` · `GET /contracts/<id>` — schema contracts
- `POST /contracts/<id>/validate` — run contract validation (`dataset_id`)
- `GET /rules` · `POST /rules` — list and create validation rules
- `POST /datasets/<id>/rules/run` — run selected rules (`rule_ids`)

Auth: browser session cookie, or `X-API-Key: <key>` header (generate multi-key,
labelled, revocable keys on the Settings → API keys page; only SHA-256 hashes
are stored and the raw value is displayed exactly once). Full request/response
shapes, status codes and pagination details: `docs/API.md`.

## Testing

`pytest` covers ingestion/parsing guards and streamed limit scans, profiling
correctness and the profiling time budget, scoring formula hand-recomputation,
cleaning operations and the optimistic version guard, contract and rule
engines, assessment comparison, auth flows, rate limiting, CSRF coverage,
API auth/scoping/pagination, audit trail, escaping, exports and the WSGI
entry point. Run with `.venv\Scripts\python -m pytest` (370+ tests).

## Roadmap

See `docs/ROADMAP.md`. Nothing there is paid infrastructure until it earns its keep.

## Licensing

Original project code: to be chosen by the maintainer (see `docs/DEVELOPMENT.md`).
Third-party dependencies and their licences are listed in `docs/DEPENDENCIES.md`.
