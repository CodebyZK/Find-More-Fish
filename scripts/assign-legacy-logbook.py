"""Copy the former single-user logbook into one GitLab account's private storage.

The source is retained. Run with the server stopped so uploads cannot change
while they are copied; SQLite itself is copied with its online backup API.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy a legacy logbook to a GitLab account.")
    parser.add_argument("--user-id", type=int, required=True, help="Numeric GitLab account ID")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    if args.user_id <= 0:
        parser.error("--user-id must be positive")

    source_root = args.data_dir.resolve()
    source_db = source_root / "logbook.sqlite3"
    destination = source_root / "users" / f"gitlab-{args.user_id}"
    if not source_db.is_file():
        parser.error(f"No legacy database found at {source_db}")
    if destination.exists():
        parser.error(f"Destination already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="legacy-logbook-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "account"
        staged.mkdir()
        with closing(sqlite3.connect(source_db, timeout=10)) as source:
            with closing(sqlite3.connect(staged / "logbook.sqlite3", timeout=10)) as target:
                source.backup(target)
        uploads = source_root / "uploads"
        if uploads.is_dir():
            shutil.copytree(uploads, staged / "uploads")
        staged.replace(destination)
    print(f"Copied legacy logbook and uploads to {destination}")
    print("The original data remains in place.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
