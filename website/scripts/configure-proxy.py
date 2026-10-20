"""Replace this website's legacy Nginx popup after verifying app authentication.

Run on the production host after the Website container is healthy. No logbook
data, OAuth credentials, TLS configuration, or other virtual hosts are changed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


DOMAIN = "fish.zionkoudijs.com"
SITE = Path("/etc/nginx/sites-enabled") / DOMAIN
AUTH = re.compile(r"(?m)^([ \t]*)auth_basic[ \t]+([^;\n]+);")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def response(origin: str, path: str) -> tuple[int, object, str]:
    headers = {"Host": DOMAIN}
    if origin == "http://127.0.0.1:80":
        # Match the HTTPS request metadata supplied by the existing edge proxy.
        headers["X-Forwarded-Proto"] = "https"
    request = Request(f"{origin}{path}", headers=headers)
    try:
        result = build_opener(NoRedirect).open(request, timeout=15)
    except HTTPError as error:
        result = error
    with result:
        return result.status, result.headers, result.read(65536).decode("utf-8", errors="replace")


def verify_auth(origin: str) -> None:
    status, headers, page = response(origin, "/login")
    if status != 200 or "Continue with GitLab" not in page or headers.get("WWW-Authenticate"):
        raise RuntimeError(f"{origin} does not serve the configured GitLab login (HTTP {status}, redirect {headers.get('Location', 'none')})")
    for path in ("/api/csrf-token", "/uploads/website-auth-check.jpg"):
        status, headers, _ = response(origin, path)
        if status != 401 or headers.get("WWW-Authenticate"):
            raise RuntimeError(f"{origin} does not enforce app authentication for {path} (HTTP {status})")
    status, headers, _ = response(origin, "/trips")
    if status != 302 or not headers.get("Location", "").startswith("/login"):
        raise RuntimeError(f"{origin} does not redirect signed-out visitors to login (HTTP {status})")


def admin_command(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode and os.geteuid() != 0:
        result = subprocess.run(["sudo", "-n", *command], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    print(result.stdout.strip() or result.stderr.strip() or f"{' '.join(command)} succeeded", flush=True)


def verify_proxy() -> None:
    for attempt in range(10):
        try:
            # Public probes from this host can receive an edge 403. Verify the
            # origin using the edge's HTTPS metadata; check the public UI in a
            # browser separately without changing any edge protections.
            verify_auth("http://127.0.0.1:80")
            return
        except Exception:
            if attempt == 9:
                raise
            time.sleep(1)


def main() -> None:
    # Do this before requesting privilege or changing the Nginx configuration.
    verify_auth("http://127.0.0.1:8081")
    status, headers, _ = response("http://127.0.0.1:80", "/login")
    print(f"Origin login with forwarded HTTPS: {status}; redirect: {headers.get('Location', 'none')}", flush=True)
    if status not in {200, 401}:
        raise RuntimeError("Cannot reach the origin login with the existing HTTPS proxy metadata")
    target = SITE.resolve(strict=True)
    original = target.read_text(encoding="utf-8")
    uncommented = re.sub(r"(?m)#.*$", "", original)
    names = re.findall(r"\bserver_name\s+([^;]+);", uncommented)
    if not names or any(set(names_line.split()) != {DOMAIN} for names_line in names):
        raise RuntimeError("Refusing to change a config that serves another domain")
    updated, count = AUTH.subn(lambda match: f"{match[1]}auth_basic off;", original)
    if not count:
        raise RuntimeError("Expected the site's explicit auth_basic directive")
    if updated == original:
        verify_proxy()
        print("Nginx already uses the Website GitLab login.", flush=True)
        return

    if not os.access(target, os.W_OK):
        if os.geteuid() == 0 or "--elevated" in sys.argv:
            raise RuntimeError("Cannot write the website Nginx configuration")
        print("Requesting existing noninteractive sudo permission for this site update.", flush=True)
        subprocess.run(["sudo", "-n", sys.executable, str(Path(__file__).resolve()), "--elevated"], check=True)
        return

    nginx = shutil.which("nginx") or "/usr/sbin/nginx"
    admin_command([nginx, "-t"])
    backup_dir = (Path("/var/backups/fish-logbook/nginx") if os.geteuid() == 0
                  else Path.home() / ".local/state/fish-logbook/nginx")
    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = backup_dir / f"{DOMAIN}.{stamp}.conf"
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(original)
    print(f"Saved Nginx backup: {backup}", flush=True)
    if target.read_text(encoding="utf-8") != original:
        raise RuntimeError("Nginx configuration changed during preparation; refusing to overwrite it")

    try:
        # Preserve the existing owner, mode and symlink target. Reload only after
        # nginx -t succeeds; the running workers keep their old config until then.
        target.write_text(updated, encoding="utf-8")
        admin_command([nginx, "-t"])
        admin_command(["systemctl", "reload", "nginx"])
        verify_proxy()
    except BaseException:
        target.write_text(original, encoding="utf-8")
        admin_command([nginx, "-t"])
        admin_command(["systemctl", "reload", "nginx"])
        print("Restored the previous Nginx configuration.", flush=True)
        raise
    print("Website login is public; private API, uploads and pages still require GitLab sign-in.", flush=True)


if __name__ == "__main__":
    main()
