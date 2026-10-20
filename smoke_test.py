"""Quick manual smoke test (dev helper, run with the venv python)."""
import io
import tempfile
from pathlib import Path

from werkzeug.test import Client
import sys
sys.path.insert(0, ".")

from datasure import create_app
from datasure.extensions import db
from datasure.models import User

app = create_app("testing")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["TESTING"] = True

with app.app_context():
    db.create_all()
    user = User(username="smoketest", email="smoke@example.com")
    user.set_password("smokepass123")
    db.session.add(user)
    db.session.commit()

client = app.test_client()

# register a fresh user through the UI
resp = client.post("/register", data={
    "username": "tester", "email": "tester@example.com",
    "password": "goodpassword1", "confirm_password": "goodpassword1",
}, follow_redirects=False)
assert resp.status_code == 302, f"register failed: {resp.status_code} {resp.data[:300]}"

# login
resp = client.post("/login", data={"username": "tester", "password": "goodpassword1"},
                   follow_redirects=True)
assert b"Dashboard" in resp.data, "login failed"

# upload a CSV with deliberate quality problems
csv_content = (
    "id,name,age,country,salary,bonus,duplicate_of_age\n"
    "1,Alice,29,UK ,48000,100,29\n"
    "2,Bob,,UK ,52000,120,52\n"
    "2,Bob,,UK ,52000,120,52\n"
    "3,Charlie,41,U SA ,58000,,41\n"
    "4,Dave,35,UK ,47000,300,35\n"
    "5,Eve,29,UK ,,29,29\n"
    "6,Frank,50,UK ,61000,250,50\n"
    "7,Grace,44,UK ,55000,175,44\n"
    "8,Hank,33,UK ,900000,220,33\n"
)
resp = client.post("/datasets/upload", data={
    "file": (io.BytesIO(csv_content.encode("utf-8")), "employees test file.csv"),
}, content_type="multipart/form-data", follow_redirects=False)
assert resp.status_code == 302, f"upload failed: {resp.status_code} {resp.data[:500]}"
dataset_url = resp.headers["Location"]
dataset_id = int(dataset_url.rstrip("/").rsplit("/", 1)[-1])
print("uploaded dataset:", resp.headers["Location"])

# dataset detail renders
resp = client.get(f"/datasets/{dataset_id}")
assert resp.status_code == 200, "detail page failed"

# run assessment
resp = client.post(f"/datasets/{dataset_id}/assess",
                   data={"target_column": "country", "label": "smoke"},
                   follow_redirects=False)
assert resp.status_code == 302, f"assess failed: {resp.status_code} {resp.data[:500]}"

with app.app_context():
    from datasure.models import Assessment
    assessment = db.session.get(Assessment, 1)
    assert assessment is not None and assessment.quality_score is not None
    print("assessment score:", assessment.quality_score)
    print("issues:", [issue["kind"] for issue in assessment.issues_json])
    print("dimensions:", {k: v["score"] for k, v in assessment.scores_json["dimensions"].items()})

# assessment page + report
resp = client.get(f"/datasets/{dataset_id}/assessments/1")
assert resp.status_code == 200, "assessment page failed"
resp = client.get(f"/datasets/{dataset_id}/assessments/1/report")
assert resp.status_code == 200, f"report failed {resp.status_code}"
resp = client.get(f"/datasets/{dataset_id}/assessments/1/report?format=json")
assert resp.status_code == 200, "json report failed"

# clean preview + apply + download
resp = client.post(f"/datasets/{dataset_id}/clean/preview",
                   data={"operation": "drop_duplicate_rows", "param_keep": "first"},
                   follow_redirects=True)
assert b"Preview" in resp.data, "clean preview failed"

resp = client.post(f"/datasets/{dataset_id}/clean/apply",
                   data={"operation": "drop_duplicate_rows", "param_keep": "first"},
                   follow_redirects=True)
assert (b"applied and recorded" in resp.data), "clean apply failed"

resp = client.get(f"/datasets/{dataset_id}/download")
assert resp.status_code == 200, "download failed"

# API with API key
with app.app_context():
    from sqlalchemy import select
    from datasure.models import User
    from datasure.auth.apikeys import create_key
    u = db.session.scalar(select(User).where(User.username == "tester"))
    _record, raw_key = create_key(u, "smoke test key")
    db.session.commit()
resp = client.get("/api/v1/datasets", headers={"X-API-Key": raw_key})
assert resp.status_code == 200, f"api failed: {resp.status_code} {resp.data[:200]}"

with client.session_transaction() as sess:
    sess.clear()
resp = client.get("/api/v1/datasets")
assert resp.status_code == 401, "api must require auth when no session and no key"

# cross-user protection: anonymous user cannot access dataset pages
resp = client.get(f"/datasets/{dataset_id}", follow_redirects=False)
assert resp.status_code == 302 and "/login" in resp.headers["Location"], "anon access allowed!"

print("SMOKE TEST: ALL PASSED")
