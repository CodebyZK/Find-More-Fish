"""Exercise the CI remote shell without contacting production or running Docker."""

import os
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which("sh")
pytestmark = pytest.mark.skipif(SHELL is None, reason="POSIX shell required")


@pytest.mark.parametrize(
    ("build_status", "startup_status", "diagnostic_status"),
    [(0, 0, 0), (0, 17, 0), (0, 17, 23), (9, 0, 0)],
)
def test_remote_deploy_preserves_failure_and_reports_diagnostics(
    tmp_path, build_status, startup_status, diagnostic_status
):
    (tmp_path / ".oauth.env.tested-commit").write_text("GITLAB_CLIENT_ID='test'\n")
    ci = (ROOT / "website/ci.yml").read_text()
    remote = textwrap.dedent(ci.split("<<'REMOTE_SCRIPT'\n", 1)[1].split("      REMOTE_SCRIPT", 1)[0])
    # Function stubs log the commands and simulate failures, including diagnostics
    # failing after startup has already failed. mkdir operates only in tmp_path.
    stubs = r'''
git() { printf 'git %s\n' "$*"; }
    docker() {
      printf 'docker %s\n' "$*" >&2
      if [ "$1" = compose ]; then shift 5; set -- compose "$@"; fi
      case "$*" in
        'compose build') return "$BUILD_STATUS" ;;
        'compose up '*)
          test "$APP_PORT" = 8081 && test "$FISH_DATA_DIR" = runtime-data \
            && test "$FISH_STORAGE_BACKEND" = local \
            && test "$FISH_OAUTH_ENV_FILE" = ./.oauth.env || return 99
          return "$STARTUP_STATUS" ;;
    'compose ps --all --quiet') printf 'test-container\n'; return 0 ;;
    'compose logs '*|'inspect '*) return "$DIAGNOSTIC_STATUS" ;;
  esac
}
'''
    result = subprocess.run(
        [SHELL, "-s", "--", ".", "runtime-data", "tested-commit"],
        input=stubs + remote,
        cwd=tmp_path,
        env={**os.environ, "BUILD_STATUS": str(build_status),
             "STARTUP_STATUS": str(startup_status), "DIAGNOSTIC_STATUS": str(diagnostic_status)},
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == (build_status or startup_status), output
    assert "git reset --hard tested-commit" in output
    assert (tmp_path / ".oauth.env").is_file()
    assert not (tmp_path / ".oauth.env.tested-commit").exists()
    if build_status:
        assert "docker compose -f docker-compose.yml -f website/docker-compose.yml up" not in output
    elif startup_status:
        assert "docker compose -f docker-compose.yml -f website/docker-compose.yml logs --no-color --tail 200" in output
        assert "docker inspect --format {{json .State}} test-container" in output
    else:
        assert "docker compose -f docker-compose.yml -f website/docker-compose.yml ps" in output
        assert "docker compose -f docker-compose.yml -f website/docker-compose.yml logs" not in output
