"""The single-page app shell, static assets, health, and CSRF token."""

from __future__ import annotations

from flask import Blueprint, Response, abort, current_app, jsonify, redirect, render_template, request, send_from_directory, session

from ..config import PROJECT_ROOT
from ..request_security import csrf_token
from . import read_document


blueprint = Blueprint("pages", __name__)

APP_ROUTES = (
    "/", "/trips", "/expeditions", "/bests", "/stats", "/leaderboard",
    "/map", "/gear", "/gallery", "/checklists", "/wiki", "/settings",
)
STATIC_SUFFIXES = {".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".woff", ".woff2", ".map"}
PUBLIC_STATIC_JSON_ASSETS = {"data/bathymetry/manifest.json"}


@blueprint.get("/healthz")
def healthcheck() -> Response:
    """Report process health without requiring the persisted logbook to be valid."""
    return jsonify({"ok": True})


@blueprint.get("/api/csrf-token")
def get_csrf_token() -> Response:
    return jsonify({"csrfToken": csrf_token()})


@blueprint.get("/favicon.ico")
def favicon() -> tuple[str, int]:
    return "", 204


def app_page() -> Response:
    if request.path == "/" and current_app.config["AUTH_REQUIRED"]:
        return redirect("/trips" if session.get("gitlab_user_id") else "/login")
    database_error = ""
    try:
        theme = read_document().get("settings", {}).get("theme")
    except Exception as error:
        # Keep the shell and archive recovery tools available. The browser
        # must still refuse to load or save an unavailable account logbook.
        database_error = str(error) or "The stored logbook database could not be opened."
        current_app.logger.error("Stored logbook could not be loaded; serving degraded app shell: %s", database_error)
        theme = None
    return Response(
        render_template(
            "index.html",
            initial_theme="dark" if theme == "dark" else "light",
            database_error=database_error,
            great_lakes_api_url=current_app.extensions["fish.config"].great_lakes_api_url,
            account_name=session.get("gitlab_name", ""),
            auth_required=current_app.config["AUTH_REQUIRED"],
        ),
        mimetype="text/html",
    )


for _route in APP_ROUTES:
    blueprint.add_url_rule(_route, "app_page", app_page, methods=["GET"])


@blueprint.get("/static/<path:filename>")
def static_files(filename: str) -> Response:
    if filename.startswith(".") or "/." in filename:
        abort(404)
    static_root = (PROJECT_ROOT / "static").resolve()
    requested = (static_root / filename).resolve()
    if (
        static_root not in requested.parents
        or (requested.suffix.lower() not in STATIC_SUFFIXES and filename not in PUBLIC_STATIC_JSON_ASSETS)
    ):
        abort(404)
    return send_from_directory(static_root, filename)
