"""Tests for install-watcher.sh plist generation (via --dry-run; never touches launchd)."""

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("plutil") is None, reason="macOS only (plutil)")


def _generate(repo: Path, extra_env: dict[str, str] | None = None) -> dict:
    """Copy the installer + template into ``repo`` and return the parsed dry-run plist."""
    repo.mkdir(parents=True, exist_ok=True)
    for name in ("install-watcher.sh", "launchagent.plist.template"):
        shutil.copy2(_ROOT / name, repo / name)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SCANSNAP_")}
    env.update(extra_env or {})
    out = subprocess.run(
        ["bash", str(repo / "install-watcher.sh"), "--dry-run"],
        env=env, capture_output=True, check=True,
    ).stdout
    return plistlib.loads(out)


class TestInstallWatcherDryRun:
    def test_fills_repo_path_and_label(self, tmp_path):
        repo = tmp_path / "repo"
        plist = _generate(repo)
        assert plist["Label"] == "local.scansnap-ocr"
        assert plist["ProgramArguments"] == [f"{repo}/.venv/bin/python", f"{repo}/watcher.py"]
        assert plist["WorkingDirectory"] == str(repo)
        assert plist["StandardErrorPath"] == f"{repo}/logs/watcher-stderr.log"
        assert plist["EnvironmentVariables"]["SCANSNAP_TITLE_RELEASE"] == "1"

    def test_no_placeholders_left(self, tmp_path):
        _generate(tmp_path / "repo")
        assert "__" not in (tmp_path / "repo" / "launchagent.plist").read_text()

    def test_special_chars_in_path_are_escaped(self, tmp_path):
        repo = tmp_path / "a b&c"
        plist = _generate(repo)
        assert plist["WorkingDirectory"] == str(repo)

    def test_bakes_in_scansnap_env_vars(self, tmp_path):
        plist = _generate(tmp_path / "repo", {
            "SCANSNAP_TITLE_DROP_WORDS": "Muster & <Sohn>",
            "SCANSNAP_FOLDER": "/Volumes/Scans",
        })
        env = plist["EnvironmentVariables"]
        assert env["SCANSNAP_TITLE_DROP_WORDS"] == "Muster & <Sohn>"
        assert env["SCANSNAP_FOLDER"] == "/Volumes/Scans"

    def test_template_release_flag_not_duplicated(self, tmp_path):
        _generate(tmp_path / "repo", {"SCANSNAP_TITLE_RELEASE": "0"})
        text = (tmp_path / "repo" / "launchagent.plist").read_text()
        assert text.count("SCANSNAP_TITLE_RELEASE") == 1
