"""Compose the website around the shared app's public integration points."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from flask import Blueprint, Flask, Response, g, has_request_context, request, session
from jinja2 import ChoiceLoader, FileSystemLoader, PrefixLoader
from werkzeug.local import LocalProxy
from backend.app_factory import create_app as create_shared_app
from backend.config import AppConfig, PROJECT_ROOT
from backend.storage import Storage
from .auth import configure_gitlab_auth
from .storage import AccountStorage, user_data_dir

ROOT = Path(__file__).resolve().parent
BUILD_MARKER = b"/* fishing-logbook-website */"

def website_frontend_ready() -> bool:
    try:
        with (PROJECT_ROOT / "static/dist/app.js").open("rb") as stream:
            return stream.read(len(BUILD_MARKER)) == BUILD_MARKER
    except OSError:
        return False


def create_app(config: AppConfig | None = None, *, auth_required: bool = True) -> Flask:
    config = config or AppConfig.from_env()
    if not auth_required:
        raise ValueError("Use backend.app_factory for shared tests; the website always requires authentication.")
    if config.storage_backend != "local":
        raise RuntimeError("GitLab account storage requires FISH_STORAGE_BACKEND=local; the cloud worker is not account scoped.")
    accounts = AccountStorage(config)
    stores = Storage(
        LocalProxy(lambda: accounts.current().logbook),
        LocalProxy(lambda: accounts.current().media),
    )

    def configure(app: Flask) -> None:
        app.config.update(AUTH_REQUIRED=True, AUTH_DATA_DIR=config.data_dir, SESSION_COOKIE_SAMESITE="Lax")
        app.extensions["website.config"] = config
        app.extensions["website.accounts"] = accounts
        configure_gitlab_auth(app)

        def scoped_config() -> AppConfig:
            if has_request_context() and getattr(g, "gitlab_user_id", None):
                return replace(config, data_dir=user_data_dir())
            return config

        # Existing routes use the same storage/config interfaces. Their account
        # selection is resolved per request, never assigned to a global user.
        app.extensions["fish.config"] = LocalProxy(scoped_config)
        app.jinja_loader = ChoiceLoader([
            FileSystemLoader(ROOT / "templates"),
            PrefixLoader({"shared": app.jinja_loader}),
            app.jinja_loader,
        ])
        app.register_blueprint(Blueprint("website", __name__, static_folder=str(ROOT / "static"), static_url_path="/website/static"))

        @app.context_processor
        def account_context() -> dict:
            return {"account_name": session.get("gitlab_name", "")}

        @app.before_request
        def require_website_bundle() -> tuple[str, int] | None:
            if not config.testing and (request.endpoint == "pages.app_page" or request.path == "/static/dist/app.js"):
                if not website_frontend_ready():
                    return "Website assets are missing or belong to the shared client. Run node website/build.mjs.", 503
            return None

        @app.after_request
        def private_media_cache(response: Response) -> Response:
            if request.path.startswith("/uploads/"):
                response.headers["Cache-Control"] = "no-store"
            return response

    return create_shared_app(config, storage=stores, configure_app=configure)
