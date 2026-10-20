"""Assessment comparison: score deltas and issue changes between two snapshots.

Comparisons of two assessments of the SAME dataset are exact; when column
sets differ (e.g. after cleaning), comparisons are flagged as indicative only.
"""
from __future__ import annotations

from typing import Any


def _issue_signature(issue: dict[str, Any]) -> str:
    columns = "|".join(sorted(str(c) for c in issue.get("columns", [])))
    return f"{issue['kind']}::{columns}"


def compare_assessments(assessment_from, assessment_to) -> dict[str, Any]:
    """Build a comparison structure between two Assessment rows.

    The result is JSON-serialisable and never mutates the assessments.
    """
    scores_from = assessment_from.scores_json or {}
    scores_to = assessment_to.scores_json or {}
    dims_from = scores_from.get("dimensions") or {}
    dims_to = scores_to.get("dimensions") or {}

    dimensions: dict[str, dict] = {}
    for name in sorted(set(dims_from) | set(dims_to)):
        a = (dims_from.get(name) or {}).get("score")
        b = (dims_to.get(name) or {}).get("score")
        delta = round(b - a, 1) if (a is not None and b is not None) else None
        dimensions[name] = {"from": a, "to": b, "delta": delta}

    overall_from = assessment_from.quality_score
    overall_to = assessment_to.quality_score
    overall_delta = (
        round(overall_to - overall_from, 1)
        if (overall_from is not None and overall_to is not None)
        else None
    )

    issues_from = {_issue_signature(i): i for i in (assessment_from.issues_json or [])}
    issues_to = {_issue_signature(i): i for i in (assessment_to.issues_json or [])}
    sig_from = set(issues_from)
    sig_to = set(issues_to)

    def best_for(signature: str, pool: dict) -> dict:
        return pool[signature]

    repeated: list[dict] = []
    severity_changed: list[dict] = []
    for signature in sig_from & sig_to:
        issue_a = issues_from[signature]
        issue_b = issues_to[signature]
        entry = {
            "kind": issue_b["kind"],
            "columns": issue_b.get("columns", []),
            "severity": issue_b["severity"],
            "message": issue_b["message"],
        }
        repeated.append(entry)
        if issue_a["severity"] != issue_b["severity"]:
            severity_changed.append(
                {
                    "kind": issue_b["kind"],
                    "columns": issue_b.get("columns", []),
                    "from": issue_a["severity"],
                    "to": issue_b["severity"],
                }
            )

    new_issues = [dict(i) for sig, i in issues_to.items() if sig not in sig_from]
    resolved_issues = [dict(i) for sig, i in issues_from.items() if sig not in sig_to]

    (from_a, from_b) = map(int, (assessment_from.row_count or 0,
                                 assessment_to.row_count or 0))
    (from_c, to_c) = map(int, (assessment_from.column_count or 0,
                               assessment_to.column_count or 0))

    compatibility = _schema_difference(assessment_from, assessment_to)

    return {
        "overall": {"from": overall_from, "to": overall_to, "delta": overall_delta},
        "dimensions": dimensions,
        "issues": {
            "repeated": repeated,
            "new": new_issues,
            "resolved": resolved_issues,
            "severity_changed": severity_changed,
        },
        "shape": {
            "rows": {"from": from_a, "to": from_b},
            "columns": {"from": from_c, "to": to_c},
            "schema_changed": from_c != to_c,
        },
        "columns_changed": compatibility,
        "verdict": _verdict(overall_delta),
    }


def _schema_difference(assessment_from, assessment_to) -> list[str]:
    """Column-level differences between two assessments (best effort)."""
    try:
        columns_from = {entry["name"] for entry in (assessment_from.profile_json or {}).get("columns", [])}
        columns_to = {entry["name"] for entry in (assessment_to.profile_json or {}).get("columns", [])}
    except (AttributeError, KeyError, TypeError):
        return ["Column structure could not be verified."]
    added = sorted(columns_to - columns_from)
    removed = sorted(columns_from - columns_to)
    notes: list[str] = []
    if added:
        notes.append("Added columns: " + ", ".join(added))
    if removed:
        notes.append("Removed columns: " + ", ".join(removed))
    return notes


def _verdict(delta: float | None) -> str:
    if delta is None:
        return "Comparison could not compute a score delta."
    if delta == 0:
        return "No overall quality change."
    if delta > 0:
        return f"Quality improved by {delta:g} points."
    return f"Quality degraded by {abs(delta):g} points."
