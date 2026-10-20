"""DataSure AI - AI Dataset Quality and Validation Platform.

Flask application factory.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask


def _configure_logging(app: Flask) -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.DEBUG if app.testing else logging.INFO,
    )
    # Third-party libraries are noisy at DEBUG; keep them at WARNING.
    for noisy in ("matplotlib", "fontTools", "matplotlib.font_manager"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    # Note: request bodies are never logged - they may contain dataset contents.


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
        from .config import Config

        app.config.from_object(Config)
        # Serve secure cookies unless running locally with debug enabled.
        if not app.debug:
            app.config["SESSION_COOKIE_SECURE"] = True

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

    from .extensions import db, login_manager

    db.init_app(app)
    login_manager.init_app(app)

    # Register blueprints.
    from .api.routes import bp as api_bp
    from .auth.routes import bp as auth_bp
    from .datasets.routes import bp as datasets_bp
    from .main.routes import bp as main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(datasets_bp, url_prefix="/datasets")
    app.register_blueprint(api_bp, url_prefix="/api/v1")

    with app.app_context():
        db.create_all()

    app.logger.info("DataSure AI initialised (config=%s)", conf)
    return app
