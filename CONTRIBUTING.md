# Contributing to DataSure AI

Thanks for considering a contribution. This document covers setup, workflow
and project conventions.

## Development setup

```powershell
git clone https://github.com/Olamieee/DataSure-AI.git
cd DataSure-AI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# run the test suite (230+ tests, isolated in-memory DB per test)
.\.venv\Scripts\python.exe -m pytest

# run the app locally with its dev server
copy .env.example .env   # then set DATASURE_SECRET_KEY in it
.\.venv\Scripts\python.exe run.py
```

Alternatively `python -m venv` on Linux/bash uses `source .venv/bin/activate`.

## Workflow

1. Work on `main` with small, coherent commits that each represent a complete,
   useful change — never split one unchanged implementation into arbitrary
   commits and never create empty commits.
2. Every feature or fix must add or update tests. Run the full suite before
   committing; only claim tests pass if they were actually run.
3. Review the diff of your own change before committing: no secrets, no
   accidental files, no unrelated edits.
4. Documentation belongs with the change: update `README.md` or the relevant
   file in `docs/` when behaviour moves.

## Project conventions

- Python 3.12+; type hints on new code; docstrings on public functions.
- All user-facing analysis claims must stay honest: quality scores are
  documented heuristics, algorithms are fully disclosed, and nothing may be
  described as "AI-powered" without a real, explainable implementation.
- Secrets come from environment variables only; never commit keys, tokens or
  real dataset contents into the repository or tests.
- Templates must escape user content (Jinja autoescaping is in effect — do not
  use `| safe` on user-derived values).
- Keep the security posture intact: CSRF tokens on browser forms, API
  blueprint exempt, ownership checks on every per-user resource, audit events
  for destructive actions, no sensitive data in logs.

## Testing notes

- Tests run against isolated in-memory SQLite per test via `tests/conftest.py`
  fixtures; avoid module-level state.
- Login rate limiting is reset between tests by the same fixtures.
- `smoke_test.py` performs an end-to-end pass (register → upload → assess →
  report → clean → API) against a temporary instance path.

## Licensing questions

Ownership and originality matter for this project: only genuinely written code
and documentation belongs here, and dependencies are limited to the list in
`requirements.txt` with visible licences.
