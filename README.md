# Fishing Logbook Desktop

Fishing Logbook is a web app for trips, catches, gear, maps, and fishing statistics. This branch adds GitLab sign-in and a private logbook for each GitLab account.

## Configure GitLab sign-in

Create a GitLab OAuth application with the `read_user` scope. Register the exact callback URL for this deployment, such as `https://your-domain.example/auth/gitlab/callback`. Set `GITLAB_CLIENT_ID`, `GITLAB_CLIENT_SECRET`, and `GITLAB_REDIRECT_URI` on the server. `GITLAB_URL` defaults to `https://gitlab.com` and can point to a self-managed GitLab HTTPS origin. See [GitLab's OAuth application setup](https://docs.gitlab.com/integration/oauth_provider/) for the registration steps.

By default, any GitLab account can sign in and create its own private logbook. To limit access, set `GITLAB_ALLOWED_USER_IDS` to comma-separated numeric GitLab account IDs. The server checks this list on every authenticated request. Account IDs are used as stable storage keys; usernames and email addresses are not used for storage paths.

Set a persistent `SECRET_KEY` for direct Python deployments. Docker generates and saves one in `data/.secret_key` if it is not provided. Set `SESSION_COOKIE_SECURE=true` behind HTTPS. Local HTTP development can use `false`. GitLab permits an HTTP callback for development, but use HTTPS for a public deployment.

### Run locally

Requirements: Python 3.11+ and the packages in `requirements.txt`. On Windows, run `./scripts/run-local.ps1` after setting the GitLab environment variables. The app opens at `http://127.0.0.1:8080`. Register `http://127.0.0.1:8080/auth/gitlab/callback` as the OAuth redirect URI for this local setup.

### Docker Compose

Copy `.env.example` to `.env`, fill in the GitLab settings, and run `docker compose up --build -d`. The app listens on host port 80 by default; set `APP_PORT` to change it. The host data directory is `./data` by default; set `FISH_DATA_DIR` to another host directory if needed. The `.env` file and account data are ignored by Git.

## Data ownership and migration

Each account has its own SQLite database and uploads under `data/users/gitlab-<id>/`. The app checks sign-in before serving logbooks, archives, photos, uploads, or API routes. GitLab access tokens are only used during sign-in and are not stored.

The former single-user `data/logbook.sqlite3` and `data/uploads/` are left untouched. To assign those records to a GitLab account, stop the server and run:

```powershell
.\.venv\Scripts\python.exe scripts/assign-legacy-logbook.py --user-id 123456
```

Use that account's numeric GitLab ID. The command refuses to replace an existing account logbook and keeps the original data. Alternatively, export an archive before enabling sign-in and import it after signing into the intended account.

The account-scoped implementation uses local storage. `FISH_STORAGE_BACKEND=cloud` is rejected while authentication is enabled because the existing cloud worker has one shared logbook and media namespace.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts/build-standalone.py --check
```

`standalone.html` is generated from `templates/` for direct-file use. Do not edit it by hand.
