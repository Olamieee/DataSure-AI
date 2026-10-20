"""Secure storage helpers for uploaded datasets and generated reports.

Design rules enforced here:
- File names are ALWAYS server-generated (UUID4 + safe extension).
- Client-provided file names are kept only as display metadata.
- Reads never construct paths from user input.
- Every dataset belongs to a user_id whose directory is the only access point.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path


def user_upload_dir(instance_path: str, user_id: int) -> Path:
    directory = Path(instance_path) / "uploads" / f"user_{user_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def safe_extension(client_filename: str, allowed: set[str]) -> str:
    """Return a normalised extension if allowed, else raise ValueError."""
    suffix = Path(client_filename).suffix.lower()
    if suffix not in allowed:
        raise ValueError(
            f"Unsupported file type '{suffix or 'unknown'}'. Allowed types: "
            + ", ".join(sorted(allowed))
        )
    return suffix


def generate_storage_filename(extension: str) -> str:
    return f"{uuid.uuid4().hex}{extension}"


def sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_display_name(client_filename: str, max_length: int = 200) -> str:
    """Sanitise a client-provided name used purely for display."""
    from pathlib import PurePosixPath, PureWindowsPath

    stripped = PureWindowsPath(client_filename).name
    stripped = PurePosixPath(stripped).name
    cleaned = "".join(
        ch if ch.isalnum() or ch in (" ", "-", "_", ".", "(") else "_"
        for ch in stripped
    ).strip(" ._")
    return (cleaned[:max_length] or "unnamed_dataset")


def delete_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
