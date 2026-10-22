"""Contract → JSON Schema translation (draft 2020-12).

The generated schema is a portable artifact: teams can reuse their DataSure
contract in editors, spreadsheets and other pipelines that accept JSON Schema.
Only documentable type constraints are mapped — quality heuristics (missing
rates, uniqueness) are deliberately excluded because they are not boolean
data-shape checks.
"""
from __future__ import annotations

from typing import Any

_KIND_TYPE_MAP = {
    "numeric": {"type": ["number"]},
    "boolean": {"type": ["boolean"]},
    "datetime": {"type": ["string"]},
    "categorical": {"type": ["string"]},
    "text": {"type": ["string"]},
}


def contract_to_json_schema(contract_json: dict[str, Any]) -> dict[str, Any]:
    """Render the stored contract as a JSON Schema object.

    Numeric kinds accept both integers and floats; allowed_values becomes an
    ``enum``; columns that are not nullable become ``required``. Unknown kinds
    are treated as unconstrained (they get no ``type``) rather than guessed.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for column in contract_json.get("columns", []) or []:
        name = str(column.get("name") or "")
        if not name:
            continue
        kind = column.get("kind")
        constraint: dict[str, Any] = {}
        constraint.update(_KIND_TYPE_MAP.get(kind, {}))
        allowed = column.get("allowed_values")
        if allowed is not None:
            constraint["enum"] = [
                value if isinstance(value, (int, float, bool, str)) else str(value)
                for value in allowed
            ]
        properties[name] = constraint
        if column.get("nullable") is False:
            required.append(name)

    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "DataSure contract",
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    if not contract_json.get("allow_extra_columns", True):
        schema["additionalProperties"] = False
    return schema
