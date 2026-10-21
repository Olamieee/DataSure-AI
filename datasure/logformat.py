"""Log formatters for DataSure AI.

The default text formatter mirrors typical WSGI logs. `JsonFormatter`
emits single-line JSON records for log aggregators, enabled with
DATASURE_LOG_FORMAT=json. Both formatters refuse to raise: logging must
never take a request down.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("datasure")


class JsonFormatter(logging.Formatter):
    """Single-line JSON log formatter; formatting failures degrade, never raise."""

    @staticmethod
    def _default(value):
        return repr(value)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "line": record.lineno,
        }
        try:
            from . import get_correlation_id

            request_id = get_correlation_id()
            if request_id:
                payload["request_id"] = request_id
        except Exception:  # pragma: no cover - logging must never raise
            pass

        exc_info = getattr(record, "exc_info", None)
        if exc_info:
            try:
                payload["exc_info"] = self.formatException(exc_info).replace("\n", " | ")
            except Exception:  # pragma: no cover
                payload["exc_info"] = "exception formatting failed"

        try:
            return json.dumps(payload, default=JsonFormatter._default,
                              separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError):  # pragma: no cover
            return json.dumps({"level": record.levelname,
                               "message": "unserialisable log record"})


def apply_formatter(app) -> None:
    """Attach the JSON formatter to the app logger when configured."""
    from flask.logging import default_handler

    if app.config.get("LOG_FORMAT") != "json":
        return
    formatter = JsonFormatter()
    if default_handler is not None:
        default_handler.setFormatter(formatter)
    logger.debug("JSON log formatter enabled")
