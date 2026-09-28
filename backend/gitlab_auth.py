"""GitLab OAuth sign-in and request authentication."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from flask import Flask, Response, current_app, g, jsonify, redirect, render_template, request, session, url_for


PUBLIC_PATHS = {"/", "/login", "/auth/gitlab", "/auth/gitlab/callback", "/healthz", "/favicon.ico"}


def _gitlab_url() -> str:
    value = str(current_app.config["GITLAB_URL"]).rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.path not in {"", "/"}:
        raise ValueError("GITLAB_URL must be an HTTPS origin")
    return value


def _next_path(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/trips"
    return value


def _oauth_configured() -> bool:
    return all(current_app.config.get(key) for key in ("GITLAB_CLIENT_ID", "GITLAB_CLIENT_SECRET", "GITLAB_REDIRECT_URI"))


def _allowed_user_ids() -> set[str]:
    return {part.strip() for part in str(current_app.config["GITLAB_ALLOWED_USER_IDS"]).split(",") if part.strip()}


def _json_request(url: str, *, form: dict | None = None, token: str = "") -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urlencode(form).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, data=data, headers=headers), timeout=10) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("GitLab returned an invalid response")
    return payload


def configure_gitlab_auth(app: Flask) -> None:
    app.config.setdefault("AUTH_REQUIRED", not app.config.get("TESTING", False))
    app.config.setdefault("AUTH_DATA_DIR", os.environ.get("FISH_DATA_DIR", "") or None)
    if app.config["AUTH_DATA_DIR"] is None:
        from .backend_config import DATA_DIR
        app.config["AUTH_DATA_DIR"] = DATA_DIR
    app.config.setdefault("GITLAB_URL", os.environ.get("GITLAB_URL", "https://gitlab.com"))
    app.config.setdefault("GITLAB_CLIENT_ID", os.environ.get("GITLAB_CLIENT_ID", ""))
    app.config.setdefault("GITLAB_CLIENT_SECRET", os.environ.get("GITLAB_CLIENT_SECRET", ""))
    app.config.setdefault("GITLAB_REDIRECT_URI", os.environ.get("GITLAB_REDIRECT_URI", ""))
    app.config.setdefault("GITLAB_ALLOWED_USER_IDS", os.environ.get("GITLAB_ALLOWED_USER_IDS", ""))
    app.permanent_session_lifetime = timedelta(hours=12)

    @app.before_request
    def require_login() -> Response | tuple[Response, int] | None:
        if not app.config["AUTH_REQUIRED"]:
            return None
        if request.path in PUBLIC_PATHS or request.path.startswith("/static/"):
            return None
        user_id = session.get("gitlab_user_id")
        if isinstance(user_id, int) and user_id > 0:
            allowed = _allowed_user_ids()
            if not allowed or str(user_id) in allowed:
                g.gitlab_user_id = user_id
                return None
            session.clear()
        if request.path.startswith("/api/") or request.path.startswith("/uploads/"):
            return jsonify({"error": "Sign in to access your logbook."}), 401
        return redirect(url_for("login", next=_next_path(request.full_path.rstrip("?"))))

    @app.get("/login")
    def login() -> Response:
        if not app.config["AUTH_REQUIRED"]:
            return redirect("/trips")
        if isinstance(session.get("gitlab_user_id"), int):
            return redirect(_next_path(request.args.get("next")))
        return Response(render_template("login.html", configured=_oauth_configured(), error=request.args.get("error", ""), next_path=_next_path(request.args.get("next"))), mimetype="text/html")

    @app.get("/auth/gitlab")
    def gitlab_login() -> Response:
        if not _oauth_configured():
            return redirect(url_for("login", error="GitLab sign-in is not configured yet."))
        try:
            base_url = _gitlab_url()
        except ValueError:
            return redirect(url_for("login", error="GitLab sign-in configuration is invalid."))
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        session["oauth_state"] = state
        session["oauth_verifier"] = verifier
        session["oauth_next"] = _next_path(request.args.get("next"))
        query = urlencode({
            "client_id": app.config["GITLAB_CLIENT_ID"],
            "redirect_uri": app.config["GITLAB_REDIRECT_URI"],
            "response_type": "code",
            "scope": "read_user",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return redirect(f"{base_url}/oauth/authorize?{query}")

    @app.get("/auth/gitlab/callback")
    def gitlab_callback() -> Response:
        expected = session.pop("oauth_state", "")
        verifier = session.pop("oauth_verifier", "")
        next_path = session.pop("oauth_next", "/trips")
        supplied = request.args.get("state", "")
        code = request.args.get("code", "")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied) or not verifier or not code:
            return redirect(url_for("login", error="Sign-in could not be verified. Please try again."))
        try:
            base_url = _gitlab_url()
            token = _json_request(f"{base_url}/oauth/token", form={
                "client_id": app.config["GITLAB_CLIENT_ID"],
                "client_secret": app.config["GITLAB_CLIENT_SECRET"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": app.config["GITLAB_REDIRECT_URI"],
                "code_verifier": verifier,
            })
            access_token = token.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise ValueError("GitLab did not return an access token")
            profile = _json_request(f"{base_url}/api/v4/user", token=access_token)
            user_id = profile.get("id")
            if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
                raise ValueError("GitLab did not return a valid account ID")
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError):
            current_app.logger.exception("GitLab sign-in failed")
            return redirect(url_for("login", error="GitLab sign-in failed. Please try again."))

        allowed = _allowed_user_ids()
        if allowed and str(user_id) not in allowed:
            return redirect(url_for("login", error="This GitLab account does not have access."))
        session.clear()
        session.permanent = True
        session["gitlab_user_id"] = user_id
        session["gitlab_username"] = str(profile.get("username") or "")[:100]
        session["gitlab_name"] = str(profile.get("name") or profile.get("username") or "GitLab user")[:100]
        return redirect(_next_path(next_path))

    @app.post("/logout")
    def logout() -> Response:
        session.clear()
        return redirect(url_for("login"))
