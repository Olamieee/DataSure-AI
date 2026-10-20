# Roadmap

Status: v1 core workflow implemented (upload → assess → score → clean → report → history).

## Next up (priority order)

1. **API key management UI** — generate/regenerate keys in a settings page
   (the model method exists; no UI yet).
2. **Dataset diff view** — compare two assessments of the same dataset
   (score delta + issue delta); data is already stored per assessment.
3. **Deployment hardening** — Gunicorn/Waitress production server docs,
   reverse-proxy setup, health check integration.
4. **CSRF tokens for all POST forms** (planned; currently same-site forms and
   POST-only logout).
5. **Scheduled assessments** — only after justification for paid infrastructure.

## Later / consideration only

- Team collaboration (multi-user workspaces)
- Pandera-style user-defined validation rules
- ML-assisted cleaning suggestions (must beat the deterministic rules measurably)
- PostgreSQL migration guide documentation as usage grows
