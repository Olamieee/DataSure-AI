# Architecture Decision Record — summary

## Stack rationale

- **Flask + server-rendered Jinja + Bootstrap/Chart.js**: the product is a
  guided workflow (upload → assess → fix), not a highly interactive dashboard.
  Server-rendering keeps deployment simple, testing straightforward and the
  attack surface small. A SPA frontend would add complexity without a
  corresponding user benefit at this stage.
- **SQLAlchemy (Flask-SQLAlchemy)** with SQLite default: zero-ops local
  development; a single string change (`DATASURE_DATABASE_URL`) moves to
  PostgreSQL. Column types used are deliberately portable (Integer/String/JSON/DateTime/Boolean).
- **Pandas/NumPy profiling**: the analysis needs are arithmetic and group-wise;
  dedicated validation libraries (Pandera etc.) add a schema-definition DSL that
  overlaps exactly with this product's own issue report. Where third-party
  validation adds real value later, it can be layered on top of the profiler.
- **scikit-learn**: available for future ML-assisted cleaning suggestions; the
  current scoring/issues are deterministic rules by design (auditable).

## Key invariants (safety-critical)

1. **Uploads never mutate.** Cleaning writes a new file; the original upload for
   a dataset's version line always remains on disk. `Dataset.storage_filename`
   points at the current version; the first cleaning operation's context
   preserves the chain.
2. **Ownership checks everywhere.** `_owned_dataset` (web) and `_own_dataset`
   (API) are the only access paths to stored files/records.
3. **No user input constructs filesystem paths.** Storage names are UUID+extension.
4. **Leakage findings are warnings.** The platform never asserts leakage.
5. **Scores are disclosed heuristics.** Every dimension publishes formula, inputs
   and penalties; the disclaimer appears in UI and reports.

## Data model

- `users` — credentials, `api_key_hash` (SHA-256 of a random token)
- `datasets` — metadata, current storage filename, version counter, status
- `assessments` — immutable snapshots: `profile_json`, `issues_json`,
  `scores_json`, quality score, target column, duration
- `cleaning_operations` — audit trail: operation, params, before/after shapes,
  cells changed, resulting filename

## Known trade-offs / future work

- `profile_json` stores full profiles per assessment; pruning or compression may
  be needed for heavy usage patterns.
- Flask-Login session auth is cookie-based; a token flow for programmatic
  uploads is on the roadmap (API keys already exist for reads).
- No CSRF framework yet: forms are same-site and logout is POST-only, but adding
  a CSRF layer (Flask-WTF) is planned before any multi-user hosting.
