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
Both Playwright configurations pin their child-server PORT to their base URL, even
when CI exports PORT=8080. CI captures failure artifacts under test-results/ inside
the checkout so GitLab can upload screenshots, traces, and reports.
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

## Production OAuth settings

The deployment uses CI_SERVER_URL as the default GitLab provider and
https://fish.zionkoudijs.com/auth/gitlab/callback as the default callback.
GITLAB_URL and GITLAB_REDIRECT_URI can override these public URLs.

Register an OAuth application on that GitLab instance with the exact callback and
read_user scope. In the desktop project's Settings > CI/CD > Variables, configure:

| Variable | Value | Visibility |
| --- | --- | --- |
| GITLAB_CLIENT_ID | Application ID from the registered OAuth application | Masked |
| GITLAB_CLIENT_SECRET | Application secret from that same application | Masked and hidden |
| GITLAB_ALLOWED_USER_IDS | Optional comma-separated account IDs | Optional |

Use production environment scope. If variables are protected, Website must be a
protected branch. The deploy job reports all missing OAuth variables before
contacting the production host. It writes credentials only to the private OAuth
environment file. Keep client secrets out of repository files and chat messages.

## Public login and Nginx

The Website Compose overlay binds port 8081 to localhost. Nginx remains the public
proxy; HTTPS continues to be provided by the existing Cloudflare/proxy setup.
After the container becomes healthy, deployment runs scripts/configure-proxy.py
on the host. It verifies the configured GitLab login and signed-out protections
before disabling Basic Auth in /etc/nginx/sites-enabled/fish.zionkoudijs.com.
The script refuses a site config serving any other domain. It saves a private
backup outside the checkout, validates Nginx before reloading, and restores the
previous config if the reload or authentication checks fail. The deployment
account needs write permission for that site (or existing noninteractive sudo
permission), plus permission to validate and reload Nginx. No credentials or
logbook data are read by this operation.

The optional website_proxy_inspection CI job checks the local upstream and lists
routing/authentication directives using the existing deployment connection.
