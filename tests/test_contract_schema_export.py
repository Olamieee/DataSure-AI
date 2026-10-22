"""Contract → JSON Schema translation and download."""
from __future__ import annotations

import io
import json

from datasure.contracts.schema_export import contract_to_json_schema


def _upload_and_create_contract(client, name: str = "the contract") -> tuple[int, int]:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("name,age\nA,29\nB,39\n".encode()),
                       "schema_src.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    dataset_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    resp = client.post(
        f"/contracts/create/{dataset_id}",
        data={"name": name, "description": "generated"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.data
    contract_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    return dataset_id, contract_id


def test_contract_to_json_schema_shape():
    schema = contract_to_json_schema({
        "allow_extra_columns": False,
        "columns": [
            {"name": "age", "kind": "numeric", "nullable": False},
            {"name": "flag", "kind": "boolean", "nullable": True},
            {"name": "tier", "kind": "categorical", "nullable": True,
             "allowed_values": ["A", "B"]},
            {"name": "weird-kind", "kind": "mystery", "nullable": True},
        ],
    })
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["type"] == "object"
    # numeric accepts ints and floats
    assert schema["properties"]["age"] == {"type": ["number"]}
    assert schema["required"] == ["age"]  # nullable=True keeps others optional
    assert schema["properties"]["flag"] == {"type": ["boolean"]}
    assert schema["properties"]["tier"] == {"type": ["string"], "enum": ["A", "B"]}
    # unknown kinds are documented, not guessed
    assert "type" not in schema["properties"]["weird-kind"]
    assert schema["additionalProperties"] is False


def test_export_download_is_valid_json_schema(logged_in_user):
    client = logged_in_user["client"]
    _dataset_id, contract_id = _upload_and_create_contract(client)

    resp = client.get(f"/contracts/{contract_id}/export.schema.json")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition and "_schema.json" in disposition

    schema = json.loads(resp.data)
    assert schema["type"] == "object"
    assert "the_contract" in disposition  # name sanitised into the filename
    names = list(schema["properties"])
    assert names == ["name", "age"]
    # generated contracts mark every column nullable; nothing is required
    assert "required" not in schema


def test_export_is_scoped(logged_in_user, second_user):
    client = logged_in_user["client"]
    _dataset_id, contract_id = _upload_and_create_contract(client)

    resp = second_user.get(f"/contracts/{contract_id}/export.schema.json")
    assert resp.status_code == 404

    resp = client.get(f"/contracts/{contract_id}/export.schema.json")
    assert resp.status_code == 200


def test_export_button_on_detail_page(logged_in_user):
    client = logged_in_user["client"]
    _dataset_id, contract_id = _upload_and_create_contract(client)

    resp = client.get(f"/contracts/{contract_id}")
    body = resp.data.decode("utf-8", errors="replace")
    assert "Export JSON Schema" in body
