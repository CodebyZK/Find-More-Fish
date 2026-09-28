from __future__ import annotations

import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile

from PIL import Image

from backend.backend_config import DEFAULT_LOGBOOK
from server import create_app


class GitLabAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-only-gitlab-session-key",
            "AUTH_REQUIRED": True,
            "AUTH_DATA_DIR": Path(self.directory.name),
            "GITLAB_CLIENT_ID": "client-id",
            "GITLAB_CLIENT_SECRET": "client-secret",
            "GITLAB_REDIRECT_URI": "http://localhost/auth/gitlab/callback",
        })

    def sign_in(self, client, user_id: int):
        start = client.get("/auth/gitlab?next=/trips")
        self.assertEqual(302, start.status_code)
        query = parse_qs(urlparse(start.headers["Location"]).query)
        self.assertEqual(["read_user"], query["scope"])
        self.assertEqual(["S256"], query["code_challenge_method"])

        def response(url, **kwargs):
            if url.endswith("/oauth/token"):
                self.assertTrue(kwargs["form"]["code_verifier"])
                return {"access_token": f"token-{user_id}"}
            self.assertEqual(f"Bearer token-{user_id}", f"Bearer {kwargs['token']}")
            return {"id": user_id, "username": f"user{user_id}", "name": f"User {user_id}"}

        with patch("backend.gitlab_auth._json_request", side_effect=response):
            finish = client.get(f"/auth/gitlab/callback?state={query['state'][0]}&code=valid")
        self.assertEqual(302, finish.status_code)
        self.assertEqual("/trips", finish.headers["Location"])

    def test_private_routes_require_login_and_bad_state_is_rejected(self):
        client = self.app.test_client()
        self.assertEqual(302, client.get("/trips").status_code)
        self.assertEqual(401, client.get("/api/logbook").status_code)
        self.assertEqual(401, client.get("/uploads/trip-photos/private.jpg").status_code)
        self.assertEqual(200, client.get("/login").status_code)
        client.get("/auth/gitlab")
        self.assertEqual(302, client.get("/auth/gitlab/callback?state=wrong&code=valid").status_code)
        self.assertEqual(401, client.get("/api/logbook").status_code)

    def test_logbooks_and_media_are_isolated_by_gitlab_id(self):
        alice = self.app.test_client()
        bob = self.app.test_client()
        self.sign_in(alice, 101)
        self.sign_in(bob, 202)
        payload = deepcopy(DEFAULT_LOGBOOK)
        payload["trips"] = [{"id": "alice-trip", "title": "Alice's trip", "date": "2026-09-28", "catches": []}]
        csrf = alice.get("/api/csrf-token").get_json()["csrfToken"]
        saved = alice.put("/api/logbook", json=payload, headers={"X-CSRF-Token": csrf})
        self.assertEqual(200, saved.status_code)
        self.assertEqual("alice-trip", alice.get("/api/logbook").get_json()["trips"][0]["id"])
        self.assertEqual([], bob.get("/api/logbook").get_json()["trips"])

        photo = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(photo, "JPEG")
        photo.seek(0)
        uploaded = alice.post("/api/uploads/trip-photos", data={"file": (photo, "fish.jpg")},
                              headers={"X-CSRF-Token": csrf}, content_type="multipart/form-data")
        self.assertEqual(200, uploaded.status_code)
        filename = uploaded.get_json()["filename"]
        self.assertEqual(200, alice.get(f"/uploads/trip-photos/{filename}").status_code)
        self.assertEqual(404, bob.get(f"/uploads/trip-photos/{filename}").status_code)
        self.assertEqual([], bob.get("/api/gallery").get_json()["media"])
        self.assertEqual(404, bob.get("/api/archive").status_code)
        with ZipFile(io.BytesIO(alice.get("/api/archive").data)) as archive:
            self.assertIn(f"media/trip-photos/{filename}", archive.namelist())
        self.assertTrue((Path(self.directory.name) / "users" / "gitlab-101" / "logbook.sqlite3").is_file())
        self.assertFalse((Path(self.directory.name) / "users" / "gitlab-202" / "logbook.sqlite3").exists())

        logout = alice.post("/logout", headers={"X-CSRF-Token": csrf})
        self.assertEqual(302, logout.status_code)
        self.assertEqual(401, alice.get("/api/logbook").status_code)

    def test_allowlist_rejects_unlisted_account(self):
        self.app.config["GITLAB_ALLOWED_USER_IDS"] = "101"
        client = self.app.test_client()
        self.sign_in_rejected(client, 202)

    def test_allowlist_change_revokes_existing_session(self):
        client = self.app.test_client()
        self.sign_in(client, 101)
        self.app.config["GITLAB_ALLOWED_USER_IDS"] = "202"
        self.assertEqual(401, client.get("/api/logbook").status_code)

    def sign_in_rejected(self, client, user_id):
        start = client.get("/auth/gitlab")
        state = parse_qs(urlparse(start.headers["Location"]).query)["state"][0]
        with patch("backend.gitlab_auth._json_request", side_effect=[
            {"access_token": "token"}, {"id": user_id, "username": "other"},
        ]):
            finish = client.get(f"/auth/gitlab/callback?state={state}&code=valid")
        self.assertEqual(302, finish.status_code)
        self.assertEqual(401, client.get("/api/logbook").status_code)


class LegacyAssignmentTests(unittest.TestCase):
    def test_copy_keeps_source_and_refuses_to_replace_account(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(sqlite3.connect(root / "logbook.sqlite3")) as database:
                with database:
                    database.execute("CREATE TABLE sample (value TEXT)")
                    database.execute("INSERT INTO sample VALUES ('legacy')")
            uploads = root / "uploads" / "trip-photos"
            uploads.mkdir(parents=True)
            (uploads / "fish.jpg").write_bytes(b"photo")
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "assign-legacy-logbook.py"),
                       "--user-id", "101", "--data-dir", directory]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, first.returncode, first.stderr)
            target = root / "users" / "gitlab-101"
            with closing(sqlite3.connect(target / "logbook.sqlite3")) as database:
                self.assertEqual("legacy", database.execute("SELECT value FROM sample").fetchone()[0])
            self.assertEqual(b"photo", (target / "uploads" / "trip-photos" / "fish.jpg").read_bytes())
            self.assertTrue((root / "logbook.sqlite3").exists())
            self.assertNotEqual(0, subprocess.run(command, capture_output=True).returncode)


if __name__ == "__main__":
    unittest.main()
