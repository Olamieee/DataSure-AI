"""Database models for DataSure AI.

All stored dataset payloads are kept as JSON columns so profiles remain
reproducible snapshots. Sensitive data is never stored in logs.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class User(UserMixin, db.Model, TimestampMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_active_user = db.Column(db.Boolean, nullable=False, default=True)

    datasets = db.relationship("Dataset", backref="owner", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # UserMixin compatibility -------------------------------------------------
    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return self.is_active_user

    @property
    def is_authenticated(self) -> bool:  # type: ignore[override]
        return True

    def get_id(self) -> str:
        return str(self.id)


class ApiKey(db.Model, TimestampMixin):
    __tablename__ = "api_keys"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)  # user-chosen label
    key_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    last_used_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)

    def is_active(self) -> bool:
        return self.revoked_at is None

    user = db.relationship("User", backref=db.backref("api_keys", lazy="dynamic",
                                                      cascade="all, delete-orphan"))


class Dataset(db.Model, TimestampMixin):
    __tablename__ = "datasets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    # Name actually used on disk (server-generated, never the raw client name).
    storage_filename = db.Column(db.String(160), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    extension = db.Column(db.String(10), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    row_count = db.Column(db.Integer)
    column_count = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="uploaded")  # uploaded|parsed|error
    error_message = db.Column(db.String(500))
    storage_version = db.Column(db.Integer, nullable=False, default=1)  # bumped on cleaning
    is_cleaned = db.Column(db.Boolean, nullable=False, default=False)
    has_original = db.Column(db.Boolean, nullable=False, default=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("schema_contracts.id"), nullable=True)
    contract_passed = db.Column(db.Boolean)

    assessments = db.relationship(
        "Assessment", backref="dataset", lazy="dynamic", cascade="all, delete-orphan"
    )
    cleaning_operations = db.relationship(
        "CleaningOperation", backref="dataset", lazy="dynamic", cascade="all, delete-orphan"
    )


class Assessment(db.Model, TimestampMixin):
    __tablename__ = "assessments"

    id = db.Column(db.Integer, primary_key=True)
    dataset_id = db.Column(db.Integer, db.ForeignKey("datasets.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    quality_score = db.Column(db.Float, nullable=True)
    # Full methodology snapshot: {dimension: {"score", "breakdown", "formula"}}.
    scores_json = db.Column(db.JSON)
    # Detected issues: [{kind, severity, columns, message, recommendation}]
    issues_json = db.Column(db.JSON)
    # Full column-level profile (potentially large; kept for history/compare).
    profile_json = db.Column(db.JSON)
    row_count = db.Column(db.Integer)
    column_count = db.Column(db.Integer)
    target_column = db.Column(db.String(255))
    duration_ms = db.Column(db.Integer)
    label = db.Column(db.String(120))  # user-facing version label


class SchemaContract(db.Model, TimestampMixin):
    """Reusable schema expectations for validating uploaded datasets.

    contract_json layout:
    {
      "allow_extra_columns": bool,
      "columns": [
        {"name": str, "kind": "numeric"|"categorical"|"datetime"|"boolean"|"text",
         "nullable": bool, "allowed_values": [..] | null}
      ]
    }
    """
    __tablename__ = "schema_contracts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500))
    contract_json = db.Column(db.JSON, nullable=False)

    user = db.relationship("User", backref=db.backref("schema_contracts", lazy="dynamic",
                                                      cascade="all, delete-orphan"))
    datasets = db.relationship("Dataset", backref="schema_contract", lazy="dynamic")


class CleaningOperation(db.Model, TimestampMixin):
    __tablename__ = "cleaning_operations"

    id = db.Column(db.Integer, primary_key=True)
    dataset_id = db.Column(db.Integer, db.ForeignKey("datasets.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessments.id"))
    operation = db.Column(db.String(64), nullable=False)
    params_json = db.Column(db.JSON)
    result_filename = db.Column(db.String(160))  # cleaned file on disk
    rows_before = db.Column(db.Integer)
    rows_after = db.Column(db.Integer)
    columns_before = db.Column(db.Integer)
    columns_after = db.Column(db.Integer)
    cells_changed = db.Column(db.Integer)
    success = db.Column(db.Boolean, nullable=False, default=False)
    message = db.Column(db.String(500))


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))
