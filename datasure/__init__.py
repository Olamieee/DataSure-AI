"""DataSure AI - AI Dataset Quality and Validation Platform.

Flask application factory.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from flask import Flask, render_template, request


def _configure_logging(app: Flask) -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s [req:%(request_id)s]: %(message)s",
        level=logging.DEBUG if app.testing else logging.INFO,
    )
    logging.setLogRecordFactory(_record_factory)
    # Third-party libraries are noisy at DEBUG; keep them at WARNING.
    for noisy in ("matplotlib", "fontTools", "matplotlib.font_manager"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Note: request bodies are never logged - they may contain dataset contents.

    if app.config.get("LOG_FORMAT") == "json":
        from .logformat import apply_formatter

        apply_formatter(app)


def _record_factory(*args, **kwargs) -> logging.LogRecord:
    """Ensure every log record carries a request_id even outside requests."""
    record = logging.LogRecord(*args, **kwargs)
    record.request_id = get_correlation_id()
    return record


_CORRELATION_KEY = "datasure_request_id"


def get_correlation_id() -> str:
    """Stable per-request correlation id shared by logs and error responses.

    Returns '' when logging happens outside a request context (CLI, startup),
    so log lines stay well-formed everywhere.
    """
    try:
        from flask import has_request_context, request

        if not has_request_context():
            return ""
        value = request.environ.get(_CORRELATION_KEY)
        if value:
            return value
        value = uuid.uuid4().hex[:12]
        request.environ[_CORRELATION_KEY] = value
        return value
    except Exception:  # pragma: no cover - logging must never raise
        return ""


def create_app(config_name: str | None = None) -> Flask:
    template_dir = Path(__file__).resolve().parent.parent / "templates"
    static_dir = Path(__file__).resolve().parent.parent / "static"
    instance_path = os.environ.get("DATASURE_INSTANCE_PATH")

    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
        instance_path=instance_path,
    )

    if config_name is None:
        config_name = os.environ.get("DATASURE_CONFIG", "production")

    conf = config_name.lower()
    if conf in ("development", "dev"):
        from .config import DevelopmentConfig

        app.config.from_object(DevelopmentConfig)
    elif conf == "testing":
        from .config import TestingConfig

        app.config.from_object(TestingConfig)
    else:
        from .config import ProductionConfig

        app.config.from_object(ProductionConfig)
        # SECRET_KEY classes capture the environment at import time; always
        # re-read it here so every create_app() call sees the current env.
        app.config["SECRET_KEY"] = os.environ.get("DATASURE_SECRET_KEY")
        # Serve secure cookies unless running locally with debug enabled.
        if not app.debug:
            app.config["SESSION_COOKIE_SECURE"] = True
        app.config.setdefault(
            "SESSION_COOKIE_SECURE",
            not app.debug,
        )

    # Fail fast in production if the secret key is not configured.
    if not app.config.get("SECRET_KEY") and not app.config.get("TESTING"):
        raise RuntimeError(
            "DATASURE_SECRET_KEY is not set. Generate one with:"
            " python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    # INSTANCE_PATH holds the SQLite database, uploads and generated reports.
    instance_dir = Path(app.instance_path)
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (instance_dir / "reports").mkdir(parents=True, exist_ok=True)

    _configure_logging(app)

    from .extensions import csrf, db, login_manager

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Register blueprints.
    from .api.routes import bp as api_bp
    from .auth.routes import bp as auth_bp
    from .contracts.routes import bp as contracts_bp
    from .datasets.routes import bp as datasets_bp
    from .main.routes import bp as main_bp
    from .rules.routes import bp as rules_bp
    from .settings.routes import bp as settings_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(datasets_bp, url_prefix="/datasets")
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(contracts_bp, url_prefix="/contracts")
    app.register_blueprint(rules_bp, url_prefix="/rules")
    csrf.exempt(api_bp)  # API clients authenticate with keys, not form tokens

    @app.after_request
    def _stamp_request_id(response):
        """Expose the correlation id so users can report it with issues."""
        response.headers["X-Request-ID"] = get_correlation_id()
        for header, value in app.config.get("SECURITY_HEADERS", {}).items():
            response.headers.setdefault(header, value)
        return response

    @app.errorhandler(500)
    def _internal_error(error):
        request_id = get_correlation_id()
        app.logger.error("Internal error [%s]: %s", request_id, error)
        if request.accept_mimetypes.accept_html:
            return render_template("errors/500.html", request_id=request_id), 500
        return {"error": "internal server error", "request_id": request_id}, 500

    with app.app_context():
        db.create_all()

    app.logger.info("DataSure AI initialised (config=%s)", conf)
    return app
