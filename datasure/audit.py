"""Audit trail for important actions.

`record_audit` is deliberately strict about what may be stored: identifiers
and operation names only. Values from datasets, passwords and API key
material never belong here (or in any log).
"""
from __future__ import annotations

from typing import Any

from .extensions import db
from .models import AuditEvent
from .__init__ import get_correlation_id

ALLOWED_ACTIONS = frozenset({
    "dataset_deleted",
    "cleaning_applied",
    "api_key_created",
    "api_key_revoked",
    "contract_deleted",
    "rule_deleted",
    "dataset_file_missing",
})


def record_audit(action: str, user_id: int, *, dataset_id: int | None = None,
                 request_id: str | None = None, **detail: Any) -> None:
    """Store one audit event. Unknown actions and oversized details raise.

    `request_id` defaults to the current request's correlation id (empty
    string outside requests, e.g. during CLI operations).
    """
    if request_id is None:
        from . import get_correlation_id

        request_id = get_correlation_id()
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"unknown audit action '{action}'")
    if len(detail) > 8:
        raise ValueError("audit detail is limited to 8 fields")
    detail = {key: str(value)[:120] for key, value in detail.items()}
    db.session.add(AuditEvent(
        user_id=user_id,
        action=action,
        dataset_id=dataset_id,
        detail_json=detail,
        request_id=request_id[:16],
    ))
    db.session.commit()


def dataset_events(dataset_id: int, user_id: int) -> list[AuditEvent]:
    """Audit events for one dataset, newest first (owner-scoped)."""
    return (
        AuditEvent.query.filter_by(dataset_id=dataset_id, user_id=user_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(50)
        .all()
    )
