"""Disposable browser-test server. OAuth responses are stubbed only here."""
from dataclasses import replace
from backend.config import AppConfig
from website import auth
from website.app import create_app

def provider_response(url, *, form=None, token=""):
    if form is not None:
        return {"access_token": str(int(form["code"]))}
    user_id = int(token)
    return {"id": user_id, "username": f"user{user_id}", "name": f"User {user_id}"}

def main():
    config = replace(AppConfig.from_env(), testing=True)
    app = create_app(config)
    app.config.update(GITLAB_URL="https://gitlab.example", GITLAB_CLIENT_ID="test-client",
                      GITLAB_CLIENT_SECRET="test-only", GITLAB_REDIRECT_URI="http://127.0.0.1:4174/auth/gitlab/callback")
    auth._json_request = provider_response
    app.run(host=config.host, port=config.port, threaded=True)

if __name__ == "__main__":
    main()
