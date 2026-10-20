# Website working agreement

Read README.md in this directory before changing website behavior. Website-specific
code, templates, styles, tools, tests, CI jobs, and container overrides belong here.
Shared source and documentation follow main. The shared app serves one operator;
the website wraps it with mandatory GitLab OAuth and private per-account storage.

Use node website/build.mjs and python -m website.server from the repository root.
The shared npm build and server.py deliberately retain desktop behavior. Production
must use the website Compose overlay and website.server:app. The website refuses
to serve a shared desktop bundle. Preserve server-only logbook loading, account
isolation for every data/media/archive operation, and the ban on browser document
caching. Keep OAuth environment files and live data outside Git. Never select the
shared Cloudflare storage backend for accounts.

Use website/check.ps1 for the combined checks; -Python can select a Python 3.13
interpreter. Website browser tests use their own temporary server and fake OAuth
provider. Keep provider stubs in tests. Preserve the existing production data paths,
GitLab project, and Website-only deployment rules. Do not deploy during local work.

Prefer the public shared app factory callback, storage interfaces, template block,
frontend build configuration, Docker build arguments, and CI include. Do not copy
shared route or UI implementations into this directory. When upstream changes one
of these interfaces, adapt the website integration and run both test suites.
