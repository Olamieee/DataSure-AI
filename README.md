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
| **Ingestion** | CSV / TSV / XLSX / XLS upload; encoding fallback (UTF-8 → cp1252 → Latin-1); delimiter sniffing; specific user-facing parse errors |
| **Profiling** | Missingness patterns, duplicate rows/columns, constant & high-cardinality columns, mixed types, whitespace issues, descriptive statistics, category distributions |
| **Outliers** | Tukey IQR method and Z-score method per numeric column |
| **Leakage checks** | Near-perfect feature/target correlation or agreement, redundant feature pairs — always reported as *warnings*, never conclusions |
| **Scoring** | Completeness / uniqueness / validity / consistency / distribution, each with formula, inputs and penalty breakdown; weighted overall score |
| **Cleaning** | 10 registered operations with previews, versioned storage, full operation history; the original upload can never be mutated |
| **Reports** | Self-contained HTML report with embedded matplotlib charts, plus JSON export |
| **History** | Per-dataset assessment history, score trend chart, cleaning timeline |
| **API** | Read-oriented REST API at `/api/v1` with per-user API keys (session or `X-API-Key` auth) |

## Architecture

```
datasure/
  __init__.py          app factory, blueprint registration, instance dirs
  config.py            environment-driven configuration (dev/test/production)
  extensions.py        SQLAlchemy + Flask-Login singletons
  models.py            User, Dataset, Assessment, CleaningOperation
  storage.py           UUID-based secure storage, SHA-256, name sanitisation
  assessment.py        orchestration: profile → leakage → issues → scores → store
  auth/                registration, login, logout
  datasets/
    ingest.py          robust CSV/TSV/Excel parsing with clear error messages
    routes.py          upload, detail, assess, assess view, report download,
                       clean workspace, preview, apply, history, delete
  profiling/
    profile.py         column/missingness/duplicate/schema/cardinality analysis
    outliers.py        IQR + Z-score helpers
    leakage.py         target-leakage warnings + feature correlations
    issues.py          measurements → actionable issues (deterministic rules)
    scoring.py         transparent scoring formulas
  cleaning/engine.py   validated operation registry + suggestion engine
  reports/generator.py HTML/JSON report generation (charts as data URIs)
  api/routes.py        REST API v1
templates/             Bootstrap 5 UI (server-rendered + Chart.js)
tests/                 pytest suite (102 tests)
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

## Security notes

- Storage filenames are server-generated UUIDs; client names are sanitised display metadata only.
- Every dataset/assessment/report route re-checks ownership against the current user.
- Uploads are size-capped (`MAX_CONTENT_LENGTH` + row/column guards) and extension-allowlisted.
- API keys are stored only as SHA-256 hashes; passwords use Werkzeug's scrypt hashes.
- No dataset contents are written to logs; error messages never include stack traces.
- Logout is a POST action; `?next=` redirects accept only same-site relative paths.

## API overview (`/api/v1`)

- `GET /health` — unauthenticated readiness probe
- `GET /datasets` — list your datasets
- `GET /datasets/<id>` — dataset summary
- `POST /datasets/<id>/assessments` — run an assessment (`target_column`, `label`)
- `GET /assessments/<id>` — full assessment (scores, issues, profile)
- `GET /datasets/<id>/assessments` — assessment history
- `GET /datasets/<id>/cleaning` — cleaning operation log
- `GET /datasets/<id>/preview?rows=10` — first rows

Auth: browser session cookie, or `X-API-Key: <key>` header (generate keys via the
`User.generate_api_key()` service — a management UI is planned).

## Testing

`pytest` covers ingestion/parsing guards, profiling correctness, scoring formula
hand-recomputation, cleaning operations, auth flows, API auth and scoping,
upload security and XSS/error handling. Run with `.venv\Scripts\python -m pytest`.

## Roadmap

See `docs/ROADMAP.md`. Nothing there is paid infrastructure until it earns its keep.

## Licensing

Original project code: to be chosen by the maintainer (see `docs/DEVELOPMENT.md`).
Third-party dependencies and their licences are listed in `docs/DEPENDENCIES.md`.
