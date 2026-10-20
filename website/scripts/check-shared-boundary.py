"""Detect website-specific edits leaking back into shared source after a merge."""
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {
    "backend/app_factory.py", "templates/partials/layout/topbar.html",
    "scripts/build-frontend.mjs", "Dockerfile", ".gitlab-ci.yml", "AGENTS.md",
    "playwright.config.js",  # Shared CI port isolation and artifact configuration.
    # General clean-checkout / locale fixes inherited from the initial merge.
    "tests/leaderboard.test.js", "tests/great-lakes-animation.test.js",
    "tests/great-lakes-current-inspection.test.js",
}
SCOPES = ["backend", "static", "templates", "schema", "scripts", "tests", "docs",
          "server.py", "playwright.config.js", "docker-compose.yml", "Dockerfile", ".gitlab-ci.yml", "README.md", "AGENTS.md"]
def main() -> int:
    upstream = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    result = subprocess.run(["git", "diff", "--name-only", upstream, "--", *SCOPES],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    unexpected = sorted(set(result.stdout.splitlines()) - ALLOWED)
    if unexpected:
        print("Shared source differs outside the documented integration points:")
        print("\n".join(unexpected))
        return 1
    print(f"Shared source matches {upstream} outside the documented integration points.")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
