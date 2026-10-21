"""Structured JSON logging: format option, correlation ids, never raising."""
from __future__ import annotations

import json
import logging

from datasure.logformat import JsonFormatter


class _Capture(logging.Handler):
    """Collects formatted record strings emitted through a formatter."""

    def __init__(self, formatter=None):
        super().__init__(level=logging.INFO)
        self.formatter = formatter or JsonFormatter()
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


from contextlib import contextmanager


@contextmanager
def _json_app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path / "log-instance"))
    from datasure import create_app

    app = create_app("testing")
    app.config["LOG_FORMAT"] = "json"
    from flask.logging import default_handler

    from datasure.logformat import apply_formatter

    saved = default_handler.formatter
    apply_formatter(app)
    try:
        yield app
    finally:
        default_handler.setFormatter(saved)


def test_json_formatter_emits_parseable_single_line():
    formatter = JsonFormatter()
    record = logging.LogRecord("datasure.test", logging.INFO, "file.py", 10,
                               "hello %s", ("world",), None)
    line = formatter.format(record)
    payload = json.loads(line)
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "datasure.test"
    assert "\n" not in line


def test_json_formatter_includes_request_id_in_request(app):
    capture = _Capture()
    capture.setFormatter(JsonFormatter())
    app.logger.addHandler(capture)
    with app.test_request_context("/login"):
        from datasure import get_correlation_id

        request_id = get_correlation_id()
        app.logger.info("during request")
    payload = json.loads(capture.records[0])
    assert payload["request_id"] == request_id


def test_json_formatter_formats_exception_as_single_line():
    formatter = JsonFormatter()
    try:
        raise RuntimeError("boom-value")
    except RuntimeError:
        import sys

        record = logging.LogRecord("datasure.test", logging.ERROR, "f.py", 1,
                                   "failed", None, sys.exc_info())
    line = formatter.format(record)
    payload = json.loads(line)
    assert "boom-value" in payload["exc_info"]
    assert "RuntimeError" in payload["exc_info"]
    assert "\n" not in line


def test_apply_formatter_attaches_json_to_app_logger(monkeypatch, tmp_path):
    from flask.logging import default_handler

    with _json_app(monkeypatch, tmp_path) as app:
        assert default_handler.formatter.__class__ is JsonFormatter
        app.logger.info("json flag checked")


def test_text_format_remains_default(app):
    from flask.logging import default_handler

    assert app.config["LOG_FORMAT"] == "text"
    assert default_handler.formatter.__class__ is not JsonFormatter
