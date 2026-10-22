"""Tests for the operational CLI: list-users and check-config."""
from __future__ import annotations


def _invoke(app, *args):
    return app.test_cli_runner().invoke(args=list(args))


def test_list_users_reports_accounts_and_dataset_counts(app, logged_in_user):
    result = _invoke(app, "list-users")
    assert result.exit_code == 0
    assert "testuser" in result.output
    assert "testuser@example.com" in result.output
    assert "datasets=0" in result.output


def test_list_users_empty_state(app):
    result = _invoke(app, "list-users")
    assert result.exit_code == 0
    assert "No users yet" in result.output


def test_check_config_reports_set_secret_and_limits(tmp_path, monkeypatch, app):
    monkeypatch.setenv("DATASURE_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path / "check-i"))
    result = _invoke(app, "check-config", "--config", "production")
    assert result.exit_code == 0, result.output
    assert "set (32 chars)" in result.output
    # the secret value itself must never appear in the output
    assert "x" * 20 not in result.output
    assert "LIMITS" in result.output
    assert "writable" in result.output
    assert "Config looks deployable" in result.output


def test_check_config_fails_without_secret_key(tmp_path, monkeypatch, app):
    monkeypatch.delenv("DATASURE_SECRET_KEY", raising=False)
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path / "no-key-i"))
    result = _invoke(app, "check-config", "--config", "production")
    assert result.exit_code != 0
    assert "DATASURE_SECRET_KEY is not set" in result.output


def test_check_config_reports_unwritable_instance_path(
    tmp_path, monkeypatch, app
):
    monkeypatch.setenv("DATASURE_SECRET_KEY", "some-key-value-1234567890")
    # a path under an existing FILE cannot be a directory
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file")
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(blocker / "nested"))
    result = _invoke(app, "check-config", "--config", "production")
    assert result.exit_code != 0
    assert "not writable" in result.output


def test_check_config_reports_database_origin(
    tmp_path, monkeypatch, app
):
    monkeypatch.setenv("DATASURE_SECRET_KEY", "some-key-value-1234567890")
    monkeypatch.setenv("DATASURE_DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    result = _invoke(app, "check-config", "--config", "production")
    assert result.exit_code == 0
    assert "explicit DATASURE_DATABASE_URL provided" in result.output
