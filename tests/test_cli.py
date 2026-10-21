"""Tests for the operational CLI commands (flask create-user)."""
from __future__ import annotations


def _invoke(app, *args, **kwargs):
    return app.test_cli_runner().invoke(args=list(args), **kwargs)


def test_create_user_creates_hashed_account(app):
    result = _invoke(
        app,
        "create-user",
        "--username", "opsuser",
        "--email", "ops@example.com",
        "supersafe99",
    )
    assert result.exit_code == 0, result.output
    assert "Created user 'opsuser'" in result.output

    from datasure.extensions import db
    from datasure.models import User

    with app.app_context():
        user = db.session.query(User).filter_by(username="opsuser").one()
        assert user.email == "ops@example.com"
        assert user.password_hash != "supersafe99"          # never plaintext
        assert user.check_password("supersafe99")


def test_create_user_rejects_short_password(app):
    result = _invoke(
        app,
        "create-user",
        "--username", "shorty",
        "--email", "short@example.com",
        "tiny",
    )
    assert result.exit_code != 0
    assert "at least 8 characters" in result.output

    from datasure.extensions import db
    from datasure.models import User

    with app.app_context():
        assert (
            db.session.query(User).filter_by(username="shorty").first() is None
        )


def test_create_user_rejects_invalid_email(app):
    result = _invoke(
        app,
        "create-user",
        "--username", "bademail",
        "--email", "not-an-email",
        "goodpassword1",
    )
    assert result.exit_code != 0
    assert "valid email" in result.output


def test_create_user_rejects_duplicate_username(app):
    first = _invoke(
        app,
        "create-user",
        "--username", "dup",
        "--email", "dup@example.com",
        "goodpassword1",
    )
    assert first.exit_code == 0

    second = _invoke(
        app,
        "create-user",
        "--username", "dup",
        "--email", "other@example.com",
        "goodpassword1",
    )
    assert second.exit_code != 0
    assert "already taken" in second.output


def test_create_user_rejects_duplicate_email(app):
    first = _invoke(
        app,
        "create-user",
        "--username", "first",
        "--email", "shared@example.com",
        "goodpassword1",
    )
    assert first.exit_code == 0

    second = _invoke(
        app,
        "create-user",
        "--username", "second",
        "--email", "shared@example.com",
        "goodpassword1",
    )
    assert second.exit_code != 0
    assert "already registered" in second.output


def test_create_user_prompts_and_confirms_password(app):
    result = _invoke(
        app,
        "create-user",
        "--username", "prompted",
        "--email", "prompted@example.com",
        input="secretz123\nsecretz123\n",
    )
    assert result.exit_code == 0, result.output

    from datasure.extensions import db
    from datasure.models import User

    with app.app_context():
        user = db.session.query(User).filter_by(username="prompted").one()
        assert user.check_password("secretz123")


def test_create_user_prompt_mismatch_fails(app):
    result = _invoke(
        app,
        "create-user",
        "--username", "mismatch",
        "--email", "mismatch@example.com",
        input="secretz123\nsecretz456\n",
    )
    assert result.exit_code != 0
    assert "do not match" in result.output
