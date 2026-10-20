"""Resolve private local storage for the authenticated GitLab account."""

from __future__ import annotations

from pathlib import Path
from collections import OrderedDict
from threading import Lock

from flask import current_app, g, has_request_context

from .config import AppConfig
from .storage.base import Storage
from .storage.local import LocalLogbookStore, LocalMediaStore


def auth_required() -> bool:
    return has_request_context() and bool(current_app.config.get("AUTH_REQUIRED", True))


def user_data_dir() -> Path:
    config = current_app.extensions["fish.config"]
    if not auth_required():
        return config.data_dir
    user_id = getattr(g, "gitlab_user_id", None)
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise RuntimeError("Authenticated GitLab account required for private storage")
    root = Path(current_app.config.get("AUTH_DATA_DIR", config.data_dir))
    return root / "users" / f"gitlab-{user_id}"


class AccountStorage:
    """Keep SQLite snapshots and every media operation inside one account root."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._accounts: OrderedDict[Path, Storage] = OrderedDict()
        self._lock = Lock()

    def current(self) -> Storage:
        root = user_data_dir()
        with self._lock:
            stores = self._accounts.pop(root, None)
            if stores is None:
                logbook = LocalLogbookStore(root / "logbook.sqlite3")
                # Stage next to uploads so atomic media moves stay on the same filesystem.
                media = LocalMediaStore(root / "uploads", root / "uploads", lambda: logbook.read().document)
                stores = Storage(logbook, media)
            self._accounts[root] = stores
            if len(self._accounts) > 128:
                self._accounts.popitem(last=False)
            return stores
