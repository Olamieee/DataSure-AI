"""Settings → storage page: accurate live usage numbers, properly scoped."""
from __future__ import annotations

import io


def _upload(client, name: str, csv: str) -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO(csv.encode()), name)},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_storage_page_requires_login(client):
    resp = client.get("/settings/storage", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_storage_counts_own_uploads(logged_in_user):
    client = logged_in_user["client"]
    _upload(client, "small1.csv", "name,age\nA,29\n")
    csv2 = "name,age\n" + "".join(f"r{i},{i}\n" for i in range(500))
    _upload(client, "big1.csv", csv2)

    resp = client.get("/settings/storage")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert "Datasets stored" in body
    assert "big1.csv" in body  # largest dataset is named
    assert "small1.csv" not in body


def test_storage_zero_state(logged_in_user):
    resp = logged_in_user["client"].get("/settings/storage")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert "no datasets yet" in body


def test_storage_is_scoped_per_user(uploaded_messy_dataset, second_user):
    client = uploaded_messy_dataset["client"]
    dataset_id = uploaded_messy_dataset["dataset_id"]
    _upload(client, "another.csv", "name,age\nB,41\n")

    resp = second_user.get("/settings/storage")
    body = resp.data.decode("utf-8", errors="replace")
    assert "no datasets yet" in body  # zero datasets for user B


def test_storage_excludes_deleted_files(logged_in_user):
    client = logged_in_user["client"]
    dataset_id = _upload(client, "temporary.csv", "name,age\nA,29\n")
    client.post(f"/datasets/{dataset_id}/delete", follow_redirects=True)

    resp = client.get("/settings/storage")
    body = resp.data.decode("utf-8", errors="replace")
    assert "no datasets yet" in body
