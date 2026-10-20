"""Tests for schema contracts: creation and validation service."""
from __future__ import annotations

import pandas as pd
import pytest

from datasure.contracts import contract_from_dataframe, summarise_contract, validate_dataframe


def _age_city_frame():
    return pd.DataFrame({
        "age": [29, 30, 31, 32],
        "city": ["London", "Paris", "London", "Lisbon"],
    })


def test_valid_dataset_produces_no_violations():
    contract = {
        "columns": [
            {"name": "age", "kind": "numeric", "nullable": False},
            {"name": "city", "kind": "categorical", "nullable": True,
             "allowed_values": ["London", "Paris", "Lisbon"]},
        ]
    }
    assert validate_dataframe(_age_city_frame(), contract) == []


def test_missing_required_column_violation():
    contract = {"columns": [{"name": "salary", "kind": "numeric"}]}
    violations = validate_dataframe(_age_city_frame(), contract)
    assert any(v["type"] == "missing_column" and "salary" in v["message"] for v in violations)


def test_extra_columns_rejected_when_disallowed():
    contract = {"allow_extra_columns": False, "columns": [{"name": "age", "kind": "numeric"}]}
    violations = validate_dataframe(
        pd.DataFrame({"age": [1], "unwanted": [2]}), contract
    )
    assert any(v["type"] == "extra_column" and "unwanted" in v["message"] for v in violations)


def test_extra_columns_allowed_by_default():
    contract = {"columns": [{"name": "age", "kind": "numeric"}]}
    assert validate_dataframe(pd.DataFrame({"age": [1], "x": [2]}), contract) == []


def test_not_nullable_reports_missing_counts():
    frame = pd.DataFrame({"age": [1, None, 3]})
    contract = {"columns": [{"name": "age", "kind": "numeric", "nullable": False}]}
    violations = validate_dataframe(frame, contract)
    assert any(v["type"] == "not_nullable" and "1 value" in v["message"] for v in violations)


def test_numeric_kind_reports_non_numeric_examples():
    frame = pd.DataFrame({"age": [29, "thirty", 31]})
    contract = {"columns": [{"name": "age", "kind": "numeric"}]}
    violations = validate_dataframe(frame, contract)
    message = next(v["message"] for v in violations if v["type"] == "wrong_kind")
    assert "do not qualify" in message and "thirty" in message


def test_categorical_allowed_values():
    frame = pd.DataFrame({"city": ["London", "Atlantis"]})
    contract = {"columns": [{"name": "city", "kind": "categorical",
                             "allowed_values": ["London", "Paris"]}]}
    violations = validate_dataframe(frame, contract)
    message = next(v["message"] for v in violations if v["type"] == "value_not_allowed")
    assert "Atlantis" in message


def test_boolean_kind_accepts_common_literals():
    frame_with_ok = pd.DataFrame({"flag": ["true", "False", "1", "0", "yes"]})
    contract = {"columns": [{"name": "flag", "kind": "boolean"}]}
    assert validate_dataframe(frame_with_ok, contract) == []


def test_datetime_kind():  # noqa: F811
    frame = pd.DataFrame({"when": ["2024-01-01", "definitely-not", 42]})
    contract = {"columns": [{"name": "when", "kind": "datetime"}]}
    violations = validate_dataframe(frame, contract)
    assert any(v["type"] == "wrong_kind" for v in violations)


def test_empty_column_non_nullable():
    frame = pd.DataFrame({"age": [None, None, None]})
    contract = {"columns": [{"name": "age", "kind": "numeric", "nullable": False}]}
    violations = validate_dataframe(frame, contract)
    assert any(v["type"] == "not_nullable" for v in violations)


def test_contract_generated_from_dataframe():
    df = _age_city_frame()
    contract = contract_from_dataframe(df, "people")
    assert contract["columns"][0]["name"] == "age"
    assert contract["columns"][0]["kind"] == "numeric"
    summarised = summarise_contract(contract)
    cities = next(row for row in summarised if row["name"] == "city")
    assert set(cities["allowed_values"]) == {"London", "Paris", "Lisbon"}
