"""Production WSGI entry point.

Run with a production WSGI server, e.g.:

    # Waitress (Windows-friendly, pure Python)
    .\\.venv\\Scripts\\python.exe -m waitress --listen=127.0.0.1:8000 wsgi:application

    # gunicorn on Linux behind nginx
    gunicorn --workers 4 --bind 127.0.0.1:8000 wsgi:application

Required environment:
    DATASURE_SECRET_KEY      64 hex chars; generate with:
                             python -c "import secrets; print(secrets.token_hex(32))"
    DATASURE_DATABASE_URL    optional; PostgreSQL URI for scale-out, otherwise
                             the default SQLite file is used.
Optional environment:
    DATASURE_CONFIG            production (default) | development
    DATASURE_INSTANCE_PATH     directory for the SQLite db, uploads and reports
    DATASURE_MAX_UPLOAD_MB     upload size cap (default 50)
    DATASURE_MAX_ROWS          row cap (default 500000)
    DATASURE_MAX_COLUMNS       column cap (default 400)
    DATASURE_PROFILE_TIME_BUDGET_SECONDS  profiling wall-time budget (default 120)
"""
from __future__ import annotations

import logging
import os

from datasure import create_app

application = create_app(
    os.environ.get("DATASURE_CONFIG", "production")
)

if __name__ == "__main__":
    # Helpful guard for people who run `python wsgi.py` directly; the real
    # deployment must use a WSGI server.
    logging.getLogger(__name__).warning(
        "wsgi.py run directly; use waitress or gunicorn in production")
    application.run(host="127.0.0.1", port=8000)
