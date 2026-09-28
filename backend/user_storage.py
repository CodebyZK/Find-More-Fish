"""Resolve private local storage for the authenticated GitLab account."""

from __future__ import annotations

from pathlib import Path

from flask import current_app, g, has_request_context

from .backend_config import DATA_DIR


def auth_required() -> bool:
    return has_request_context() and bool(current_app.config.get("AUTH_REQUIRED", True))


def user_data_dir() -> Path:
    if not auth_required():
        return DATA_DIR
    user_id = getattr(g, "gitlab_user_id", None)
    if not isinstance(user_id, int) or user_id <= 0:
        raise RuntimeError("Authenticated GitLab account required for private storage")
    root = Path(current_app.config.get("AUTH_DATA_DIR", DATA_DIR))
    return root / "users" / f"gitlab-{user_id}"
