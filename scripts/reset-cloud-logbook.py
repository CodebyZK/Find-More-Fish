#!/usr/bin/env python3
"""Back up and replace the shared cloud logbook with the blank schema-v2 default."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend import cloud_storage
from backend.backend_config import DEFAULT_LOGBOOK
from backend.logbook_store import validate_logbook


def _write_new_private_file(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def reset_cloud_logbook(backup_path: Path) -> None:
    if not cloud_storage.enabled():
        raise RuntimeError("Cloud storage is not enabled in this environment.")
    if not backup_path.is_absolute() or backup_path.name in {"", ".", ".."}:
        raise RuntimeError("The backup path must be an absolute filename on persistent storage.")
    if not backup_path.parent.is_dir():
        raise RuntimeError("The backup directory must already exist on persistent storage.")
    parent_mode = stat.S_IMODE(backup_path.parent.stat().st_mode)
    if parent_mode & 0o077:
        raise RuntimeError("The backup directory must be private (mode 0700).")

    raw, headers, _ = cloud_storage._request("GET", "/api/logbook")
    etag = headers.get("etag", "")
    if not etag:
        raise RuntimeError("The cloud logbook response has no ETag; refusing an unguarded reset.")
    try:
        current = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError("The cloud logbook response is not valid JSON; no changes were made.") from None
    if not isinstance(current, dict):
        raise RuntimeError("The cloud logbook is not a JSON object; no changes were made.")

    metadata_path = backup_path.with_name(backup_path.name + ".metadata.json")
    if backup_path.exists() or metadata_path.exists():
        raise RuntimeError("The backup path or its metadata file already exists; choose a new path.")

    metadata = json.dumps(
        {
            "savedAt": datetime.now(timezone.utc).isoformat(),
            "etag": etag,
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    _write_new_private_file(backup_path, raw)
    _write_new_private_file(metadata_path, metadata)

    blank = deepcopy(DEFAULT_LOGBOOK)
    valid, validation_error = validate_logbook(blank)
    if not valid:
        raise RuntimeError(f"The application's blank schema-v2 logbook is invalid: {validation_error}")
    body = json.dumps(blank, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    cloud_storage._request(
        "PUT",
        "/api/logbook",
        body=body,
        headers={"Content-Type": "application/json", "If-Match": etag},
    )

    persisted_raw, persisted_headers, _ = cloud_storage._request("GET", "/api/logbook")
    try:
        persisted = json.loads(persisted_raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError(f"Read-back verification failed; the private backup is at {backup_path}.") from None
    if persisted != blank or not persisted_headers.get("etag"):
        raise RuntimeError(f"Read-back verification failed; the private backup is at {backup_path}.")

    print("Cloud logbook reset and read-back verification succeeded.")
    print(f"Raw pre-reset logbook backup: {backup_path}")
    print(f"Private ETag metadata: {metadata_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="required confirmation to perform the reset")
    parser.add_argument("--backup", type=Path, required=True, help="new absolute path for raw pre-reset JSON")
    args = parser.parse_args()
    if not args.apply:
        parser.error("--apply is required; this command replaces the shared cloud logbook")
    try:
        reset_cloud_logbook(args.backup)
    except Exception as error:
        # Avoid showing response bodies, credentials, or logbook data in command output.
        print(f"Cloud logbook reset stopped ({type(error).__name__}); inspect the private backup if created.", file=sys.stderr)
        if isinstance(error, RuntimeError) and str(error).startswith("The backup path"):
            print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
