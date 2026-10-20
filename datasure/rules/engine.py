"""Reusable validation rules: a fixed registry of rule types.

Rules are structured data, never free-form expressions, so nothing in a
rule is ever evaluated with eval()/exec(): each rule type maps to an
explicit Python function and an allowed-operator map. Malformed rule
definitions FAIL LOUDLY with a descriptive error rather than guessing.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

RULE_TYPES = ("numeric_range", "allowed_values", "unique", "not_null",
              "column_comparison")
SEVERITIES = ("error", "warning")

# Explicit operator registry for column_comparison. Nothing outside this
# map can ever be executed, regardless of what a rule contains.
COMPARISON_OPERATORS = {
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

MAX_DISPLAYED_VALUES = 5


class RuleDefinitionError(ValueError):
    """Raised when a rule definition is malformed or uses an unknown type."""


# --------------------------------------------------------------------------- normalisation
def normalise_rule(rule_type: str, rule_json: dict) -> dict:
    """Validate/normalise a rule definition. Raises RuleDefinitionError."""
    if rule_type not in RULE_TYPES:
        raise RuleDefinitionError(
            f"unknown rule type '{rule_type}'; allowed: {', '.join(RULE_TYPES)}")
    rule_json = dict(rule_json or {})
    severity = rule_json.get("severity", "error")
    if severity not in SEVERITIES:
        raise RuleDefinitionError(f"severity must be one of {SEVERITIES}")
    rule_json["severity"] = severity

    if rule_type == "numeric_range":
        column = _column_name(rule_json.get("column"))
        if column is None:
            raise RuleDefinitionError("numeric_range requires a valid 'column'")
        unexpected = set(rule_json) - {"column", "min", "max", "inclusive", "severity"}
        if unexpected:
            raise RuleDefinitionError(
                f"numeric_range does not accept: {', '.join(sorted(unexpected))}")
        normalised: dict[str, Any] = {"column": column, "severity": severity}
        for key in ("min", "max"):
            if rule_json.get(key) is not None:
                try:
                    normalised[key] = float(rule_json[key])
                except (TypeError, ValueError) as exc:
                    raise RuleDefinitionError(f"'{key}' must be a number") from exc
        if not any(key in normalised for key in ("min", "max")):
            raise RuleDefinitionError("numeric_range requires min and/or max")
        normalised["inclusive"] = bool(rule_json.get("inclusive", True))
        return normalised

    if rule_type == "allowed_values":
        column = _column_name(rule_json.get("column"))
        values = rule_json.get("values")
        if column is None:
            raise RuleDefinitionError("allowed_values requires a valid 'column'")
        if not isinstance(values, list) or not values:
            raise RuleDefinitionError(
                "allowed_values requires a non-empty 'values' list")
        return {"column": column, "severity": severity,
                "values": [str(v)[:200] for v in values[:500]]}

    if rule_type in {"unique", "not_null"}:
        column = _column_name(rule_json.get("column"))
        if column is None:
            raise RuleDefinitionError(f"{rule_type} requires a valid 'column'")
        unexpected = set(rule_json) - {"column", "severity"}
        if unexpected:
            raise RuleDefinitionError(
                f"{rule_type} does not accept: {', '.join(sorted(unexpected))}")
        return {"column": column, "severity": severity}

    if rule_type == "column_comparison":
        left = _column_name(rule_json.get("left"))
        right = _column_name(rule_json.get("right"))
        operator = rule_json.get("operator")
        if left is None or right is None:
            raise RuleDefinitionError("column_comparison requires valid "
                                      "'left' and 'right' column names")
        if operator not in COMPARISON_OPERATORS:
            raise RuleDefinitionError(
                f"operator must be one of {sorted(COMPARISON_OPERATORS)}; "
                "free-form expressions are not permitted for safety")
        return {"left": left, "right": right, "operator": operator,
                "severity": severity}

    raise RuleDefinitionError(f"unreachable rule type '{rule_type}'")


# --------------------------------------------------------------------------- execution
def run_rules(df: pd.DataFrame, rules) -> list[dict]:
    """Apply rule-like objects (having .rule_type, .rule_json and .name)."""
    return [check(df, r.rule_type, r.rule_json) | {"name": r.name, "id": r.id}
            for r in rules]


def check(df: pd.DataFrame, rule_type: str, rule_json: dict) -> dict:
    """Apply one normalised rule to a DataFrame; returns a pass/fail summary."""
    rule = normalise_rule(rule_type, rule_json)

    if rule_type == "not_null":
        values = df.get(rule["column"])
        if values is None:
            return _failed(rule, f"column '{rule['column']}' does not exist in this dataset")
        count = int(values.isna().sum())
        if count == 0:
            return _passed()
        return _failed(
            rule,
            f"column '{rule['column']}' has {count:,} missing value(s)",
            _sample_index(values[values.isna()].index),
        )

    if rule_type == "unique":
        values = df.get(rule["column"])
        if values is None:
            return _failed(rule, f"column '{rule['column']}' does not exist in this dataset")
        duplicated = values.notna() & values.duplicated(keep=False)
        count = int(duplicated.sum())
        if count == 0:
            return _passed()
        return _failed(
            rule,
            f"column '{rule['column']}' has {count:,} value(s) belonging to duplicate groups",
            _sample_index(values[duplicated].index),
        )

    if rule_type == "allowed_values":
        values = df.get(rule["column"])
        if values is None:
            return _failed(rule, f"column '{rule['column']}' does not exist in this dataset")
        expected = {str(v) for v in rule["values"]}
        actual = values.dropna().astype(str)
        unexpected = actual[~actual.isin(expected)]
        count = int(unexpected.shape[0])
        if count == 0:
            return _passed()
        return _failed(
            rule,
            (f"column '{rule['column']}' has {count:,} value(s) outside the "
             "allowed set"),
            list(dict.fromkeys(unexpected.tolist()))[:MAX_DISPLAYED_VALUES],
        )

    if rule_type == "numeric_range":
        values = df.get(rule["column"])
        if values is None:
            return _failed(rule, f"column '{rule['column']}' does not exist in this dataset")
        coerced = pd.to_numeric(values, errors="coerce")
        not_numeric = values.notna() & coerced.isna()
        if rule.get("inclusive", True):
            bad = (coerced < rule.get("min", float("-inf"))) | \
                  (coerced > rule.get("max", float("inf")))
        else:
            bad = (coerced <= rule.get("min", float("-inf"))) | \
                  (coerced >= rule.get("max", float("inf")))
        bad = bad.fillna(False) | not_numeric
        count = int(bad.sum())
        if count == 0:
            return _passed()
        bounds = " and ".join(
            f"{'<=' if rule.get('inclusive', True) else '<'} {rule[key]:g}"
            for key in ("min", "max") if key in rule)
        return _failed(
            rule,
            (f"column '{rule['column']}' has {count:,} value(s) outside the "
             f"accepted range where the condition is {bounds}"),
            _sample_values(values[bad]),
        )

    if rule_type == "column_comparison":
        left_values, right_values = df.get(rule["left"]), df.get(rule["right"])
        if left_values is None or right_values is None:
            missing = rule["left"] if left_values is None else rule["right"]
            return _failed(rule, f"column '{missing}' does not exist in this dataset")
        parsed = _parsed_pair(left_values, right_values)
        comparable = parsed.left.notna() & parsed.right.notna()
        operator = COMPARISON_OPERATORS[rule["operator"]]
        failed_pairs = [
            not operator(l, r)
            for l, r in zip(parsed.left[comparable], parsed.right[comparable])
        ]
        bad = parsed.left.index[comparable][failed_pairs] if failed_pairs else []
        incomparable = (~comparable) & (left_values.notna() | right_values.notna())
        count = len(bad) + int(incomparable.sum())
        if count == 0:
            return _passed()
        note = ""
        if int(incomparable.sum()):
            note = (f"; {int(incomparable.sum()):,} row(s) could not be "
                    "compared (missing or unparseable)")
        return _failed(
            rule,
            (f"{len(bad):,} row(s) violate "
             f"'{rule['left']} {rule['operator']} {rule['right']}'{note}"),
            _sample_index(list(bad)[:MAX_DISPLAYED_VALUES]),
        )

    raise RuleDefinitionError(f"unreachable rule type '{rule_type}'")


class _ParsedPair:
    def __init__(self, left: pd.Series, right: pd.Series):
        self.left, self.right = left, right


def _parsed_pair(left_values: pd.Series, right_values: pd.Series) -> _ParsedPair:
    """Parse two columns for comparison: dates if both look datelike, else numbers."""
    left_date = _coerce_dates(left_values)
    right_date = _coerce_dates(right_values)
    if (_date_share(left_values, left_date) >= 0.9
            and _date_share(right_values, right_date) >= 0.9):
        return _ParsedPair(left_date, right_date)
    return _ParsedPair(
        pd.to_numeric(left_values, errors="coerce"),
        pd.to_numeric(right_values, errors="coerce"),
    )


def _coerce_dates(values: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(values.astype(str), errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(values, errors="coerce")


def _date_share(original: pd.Series, parsed: pd.Series) -> float:
    non_missing = original.notna().sum()
    if non_missing == 0:
        return 0.0
    return float(parsed.notna().sum()) / float(non_missing)


# --------------------------------------------------------------------------- helpers
def _column_name(value) -> str | None:
    if not isinstance(value, str):
        return None
    column = value.strip()
    if not column or len(column) > 200 or re.search(r"[\x00-\x1f]", column):
        return None
    return column


def _sample_index(index, limit: int = MAX_DISPLAYED_VALUES) -> list[str]:
    return [str(i)[:60] for i in list(index)[:limit]]


def _sample_values(values: pd.Series, limit: int = MAX_DISPLAYED_VALUES) -> list[str]:
    return [str(v)[:60] for v in list(values)[:limit]]


def _passed() -> dict:
    return {"passed": True, "count": 0, "message": "", "examples": [],
            "severity": "info"}


def _failed(rule: dict, message: str, examples: list[str] | None = None) -> dict:
    return {
        "passed": False,
        "count": 0,
        "message": message,
        "examples": examples or [],
        "severity": rule.get("severity", "error"),
    }
