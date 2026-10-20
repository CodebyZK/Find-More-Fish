"""Run OAuth deployment preparation with dummy credentials and no network access."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import pytest

ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which("sh")
pytestmark = pytest.mark.skipif(SHELL is None, reason="POSIX shell required")


def prepare(tmp_path, **overrides):
    ci = (ROOT / "website/ci.yml").read_text(encoding="utf-8")
    deploy = ci.split("deploy_production:", 1)[1].split("deploy_cloudflare_worker:", 1)[0]
    script = textwrap.dedent(deploy.split("  script:\n    - |\n", 1)[1])
    preparation = script.split("scp -o BatchMode=yes", 1)[0]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GITLAB_")}
    output = tmp_path / "prepared.env"
    environment.update({
        "CI_SERVER_URL": "https://git.zionkoudijs.com",
        "DEPLOY_HOST": "test.invalid", "DEPLOY_USER": "test-deploy",
        "DEPLOY_PATH": str(tmp_path), "DEPLOY_DATA_PATH": str(tmp_path / "data"),
        "GITLAB_CLIENT_ID": "dummy-client-id", "GITLAB_CLIENT_SECRET": "dummy-client-secret",
        "TEST_PYTHON": Path(sys.executable).as_posix(), "PREPARED_ENV": str(output),
        "TMPDIR": str(tmp_path),
    })
    for key, value in overrides.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    script = 'set -eu\npython3() { "$TEST_PYTHON" "$@"; }\n' + preparation + 'cp "$oauth_env" "$PREPARED_ENV"\n'
    result = subprocess.run([SHELL, "-s"], input=script, cwd=tmp_path, env=environment,
                            capture_output=True, text=True)
    return result, output


def test_public_oauth_urls_default_from_ci_and_production_site(tmp_path):
    result, output = prepare(tmp_path)
    assert result.returncode == 0, result.stderr
    values = output.read_text(encoding="utf-8")
    assert "GITLAB_URL='https://git.zionkoudijs.com'" in values
    assert "GITLAB_REDIRECT_URI='https://fish.zionkoudijs.com/auth/gitlab/callback'" in values
    assert "dummy-client-secret" not in result.stdout + result.stderr


def test_explicit_oauth_urls_are_preserved(tmp_path):
    result, output = prepare(tmp_path, GITLAB_URL="https://other-gitlab.example",
                             GITLAB_REDIRECT_URI="https://other-fish.example/auth/gitlab/callback")
    assert result.returncode == 0, result.stderr
    values = output.read_text(encoding="utf-8")
    assert "GITLAB_URL='https://other-gitlab.example'" in values
    assert "GITLAB_REDIRECT_URI='https://other-fish.example/auth/gitlab/callback'" in values


def test_missing_credentials_are_reported_together_without_publishing_config(tmp_path):
    result, output = prepare(tmp_path, GITLAB_CLIENT_ID=None, GITLAB_CLIENT_SECRET=None)
    assert result.returncode != 0
    assert "GITLAB_CLIENT_ID, GITLAB_CLIENT_SECRET" in result.stderr
    assert "production scope" in result.stderr
    assert not output.exists()


def test_missing_secret_still_prevents_deployment(tmp_path):
    result, output = prepare(tmp_path, GITLAB_CLIENT_SECRET=None)
    assert result.returncode != 0
    assert "Missing production OAuth variables: GITLAB_CLIENT_SECRET." in result.stderr
    assert not output.exists()


def test_control_characters_cannot_inject_environment_settings(tmp_path):
    result, output = prepare(tmp_path, GITLAB_CLIENT_SECRET="dummy-secret\nUNEXPECTED=1")
    assert result.returncode != 0
    assert "GITLAB_CLIENT_SECRET contains unsupported control characters" in result.stderr
    assert "dummy-secret" not in result.stdout + result.stderr
    assert not output.exists()
