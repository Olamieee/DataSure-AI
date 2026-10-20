"""Tests for the validation rule engine and rule normalisation."""
from __future__ import annotations

import pandas as pd
import pytest

from datasure.rules import (
    COMPARISON_OPERATORS,
    RULE_TYPES,
    RuleDefinitionError,
    check,
    normalise_rule,
    run_rules,
)
from datasure.rules.engine import _parsed_pair


class _Rule:
    def __init__(self, name, rule_type, rule_json, id=1):
        self.name, self.rule_type, self.rule_json, self.id = name, rule_type, rule_json, id


def _frame():
    return pd.DataFrame({
        "age": [29, 30, 31, 32],
        "city": ["London", "Paris", "London", "Lisbon"],
        "start": ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"],
        "end": ["2024-06-01", "2024-02-01", "2024-12-01", "2024-03-15"],
        "id": [1, 2, 3, 3],
    })


# --------------------------------------------------------------------------- normalisation
def test_unknown_rule_type_rejected():
    with pytest.raises(RuleDefinitionError, match="unknown rule type"):
        normalise_rule("shellexec", {"column": "a"})


def test_expression_like_rule_type_never_exists():
    # no matter what a rule claims, only the fixed registry responds
    assert "shellexec" not in RULE_TYPES
    with pytest.raises(RuleDefinitionError):
        normalise_rule("eval", {})


def test_comparison_operator_whitelist():
    with pytest.raises(RuleDefinitionError, match="free-form expressions are not permitted"):
        normalise_rule("column_comparison",
                       {"left": "a", "right": "b", "operator": "__import__"})
    assert "__import__" not in COMPARISON_OPERATORS


def test_numeric_range_validates_params():
    with pytest.raises(RuleDefinitionError, match="must be a number"):
        normalise_rule("numeric_range", {"column": "a", "min": "abc"})
    with pytest.raises(RuleDefinitionError, match="requires min and/or max"):
        normalise_rule("numeric_range", {"column": "a"})
    with pytest.raises(RuleDefinitionError, match="does not accept"):
        normalise_rule("numeric_range", {"column": "a", "min": 0, "extra": True})
    ok = normalise_rule("numeric_range", {"column": "a", "min": 0, "max": 10})
    assert ok["min"] == 0.0 and ok["inclusive"] is True


def test_allowed_values_validates_params():
    with pytest.raises(RuleDefinitionError, match="non-empty"):
        normalise_rule("allowed_values", {"column": "a", "values": []})
    with pytest.raises(RuleDefinitionError, match="valid 'column'"):
        normalise_rule("allowed_values", {"column": " ", "values": ["x"]})


def test_severity_restricted():
    with pytest.raises(RuleDefinitionError, match="severity must be"):
        normalise_rule("not_null", {"column": "a", "severity": "critical"})


def test_control_characters_rejected_in_column_names():
    with pytest.raises(RuleDefinitionError, match="valid 'column'"):
        normalise_rule("not_null", {"column": "a\x00b"})


# --------------------------------------------------------------------------- engine
def test_not_null_rule():
    frame = pd.DataFrame({"a": [1, None, 3]})
    summary = check(frame, "not_null", {"column": "a"})
    assert not summary["passed"] and "1 missing" in summary["message"]
    assert check(pd.DataFrame({"a": [1, 2]}), "not_null", {"column": "a"})["passed"]


def test_unique_rule():
    frame = _frame()
    summary = check(frame, "unique", {"column": "id"})
    assert not summary["passed"]
    assert check(frame.assign(id=[1, 2, 3, 4]), "unique", {"column": "id"})["passed"]
    # missing values do not count as duplicates of each other
    empty_frame = pd.DataFrame({"a": [1, None, None, 2]})
    assert check(empty_frame, "unique", {"column": "a"})["passed"]


def test_allowed_values_rule():
    frame = pd.DataFrame({"city": ["London", "Atlantis"]})
    summary = check(frame, "allowed_values", {"column": "city", "values": ["London"]})
    assert not summary["passed"] and "outside the allowed set" in summary["message"]


def test_numeric_range_rule_bounds_and_text():
    frame = pd.DataFrame({"age": [5, 29, "old", None]})
    summary = check(frame, "numeric_range", {"column": "age", "min": 18, "max": 100})
    assert not summary["passed"]
    assert "2 value(s)" in summary["message"]
    assert check(pd.DataFrame({"age": [29, 30]}), "numeric_range",
                 {"column": "age", "min": 18})["passed"]


def test_numeric_range_exclusive():
    frame = pd.DataFrame({"age": [18, 19]})
    summary = check(frame, "numeric_range",
                    {"column": "age", "min": 18, "inclusive": False})
    assert not summary["passed"]


def test_column_comparison_dates():
    frame = _frame()
    summary = check(frame, "column_comparison",
                    {"left": "start", "right": "end", "operator": "<="})
    assert not summary["passed"]  # row 4: end before start
    parsed = _parsed_pair(frame["start"], frame["end"])
    assert parsed.left.notna().all()


def test_column_comparison_numeric_and_missing():
    frame = pd.DataFrame({"a": [1, 5, None, "x"], "b": [2, 5, 9, 9]})
    summary = check(frame, "column_comparison", {"left": "a", "right": "b", "operator": "<="})
    assert not summary["passed"]
    # a<=b fails nowhere (1<=2, 5<=5), but row 3 (None) and row 4 ('x') are incomparable
    assert "2 row(s) could not be compared" in summary["message"]


def test_column_comparison_equal():
    frame = pd.DataFrame({"a": [1, 2], "b": [1, 3]})
    summary = check(frame, "column_comparison", {"left": "a", "right": "b", "operator": "=="})
    assert not summary["passed"]
    assert check(pd.DataFrame({"a": [2], "b": [2]}), "column_comparison",
                 {"left": "a", "right": "b", "operator": "=="})["passed"]


def test_missing_column_fails_loudly():
    frame = _frame()
    for rule_type, params in (("not_null", {"column": "ghost"}),
                              ("unique", {"column": "ghost"}),
                              ("allowed_values", {"column": "ghost", "values": ["x"]}),
                              ("numeric_range", {"column": "ghost", "min": 0}),
                              ("column_comparison", {"left": "ghost", "right": "age",
                                                     "operator": "<="})):
        summary = check(frame, rule_type, params)
        assert not summary["passed"] and "does not exist" in summary["message"]


def test_run_rules_returns_rule_identity_():
    frame = _frame()
    rules = [
        _Rule("id unique", "unique", {"column": "id"}),
        _Rule("city set", "allowed_values", {"column": "city", "values": ["London"]}),
    ]
    results = run_rules(frame, rules)
    assert results[0]["name"] == "id unique" and results[0]["id"] == 1
    assert results[0]["passed"] is False
    assert results[1]["passed"] is False
