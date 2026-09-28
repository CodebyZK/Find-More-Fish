"""Safely inspect or migrate the configured cloud logbook to schema v2.

The default is a read-only dry run. Applying the migration requires a new,
absolute backup path. Cloud media objects are not modified.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend import cloud_storage
from backend.logbook_store import _COLLECTION_KEYS, validate_logbook
from scripts.migrate_logbook_v2 import MigrationError, audit_document, migrate_document


def _record_counts(document: dict) -> dict[str, int]:
    counts = {}
    for key in _COLLECTION_KEYS:
        value = document.get(key, [])
        if not isinstance(value, list):
            raise MigrationError(f"Cloud {key} collection is not a list; refusing a potentially lossy migration.")
        counts[key] = len(value)
    for index, trip in enumerate(document.get("trips", [])):
        if not isinstance(trip, dict):
            raise MigrationError(f"Cloud trip {index} is not an object.")
        for key in ("catches", "lostFish"):
            value = trip.get(key, [])
            if not isinstance(value, list):
                raise MigrationError(f"Cloud trip {index} {key} is not a list.")
            counts[key] = counts.get(key, 0) + len(value)
    return counts


def _save_backup(path: Path, document: dict, revision: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({
                "savedAt": datetime.now(timezone.utc).isoformat(),
                "revision": revision,
                "logbook": document,
            }, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def migrate_cloud(*, apply: bool, backup_path: Path | None = None) -> bool:
    if not cloud_storage.enabled():
        raise MigrationError("Set FISH_STORAGE_BACKEND=cloud and configure the cloud API URL/token first.")
    if apply and (backup_path is None or not backup_path.is_absolute()):
        raise MigrationError("--apply requires --backup with an absolute path on persistent storage.")

    before, revision = cloud_storage.get_logbook()
    if not isinstance(before, dict):
        raise MigrationError("Cloud logbook is not a JSON object.")
    version = before.get("schemaVersion")
    if version is not None and (type(version) is not int or version > 2 or version < 0):
        raise MigrationError(f"Unsupported cloud schemaVersion {version!r}; refusing to overwrite it.")
    before_counts = _record_counts(before)
    after = migrate_document(before)
    valid, error = validate_logbook(after)
    if not valid:
        raise MigrationError(f"Migrated logbook is invalid: {error}")
    remaining = audit_document(after)
    if remaining:
        raise MigrationError(f"Legacy fields remain after migration: {dict(remaining)}")
    after_counts = _record_counts(after)
    if after_counts != before_counts:
        raise MigrationError(f"Record counts changed: {before_counts} before, {after_counts} after.")

    print(f"Cloud revision: {revision or '(missing)'}")
    print(f"Schema: {before.get('schemaVersion')} -> {after['schemaVersion']}")
    print(f"Trips: {after_counts['trips']}; catch/lost records: {after_counts.get('catches', 0) + after_counts.get('lostFish', 0)}")
    print(f"Legacy fields: {dict(audit_document(before))}")
    if before == after:
        print("Cloud logbook is already canonical v2. No write needed.")
        return False
    if not apply:
        print("Dry run only. Re-run with --apply and an absolute --backup path to write v2.")
        return False
    if not revision:
        raise MigrationError("Cloud response has no ETag; refusing an unguarded write.")

    assert backup_path is not None
    _save_backup(backup_path, before, revision)
    print(f"Original cloud logbook saved to {backup_path}")
    new_revision = cloud_storage.put_logbook(after, revision)
    persisted, verified_revision = cloud_storage.get_logbook()
    if persisted != after:
        raise MigrationError(f"Cloud verification failed; inspect the backup at {backup_path} before retrying.")
    print(f"Migration complete. New revision: {verified_revision or new_revision}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist the validated conversion")
    parser.add_argument("--backup", type=Path, help="Absolute path for a new backup JSON file")
    args = parser.parse_args()
    try:
        migrate_cloud(apply=args.apply, backup_path=args.backup)
    except (MigrationError, cloud_storage.CloudStorageError, OSError, ValueError) as error:
        print(f"Cloud migration stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
