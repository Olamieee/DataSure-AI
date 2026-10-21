"""The SQLite database must always follow DATASURE_INSTANCE_PATH."""
from __future__ import annotations

from pathlib import Path


def test_production_database_lives_in_instance_path(tmp_path, monkeypatch):
    """DATASURE_INSTANCE_PATH must control the database file location."""
    monkeypatch.setenv("DATASURE_SECRET_KEY", "path-test-key-not-secret")
    instance_dir = tmp_path / "honoured-instance"
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(instance_dir))

    from datasure import create_app

    application = create_app("production")
    expected_uri = f"sqlite:///{instance_dir / 'datasure.db'}"
    assert application.config["SQLALCHEMY_DATABASE_URI"] == expected_uri
    # create_app runs create_all(), so the file must physically exist there.
    assert (instance_dir / "datasure.db").exists()
    with application.app_context():
        pass


def test_explicit_database_url_wins_over_instance_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DATASURE_SECRET_KEY", "path-test-key-not-secret")
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path / "i"))
    monkeypatch.setenv("DATASURE_DATABASE_URL", "sqlite:///:memory:")

    from datasure import create_app

    application = create_app("production")
    assert application.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"


def test_testing_config_keeps_its_own_database_uri(tmp_path, monkeypatch):
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(tmp_path / "i"))

    from datasure import create_app

    application = create_app("testing")
    assert application.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"


def test_development_database_follows_instance_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DATASURE_SECRET_KEY", "path-test-key-not-secret")
    instance_dir = tmp_path / "dev-instance"
    monkeypatch.setenv("DATASURE_INSTANCE_PATH", str(instance_dir))

    from datasure import create_app

    application = create_app("development")
    assert application.config["SQLALCHEMY_DATABASE_URI"] == (
        f"sqlite:///{Path(instance_dir) / 'datasure.db'}"
    )
