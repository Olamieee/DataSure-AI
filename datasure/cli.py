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
