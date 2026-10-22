# Roadmap

Status: the v1 core workflow (upload → assess → score → clean → report →
history) plus the hardening layers below are implemented and covered by the
automated test suite (330+ tests).

## Delivered

- CSRF protection on all browser forms (API blueprint exempt; key-authenticated)
- API key management UI: multi-key creation, one-time display, revocation,
  last-used tracking
- Assessment comparison view: score deltas, resolved/new issues, severity
  transitions, schema-change warnings
- Schema contracts: generation from datasets, validation with readable
  violations, per-dataset result tracking
- Reusable validation rules: five structured rule types with a fixed operator
  registry (no expression evaluation)
- Large-file handling: streamed CSV limit scanning, profiling wall-time budget
- Observability: per-request correlation IDs in logs and on error pages,
  audit trail for destructive actions
- Login rate limiting, password change, security headers, secure-cookie
  production config
- Pagination for dashboard, history and REST list endpoints
- CSV exports of issues and column statistics
- Production WSGI entry point + deployment documentation
- GitHub Actions CI (pytest on Python 3.12/3.13)
- `/healthz` readiness endpoint with database check (JSON + 503 degraded)
- Explicit schema migration framework (`datasure/migrations.py`, version
  recorded in the database; failing steps abort startup loudly)
- CLI operations: `create-user`, `list-users`, `check-config`, `prune-audits`
- Activity page (users see their own audit events) and live storage usage page
- Dashboard search (wildcard-escaped, case-insensitive) and paginated
  contracts/rules pages
- Duplicate-upload warning by content hash
- REST API parity: contracts (list/retrieve/validate), rules (list/create/run),
  CSV exports, dataset file download, assessment comparison

## Next up (priority order)

1. **Background assessments** — only if profiling throughput on real datasets
   justifies the queueing complexity; failures surface as a recoverable job
   status.
2. **PostgreSQL hardening for the migration framework** — the version-tracked
   migration framework ships and works on SQLite in production paths; extend
   the step vocabulary with dialect-aware ALTER helpers before claiming
   first-class PostgreSQL support.
3. **Password reset flow** — requires an email-sending decision (no SMTP
   dependency exists yet).
4. **Report accessibility polish** — landmark roles, table captions, focus
   order pass against the HTML report template.

## Later / consideration only

- Team collaboration (multi-user workspaces)
- ML-assisted cleaning suggestions (must beat the deterministic rules
  measurably before replacing them)
- Redis-backed rate limiting for clustered deployments
- Scheduled assessment runs (paid infrastructure; needs justification)
