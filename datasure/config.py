"""Application configuration for DataSure AI.

Configuration is loaded from environment variables with sensible development
defaults. Production deployments should set SECRET_KEY explicitly.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Base configuration shared by all environments."""

    SECRET_KEY: str | None = os.environ.get("DATASURE_SECRET_KEY")
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 hours, in seconds

    # SQLAlchemy: SQLite by default, PostgreSQL via DATABASE_URL.
    SQLALCHEMY_DATABASE_URI: str | None = (
        os.environ.get("DATASURE_DATABASE_URL")
        or f"sqlite:///{BASE_DIR / 'instance' / 'datasure.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload limits (also enforced by Flask's MAX_CONTENT_LENGTH).
    MAX_CONTENT_LENGTH = int(os.environ.get("DATASURE_MAX_UPLOAD_MB", "50")) * 1024 * 1024

    # Memory guard: reject absurd row/column counts before heavy profiling runs
    # (kept generous; profiling runs on ordinary laptops).
    MAX_ROWS = int(os.environ.get("DATASURE_MAX_ROWS", "500000"))
    MAX_COLUMNS = int(os.environ.get("DATASURE_MAX_COLUMNS", "400"))

    # Allowed upload extensions. Never trust client-provided names for storage.
    ALLOWED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls"}
    ALLOWED_MIME_TYPES = (
        "text/csv",
        "text/plain",
        "application/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/octet-stream",
        "",
    )

    # Preview render limits.
    PREVIEW_ROWS = 25

    # Profiling limits.
    OUTLIER_ZSCORE_THRESHOLD = 3.0
    IQR_FACTOR = 1.5
    HIGH_CARDINALITY_RATIO = 0.95  # unique / rows ratio treated as suspicious
    LOW_CARDINALITY_MAX = 20      # categories considered "low cardinality"
    NUMERIC_TOP_VALUES = 10
    CATEGORICAL_TOP_VALUES = 10

    # Static asset caching (seconds).
    SEND_FILE_MAX_AGE_DEFAULT = 300

    JSON_SORT_KEYS = False


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    SECRET_KEY = "test-secret-key"  # noqa: S105  (test-only value)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATASURE_TEST_DATABASE_URL", "sqlite://"
    )
    WTF_CSRF_ENABLED = False
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
