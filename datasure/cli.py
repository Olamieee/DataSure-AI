"""Operational CLI commands for deployments without the web form.

These commands run inside the Flask application context and are registered on
a dedicated blueprint so ``flask --app datasure create-user ...`` works out of
the box in any environment.
"""
from __future__ import annotations

import re

import click
from flask import Blueprint

from .extensions import db
from .models import User

# cli_group=None exposes commands directly as `flask create-user ...`
bp = Blueprint("cli_commands", __name__, cli_group=None)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate(username: str, email: str, password: str) -> list[str]:
    """Mirror the web registration rules; returns a list of error messages."""
    errors: list[str] = []
    username = username.strip()
    if not (3 <= len(username) <= 64):
        errors.append("Username must be between 3 and 64 characters.")
    if not _EMAIL_RE.match(email):
        errors.append("Please enter a valid email address.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    return errors


@bp.cli.command("create-user")
@click.option("--username", required=True, help="Unique username (3-64 chars).")
@click.option("--email", required=True, help="Unique email address.")
@click.argument("password", required=False, default=None)
def create_user(username: str, email: str, password: str | None) -> None:
    """Create a user account without the web form.

    PASSWORD may be passed as an argument for scripted setups; note that
    shell history then holds it. Omitting it prompts securely (and asks for
    confirmation).
    """
    if password is None:
        password = click.prompt(
            "Password", hide_input=True, confirmation_prompt=True
        )

    errors = _validate(username, email, password)
    if errors:
        for message in errors:
            click.echo(f"error: {message}", err=True)
        raise click.exceptions.Exit(2)

    username = username.strip()
    if db.session.query(User).filter(User.username == username).first():
        raise click.UsageError(f"Username '{username}' is already taken.")
    if db.session.query(User).filter(User.email == email).first():
        raise click.UsageError(f"Email '{email}' is already registered.")

    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    click.echo(f"Created user '{username}' ({email}).")


@bp.cli.command("list-users")
def list_users() -> None:
    """List accounts: ids, usernames, emails, dataset counts."""
    from sqlalchemy import func

    from .models import Dataset, User

    query = (
        db.session.query(
            User.id,
            User.username,
            User.email,
            User.created_at,
            func.count(Dataset.id),
        )
        .outerjoin(Dataset, Dataset.user_id == User.id)
        .group_by(User.id)
        .order_by(User.id.asc())
        .all()
    )
    if not query:
        click.echo("No users yet. Create one with 'flask create-user'.")
        return
    for user_id, username, email, created_at, dataset_count in query:
        click.echo(
            f"#{user_id}\t{username}\t{email}\t"
            f"datasets={int(dataset_count)}\tcreated={created_at:%Y-%m-%d}"
        )


@bp.cli.command("check-config")
@click.option(
    "--config",
    "config_name",
    default=None,
    help="Check a specific config name (default: DATASURE_CONFIG or production).",
)
def check_config(config_name: str | None) -> None:
    """Report effective settings; problems exit 1 (safe for automation)."""
    import os
    import tempfile
    from pathlib import Path

    from .config import BASE_DIR

    conf = config_name or os.environ.get("DATASURE_CONFIG", "production")
    secrets_ok = os.environ.get("DATASURE_SECRET_KEY")
    database_url = os.environ.get("DATASURE_DATABASE_URL")
    instance_path = os.environ.get("DATASURE_INSTANCE_PATH") or str(
        BASE_DIR / "instance"
    )

    click.echo(f"Config: {conf}")
    if secrets_ok:
        click.echo(
            f"SECRET_KEY: set ({len(secrets_ok)} chars) - value is never printed"
        )
    else:
        click.echo("SECRET_KEY: MISSING (required outside testing)")

    if database_url:
        click.echo("DATABASE: explicit DATASURE_DATABASE_URL provided")
    else:
        click.echo(
            f"DATABASE: sqlite at {instance_path}/datasure.db "
            "(DATASURE_INSTANCE_PATH honouring)"
        )

    upload_mb = os.environ.get("DATASURE_MAX_UPLOAD_MB", "50")
    click.echo(
        f"LIMITS: max upload {upload_mb} MB, "
        f"max rows {os.environ.get('DATASURE_MAX_ROWS', '500000')}, "
        f"max columns {os.environ.get('DATASURE_MAX_COLUMNS', '400')}, "
        f"profile budget "
        f"{os.environ.get('DATASURE_PROFILE_TIME_BUDGET_SECONDS', '120')} s"
    )

    problems: list[str] = []
    if not secrets_ok and conf.lower() not in {"testing", "test"}:
        problems.append(
            "DATASURE_SECRET_KEY is not set; the app will refuse to start"
        )
    probe_dir = Path(instance_path)
    probe_fd = None
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe_fd, probe_name = tempfile.mkstemp(
            prefix="probe-", dir=str(probe_dir)
        )
        click.echo(f"INSTANCE PATH: {instance_path} (writable)")
    except OSError:
        problems.append(
            f"instance path '{instance_path}' is not writable"
        )
        click.echo(f"INSTANCE PATH: {instance_path} (NOT writable)")
    finally:
        if probe_fd is not None:
            os.close(probe_fd)  # Windows drags its feet on open handles
            try:
                Path(probe_name).unlink(missing_ok=True)
            except OSError:
                pass

    if problems:
        for problem in problems:
            click.echo(f"PROBLEM: {problem}", err=True)
        raise click.exceptions.Exit(1)
    click.echo("Config looks deployable.")


@bp.cli.command("prune-audits")
@click.option(
    "--days",
    type=click.IntRange(min=1),
    default=90,
    show_default=True,
    help="Delete audit events older than N days.",
)
def prune_audits(days: int) -> None:
    """Apply audit retention: remove events beyond the keeping window."""
    from datetime import timedelta

    from .models import AuditEvent, _utcnow

    cutoff = _utcnow().replace(tzinfo=None) - timedelta(days=days)
    deleted = (
        db.session.query(AuditEvent)
        .filter(AuditEvent.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    click.echo(f"Deleted {deleted} audit event(s) older than {days} day(s).")
