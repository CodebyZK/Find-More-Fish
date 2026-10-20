"""Website entry point: python -m website.server or gunicorn website.server:app."""
from backend.config import AppConfig
from .app import create_app, website_frontend_ready
config = AppConfig.from_env()
app = create_app(config)

def main() -> None:
    if not website_frontend_ready():
        raise SystemExit("Build the website frontend first: node website/build.mjs")
    print(f"Fishing Logbook Website running at http://{config.host}:{config.port}")
    print(f"Account data root: {config.data_dir}")
    app.run(host=config.host, port=config.port, threaded=True)

if __name__ == "__main__":
    main()
