from __future__ import annotations

import re

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import User

bp = Blueprint("auth", __name__)

USERNAME_PATTERN = re.compile(r"^[\w.\-]{3,64}$")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        errors: list[str] = []
        if not USERNAME_PATTERN.fullmatch(username):
            errors.append(
                "Username must be 3-64 characters (letters, digits, dot, dash, underscore)."
            )
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            errors.append("Please enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if not errors:
            if User.query.filter(User.username.ilike(username)).first():
                errors.append("Username already taken.")
            elif User.query.filter_by(email=email).first():
                errors.append("Email already registered.")
        if errors:
            for message in errors:
                flash(message, "danger")
            return render_template("auth/register.html", **_form_ctx(username, email)), 400

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Account created. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", **_form_ctx("", ""))


def _form_ctx(username: str, email: str) -> dict:
    return {"form_username": username, "form_email": email}


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        from .ratelimit import address_key, login_limiter, user_key
        from ..__init__ import get_correlation_id

        keys = (user_key(username), address_key(request.remote_addr or ""))
        for key in keys:
            blocked, seconds = login_limiter.is_blocked(key)
            if blocked:
                flash(
                    f"Too many failed attempts. Login is temporarily locked; "
                    f"try again in about {seconds // 60 + 1} minute(s).",
                    "danger",
                )
                app_logger = current_app.logger
                app_logger.warning(
                    "Login blocked by rate limit for key %s [req:%s]",
                    key.split(":", 1)[0] + ":***", get_correlation_id())
                return render_template("auth/login.html", form_username=username), 429

        user = User.query.filter(
            (User.username.ilike(username)) | (User.email == username.lower())
        ).first()
        if user is None or not user.check_password(password):
            for key in keys:
                login_limiter.record_failure(key)
            flash("Invalid username or password.", "danger")
            return render_template("auth/login.html", form_username=username), 401

        for key in keys:
            login_limiter.reset(key)
        login_user(user, remember=request.form.get("remember") == "on", fresh=True)
        next_target = request.args.get("next")
        # Only allow safe, relative next-URLs (no protocol/host tricks).
        if next_target and next_target.startswith("/") and not next_target.startswith("//"):
            return redirect(next_target)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html", form_username="")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))
