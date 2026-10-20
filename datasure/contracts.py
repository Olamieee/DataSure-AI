"""Schema contract creation and validation.

A contract describes expected columns: kind, nullability and (optionally)
the permitted categorical values. Validation produces readable violations
rather than generic failures, e.g.:

    column 'age' must allow numbers, but 12% of its values are not numeric

Contracts are per-user resources; every check below operates on a plain
DataFrame so both uploads and future endpoints can reuse it.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

KIND_PARSERS = {
    "numeric": lambda values: pd.to_numeric(values, errors="coerce"),
    "datetime": lambda values: pd.to_datetime(values, errors="coerce", format="mixed"),
}

MAX_DISPLAYED_VIOLATIONS_PER_COLUMN = 5


def validate_dataframe(df: pd.DataFrame, contract: dict) -> list[dict]:
    """Validate a DataFrame against contract_json. Returns a violation list.

    Empty list means the dataset satisfies the contract.
    """
    violations: list[dict] = _structural_violations(df, contract)
    expected = {
        entry["name"]: entry for entry in contract.get("columns", [])
        if not entry.get("omit_on_upload")  # reserved for future use
    }
    for name, entry in expected.items():
        if name not in df.columns:
            continue
        violations.extend(_column_violations(name, entry, df[name]))
    return violations


def _structural_violations(df: pd.DataFrame, contract: dict) -> list[dict]:
    violations: list[dict] = []
    expected_names = [entry["name"] for entry in contract.get("columns", [])]
    allow_extra = bool(contract.get("allow_extra_columns", True))

    missing = [name for name in expected_names if name not in df.columns]
    if missing:
        violations.append(
            {
                "type": "missing_column",
                "column": ", ".join(missing),
                "message": f"required column(s) missing: {', '.join(missing)}",
            }
        )
    if not allow_extra:
        extras = [str(column) for column in df.columns if column not in expected_names]
        if extras:
            violations.append(
                {
                    "type": "extra_column",
                    "column": ", ".join(extras),
                    "message": f"columns not allowed by contract: {', '.join(extras)}",
                }
            )
    return violations


def _column_violations(name: str, entry: dict, values: pd.Series) -> list[dict]:
    violations: list[dict] = []
    kind = entry.get("kind")
    nullable = bool(entry.get("nullable", True))
    allowed = entry.get("allowed_values")

    non_null = values.dropna()
    if non_null.empty:
        if not nullable and values.notna().sum() == 0 and len(values) > 0:
            violations.append(
                {
                    "type": "not_nullable",
                    "column": name,
                    "message": f"column '{name}' cannot be empty but has no values",
                }
            )
        return violations

    missing_count = int(values.isna().sum())
    if missing_count and not nullable:
        violations.append(
            {
                "type": "not_nullable",
                "column": name,
                "message": (
                    f"column '{name}' is not nullable but {missing_count:,} "
                    "value(s) are missing"
                ),
            }
        )

    if kind == "numeric":
        coerced = pd.to_numeric(non_null, errors="coerce")
        bad = non_null[coerced.isna()]
        if len(bad):
            violations.append(_kind_violation(name, "numeric", bad))
    elif kind == "datetime":
        parsed = pd.to_datetime(non_null.astype(str), errors="coerce", format="mixed")
        bad = non_null[parsed.isna()]
        if len(bad):
            violations.append(_kind_violation(name, "datetime", bad))
    elif kind == "boolean":
        bad = non_null[~non_null.astype(str).str.lower().isin(
            {"true", "false", "0", "1", "yes", "no"})]
        if len(bad):
            violations.append(_kind_violation(name, "boolean", bad))
    if allowed is not None:
        unexpected = non_null[~non_null.astype(str).isin(
            {str(value) for value in allowed})]
        if len(unexpected):
            sample = list(dict.fromkeys(unexpected.astype(str)))[:MAX_DISPLAYED_VIOLATIONS_PER_COLUMN]
            violations.append(
                {
                    "type": "value_not_allowed",
                    "column": name,
                    "message": (
                        f"column '{name}' contains {len(unexpected):,} value(s) outside the "
                        f"allowed set; examples: {', '.join(repr(v) for v in sample)}"
                    ),
                }
            )
    return violations


def _kind_violation(name: str, kind: str, bad_values: pd.Series) -> dict:
    total = max(len(bad_values), 1)
    examples = [
        repr(value)[:40]
        for value in list(dict.fromkeys(bad_values.astype(str)))[:MAX_DISPLAYED_VIOLATIONS_PER_COLUMN]
    ]
    return {
        "type": "wrong_kind",
        "column": name,
        "message": (
            f"column '{name}' must contain only {kind} values, but {total:,} "
            f"value(s) do not qualify; examples: {', '.join(examples)}"
        ),
    }


def contract_from_dataframe(df: pd.DataFrame, name: str,
                            description: str | None = None) -> dict:
    """Build contract_json from an uploaded dataset's inferred schema."""
    from .datasets.ingest import dataframe_schema

    columns: list[dict[str, Any]] = []
    for entry in dataframe_schema(df):
        identifier = entry["kind"] == "identifier"
        series = df[entry["name"]]
        allowed = (
            sorted(series.dropna().astype(str).unique().tolist())[:50]
            if entry["kind"] in {"categorical", "boolean"}
            and series.nunique(dropna=True) <= 50 and not identifier
            else None
        )
        columns.append(
            {
                "name": entry["name"],
                "kind": "numeric" if entry["kind"] == "numeric" else (
                    "categorical" if entry["kind"] in {"categorical", "text", "boolean"} else entry["kind"]
                ),
                # Generated contracts default to permissive: nullable=True.
                # Users can tighten nullability by editing contract_json later.
                "nullable": True,
                "allowed_values": allowed,
            }
        )
    return {
        "allow_extra_columns": True,
        "columns": columns,
    }


def summarise_contract(contract: dict) -> list[dict]:
    """Compact display rows for templates."""
    rows = []
    for entry in contract.get("columns", []):
        rows.append(
            {
                "name": entry.get("name"),
                "kind": entry.get("kind"),
                "nullable": bool(entry.get("nullable", True)),
                "allowed_values": entry.get("allowed_values"),
            }
        )
    return rows
