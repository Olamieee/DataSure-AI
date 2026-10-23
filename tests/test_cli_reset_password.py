"""flask reset-password: no-SMTP account recovery for server operators."""
from __future__ import annotations

import io


def _upload(client) -> int:
    resp = client.post(
        "/datasets/upload",
        data={"file": (io.BytesIO("a,b\n1,2\n".encode()), "rp.csv")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_reset_replaces_password(app, logged_in_user):
    client = logged_in_user["client"]
    _upload(client)  # gives the account some state to keep

    result = app.test_cli_runner().invoke(
        input="brandnewpass1\nbrandnewpass1\n",
        args=["reset-password", "--username", "testuser"],
    )
    assert result.exit_code == 0, result.output
    assert "Password replaced" in result.output

    from datasure.extensions import db
    from datasure.models import User

    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        assert user.check_password("brandnewpass1")
        assert not user.check_password("goodpassword1")


def test_reset_records_audit_event(app, logged_in_user):
    from datasure.extensions import db
    from datasure.models import AuditEvent, User

    result = app.test_cli_runner().invoke(
        input="brandnewpass1\nbrandnewpass1\n",
        args=["reset-password", "--username", "testuser"],
    )
    assert result.exit_code == 0

    with app.app_context():
        user = db.session.query(User).filter_by(username="testuser").one()
        events = (
            AuditEvent.query.filter_by(
                action="password_reset_cli", user_id=user.id
            ).all()
        )
        assert len(events) == 1


def test_reset_shows_up_on_activity_page(app, logged_in_user):
    client = logged_in_user["client"]
    result = app.test_cli_runner().invoke(
        input="brandnewpass1\nbrandnewpass1\n",
        args=["reset-password", "--username", "testuser"],
    )
    assert result.exit_code == 0

    resp = client.get("/settings/activity?action=password_reset_cli")
    body = resp.data.decode("utf-8", errors="replace")
    assert "password_reset_cli" in body


def test_unknown_username_fails_cleanly(app):
    result = app.test_cli_runner().invoke(
        input="whatever1\nwhatever1\n",
        args=["reset-password", "--username", "ghost"],
    )
    assert result.exit_code != 0
    assert "No account named 'ghost'" in result.output


def test_short_password_is_refused(app, logged_in_user):
    result = app.test_cli_runner().invoke(
        input="short\nshort\n",
        args=["reset-password", "--username", "testuser"],
    )
    assert result.exit_code != 0
    assert "at least 8 characters" in result.output


def test_reset_account_can_log_in_back(app):
    """The reset account authenticates with the new credential."""
    app.test_client().post("/register", data={
        "username": "recoverme", "email": "r@example.com",
        "password": "stalepassword1", "confirm_password": "stalepassword1",
    }, follow_redirects=False)

    result = app.test_cli_runner().invoke(
        input="brandnewpass1\nbrandnewpass1\n",
        args=["reset-password", "--username", "recoverme"],
    )
    assert result.exit_code == 0

    # the stale credential no longer logs in (fresh, unauthenticated client)
    stale_client = app.test_client()
    stale = stale_client.post("/login", data={
        "username": "recoverme", "password": "stalepassword1",
    }, follow_redirects=True)
    assert "Invalid username or password" in stale.data.decode(
        "utf-8", errors="replace"
    )

    # the new credential does
    resp = app.test_client().post("/login", data={
        "username": "recoverme", "password": "brandnewpass1",
    }, follow_redirects=False)
    assert resp.status_code == 302  # login accepted
