# Roadmap

Status: the v1 core workflow (upload → assess → score → clean → report →
history) plus the hardening layers below are implemented and covered by the
automated test suite (230+ tests).

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

## Next up (priority order)

1. **Background assessments** — only if profiling throughput on real datasets
   justifies the queueing complexity; failures surface as a recoverable job
   status.
2. **PostgreSQL migration tooling** — Alembic-style schema migration history;
   currently `create_all()` handles first-run creation only.
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
