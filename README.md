# Fishing Logbook Website

Maintainers: Lucas Pijl and Zion Koudijs.
Current release: `1.0.0`.
Requirements: Python 3.13, Node.js 22+, and packages in `requirements-dev.txt`.
Run: `.\scripts\run-local.ps1`.

The `Website` branch integrates shared features from `main` and owns website deployment.
GitLab OAuth is required for normal runs. Configure `GITLAB_URL`, `GITLAB_CLIENT_ID`,
`GITLAB_CLIENT_SECRET`, and `GITLAB_REDIRECT_URI`; `GITLAB_ALLOWED_USER_IDS` optionally restricts access.
Each account keeps its database and uploads under `FISH_DATA_DIR/users/gitlab-<id>/`.
Account storage requires `FISH_STORAGE_BACKEND=local`; the shared Cloudflare worker is not account scoped.
Browser logbooks load from the authenticated server and are not cached in localStorage.

Production deployment remains restricted to `Website`, with OAuth configuration and persistent
runtime data outside Git. Build frontend assets with `npm ci` and `npm run build`.
Run `.\scripts\check.ps1` for verification; browser tests use disposable storage.
