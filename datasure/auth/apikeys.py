"""API key creation, listing, revocation and verification.

Security rules:
- The raw key value is shown exactly once, at creation, and is never stored;
  only its SHA-256 hash is persisted.
- Revocation is soft (revoked_at timestamp) so the audit trail stays intact.
- Every operation is scoped to the owning user; other users' keys are invisible.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from flask_login import UserMixin

from ..extensions import db
from ..models import ApiKey

MAX_KEYS_PER_USER = 10


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_key(user: UserMixin, name: str) -> tuple[ApiKey, str]:
    """Create a key for `user`. Returns (record, raw_key) - raw shown once."""
    name = (name or "").strip()[:80] or "Untitled key"
    count = ApiKey.query.filter_by(user_id=user.id).count()
    if count >= MAX_KEYS_PER_USER:
        raise ValueError(
            f"You already have {MAX_KEYS_PER_USER} API keys. Revoke one before creating another."
        )
    raw = secrets.token_urlsafe(32)
    record = ApiKey(user_id=user.id, name=name, key_hash=hash_key(raw))
    db.session.add(record)
    db.session.commit()
    return record, raw


def list_keys(user: UserMixin) -> list[ApiKey]:
    """Keys owned by the user, newest first."""
    return (
        ApiKey.query.filter_by(user_id=user.id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )


def get_owned_key(user: UserMixin, key_id: int) -> ApiKey | None:
    record = db.session.get(ApiKey, key_id)
    if record is None or record.user_id != user.id:
        return None
    return record


def revoke_key(user: UserMixin, key_id: int) -> ApiKey | None:
    """Soft-revoke an owned key; returns the record or None if not owned."""
    record = get_owned_key(user, key_id)
    if record is None or not record.is_active():
        return None if record is None else record
    record.revoked_at = datetime.now(timezone.utc)
    db.session.commit()
    return record


def authenticate_key(raw_key: str) -> tuple[ApiKey, UserMixin] | None:
    """Verify a raw key value; returns (record, user) for an active key."""
    if not raw_key:
        return None
    record = ApiKey.query.filter_by(key_hash=hash_key(raw_key)).first()
    if record is None or not record.is_active():
        return None
    record.last_used_at = datetime.now(timezone.utc)
    db.session.commit()
    return record, record.user
