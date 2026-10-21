"""Lightweight health checks for load balancers and uptime monitoring.

The endpoint at ``/healthz`` is intentionally unauthenticated and cheap: it
verifies the application is serving and that the database responds. It does
not authenticate, mutate, or leak any application data.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def database_check(db: Any) -> tuple[dict, int]:
    """Run one trivial query against the database engine.

    Returns ``(check_payload, status_code)`` where the payload has a
    ``status`` of ``"ok"`` or ``"error"`` plus latency in milliseconds for
    successful connections. Never raises.
    """
    started = time.perf_counter()
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return {"status": "error", "error": type(exc).__name__}, 503
    except Exception as exc:  # engine misconfiguration, missing driver, ...
        return {"status": "error", "error": type(exc).__name__}, 503
    latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return {"status": "ok", "latency_ms": latency_ms}, 200


def run_health_checks(db: Any) -> tuple[dict, int]:
    """Aggregate all health checks; aggregate status 503 when any check fails.

    Returns a JSON-safe payload ``(dict, status_code)`` ready for a response.
    """
    database, database_code = database_check(db)
    degraded = database_code != 200
    payload = {
        "status": "ok" if not degraded else "degraded",
        "checks": {"database": database},
    }
    return payload, 200 if not degraded else 503
