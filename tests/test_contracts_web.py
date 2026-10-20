"""Web tests for schema contract management pages and validation runs."""
from __future__ import annotations

import io


def _upload(client, content: bytes, name: str = "contractdata.csv") -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(content), name)},
        content_type="multipart/form-data", follow_redirects=False,
    )
    assert resp.status_code == 302, resp.data[:200]
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _latest_contract_id(app) -> int:
    from datasure.models import SchemaContract, db
    with app.app_context():
        return db.session.query(SchemaContract).order_by(
            SchemaContract.id.desc()).first().id


GOOD_CSV = b"name,age,city\nA,29,London\nB,30,Paris\nC,31,London\nD,32,Lisbon\n"


def test_create_contract_from_dataset_page(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, GOOD_CSV)
    resp = client.post(
        f"/contracts/create/{dataset_id}",
        data={"name": "people contract"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"people contract" in resp.data
    assert b"allowed values" in resp.data or b"Allowed values" in resp.data


def test_contract_detail_lists_expected_columns(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, GOOD_CSV)
    client.post(f"/contracts/create/{dataset_id}", data={"name": "schema10"},
                follow_redirects=True)
    contract_id = _latest_contract_id(app)
    resp = client.get(f"/contracts/{contract_id}")
    assert resp.status_code == 200
    assert b"name" in resp.data and b"city" in resp.data
    assert b"numeric" in resp.data


def test_validate_dataset_pass_and_fail_and_record(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, GOOD_CSV)
    client.post(f"/contracts/create/{dataset_id}", data={"name": "std people"},
                follow_redirects=True)
    contract_id = _latest_contract_id(app)

    # pass case
    resp = client.post(
        f"/contracts/validate/{dataset_id}",
        data={"contract_id": contract_id}, follow_redirects=True,
    )
    assert b"satisfies contract" in resp.data

    # break the file, validate again; violations page readable
    from pathlib import Path
    from datasure.models import Dataset, db
    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        path = Path(app.instance_path) / "uploads" / f"user_{logged_in_user['user_id']}" / dataset.storage_filename
    path.write_bytes(b"name,age,city\nA,twenty-nine,London\nB,30,Lisbon\nC,31,Atlantis\nD,32,London\n")
    resp = client.post(
        f"/contracts/validate/{dataset_id}",
        data={"contract_id": contract_id},
    )
    page = resp.data.decode("utf-8")
    assert "wrong_kind" in page and "outside the allowed set" in page
    assert "twenty-nine" in page and "Atlantis" in page

    # result recorded on dataset
    with app.app_context():
        dataset = db.session.get(Dataset, dataset_id)
        assert dataset.contract_id == contract_id
        assert dataset.contract_passed is False


def test_cross_user_contract_endpoints_blocked(app, logged_in_user, second_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, GOOD_CSV)
    client.post(f"/contracts/create/{dataset_id}", data={"name": "private"},
                follow_redirects=True)
    contract_id = _latest_contract_id(app)
    own_dataset = _upload(second_user, GOOD_CSV, "other.csv")

    assert second_user.get(f"/contracts/{contract_id}").status_code == 404
    resp = second_user.post(
        f"/contracts/validate/{own_dataset}",
        data={"contract_id": contract_id}, follow_redirects=True,
    )
    assert b"not found" in resp.data or b"contract" in resp.data.lower()
    assert second_user.post(
        f"/contracts/{contract_id}/delete", follow_redirects=False
    ).status_code == 404
    assert client.get("/contracts/").status_code == 200  # owner can still list


def test_contract_delete_works_and_datasets_unaffected(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, GOOD_CSV)
    resp = client.post(
        f"/contracts/create/{dataset_id}", data={"name": "temp"},
        follow_redirects=False,
    )
    contract_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    client.post(f"/contracts/{contract_id}/delete", follow_redirects=True)
    resp = client.get("/contracts")
    assert b"temp" not in resp.data
    # dataset page still fine, no contract assigned
    assert client.get(f"/datasets/{dataset_id}").status_code == 200


def test_contracts_page_requires_login(client):
    resp = client.get("/contracts/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_contract_name_required(app, logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, GOOD_CSV)
    resp = client.post(
        f"/contracts/create/{dataset_id}", data={"name": ""},
        follow_redirects=True,
    )
    assert b"contract a name" in resp.data
