# Website integration

Keep Website-only features here. Shared application code comes from main.
The website composes the shared Flask factory and frontend instead of copying
its routes, data model, application UI, or persistence implementation.

| Concern | Website owner |
| --- | --- |
| App factory and entry point | app.py, server.py |
| Login and account storage | auth.py, storage.py |
| Login screen and account controls | templates/, static/css/ |
| Server-only startup, session redirects, browser cache policy | static/js/, frontend.config.mjs |
| Python, runtime, and browser tests | tests/ |
| Deployment jobs and container settings | ci.yml, docker-compose.yml |
| Explicit data maintenance tools | scripts/ |

## Run from the repository root

Use Python 3.13 with requirements-dev.txt installed, plus npm ci.
Configure the GitLab OAuth variables in your process environment; .env.example
lists them. The scripts do not automatically load a dotenv file.

    .\website\run.ps1

Or run node website/build.mjs followed by .venv\Scripts\python.exe -m website.server.
For gunicorn, use website.server:app. The shared server.py remains the desktop
entry point. Website accounts use FISH_DATA_DIR/users/gitlab-<id>/ and require
local storage. OAuth and private data remain outside Git.

Build the website using node website/build.mjs. A regular npm run build builds
the shared desktop client. The production website refuses to serve a desktop
bundle; it requires the website marker written by the website build configuration.
The website build uses esbuild's inject mechanism for request and browser-storage
adapters, plus a state-module adapter that re-exports shared state. It does not
replace browser globals or copy the shared application.

## Verification

    .\website\check.ps1

Pass -Python <path> to select an existing Python 3.13 environment. Browser tests
use temporary data and a fake OAuth provider defined only in tests/fixture_server.py.
The website tests live separately from the shared tests and run in dedicated CI jobs.
The check script runs both app modes and leaves the website frontend built.

## Container and CI

    docker compose -f docker-compose.yml -f website/docker-compose.yml build
    docker compose -f docker-compose.yml -f website/docker-compose.yml up -d

Set FISH_OAUTH_ENV_FILE to the private environment file in production. The root
pipeline includes ci.yml; all deployment rules remain restricted to Website.
Deployment jobs use the reserved .post stage after validation. Root shared jobs
retain main's definitions. Account data and OAuth files retain their existing paths.

## Pulling main

Fetch and merge origin/main normally. Keep new website behavior in this directory;
add generic hooks to shared files only when an existing integration point cannot
support it. Current shared integration points are the optional configure_app factory
callback, the topbar_extensions template block, FISH_FRONTEND_EXTENSION for esbuild,
Docker extension build arguments, and the root CI include.

These small interfaces reduce conflicts; upstream interface changes can still need
integration work. Shared-file correctness fixes should go to main as well. Inherited
Mobile schema freshness and the local Python environment remain separate setup checks.

Shared README.md and docs/ follow main to avoid repeated documentation conflicts.
Run python website/scripts/check-shared-boundary.py after merging to catch accidental
website edits in shared core files. The optional argument selects an upstream ref.
