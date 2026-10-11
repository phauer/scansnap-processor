"""Tests for config helpers."""

import importlib
from pathlib import Path

from scansnap_ocr.config import _int_env, _path_env


class TestIntEnv:
    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("SCANSNAP_TEST_INT", raising=False)
        assert _int_env("SCANSNAP_TEST_INT", 2500) == 2500

    def test_parses_valid_int(self, monkeypatch):
        monkeypatch.setenv("SCANSNAP_TEST_INT", "1000")
        assert _int_env("SCANSNAP_TEST_INT", 2500) == 1000

    def test_falls_back_on_non_numeric(self, monkeypatch):
        """A typo in the env var must not crash the import / the watcher."""
        monkeypatch.setenv("SCANSNAP_TEST_INT", "not-a-number")
        assert _int_env("SCANSNAP_TEST_INT", 2500) == 2500

    def test_falls_back_on_empty(self, monkeypatch):
        monkeypatch.setenv("SCANSNAP_TEST_INT", "")
        assert _int_env("SCANSNAP_TEST_INT", 2500) == 2500


class TestPathEnv:
    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("SCANSNAP_TEST_PATH", raising=False)
        assert _path_env("SCANSNAP_TEST_PATH", Path("/default")) == Path("/default")

    def test_returns_default_when_empty(self, monkeypatch):
        monkeypatch.setenv("SCANSNAP_TEST_PATH", "  ")
        assert _path_env("SCANSNAP_TEST_PATH", Path("/default")) == Path("/default")

    def test_expands_home(self, monkeypatch):
        monkeypatch.setenv("SCANSNAP_TEST_PATH", "~/Scans")
        assert _path_env("SCANSNAP_TEST_PATH", Path("/default")) == Path.home() / "Scans"


class TestConfigDefaults:
    """Module-level settings read the environment at import time → reload per test."""

    def _reload(self):
        import scansnap_ocr.config as config
        return importlib.reload(config)

    def teardown_method(self):
        self._reload()  # restore defaults for other tests

    def test_folders_default_to_home_documents(self, monkeypatch):
        monkeypatch.delenv("SCANSNAP_FOLDER", raising=False)
        monkeypatch.delenv("SCANSNAP_DOCS_DIR", raising=False)
        config = self._reload()
        assert config.SCANSNAP_FOLDER == Path.home() / "Documents" / "ScanSnap Home folder"
        assert config.DOCS_DIR == Path.home() / "Documents"

    def test_folders_overridable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SCANSNAP_FOLDER", str(tmp_path / "scans"))
        monkeypatch.setenv("SCANSNAP_DOCS_DIR", str(tmp_path))
        config = self._reload()
        assert config.SCANSNAP_FOLDER == tmp_path / "scans"
        assert config.DOCS_DIR == tmp_path

    def test_drop_words_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("SCANSNAP_TITLE_DROP_WORDS", raising=False)
        assert self._reload().TITLE_DROP_WORDS == []

    def test_drop_words_from_env(self, monkeypatch):
        monkeypatch.setenv("SCANSNAP_TITLE_DROP_WORDS", " Mustermann, ,Musterfrau ")
        assert self._reload().TITLE_DROP_WORDS == ["Mustermann", "Musterfrau"]


def test_version_matches_pyproject():
    """VERSION (written into processed PDFs) and pyproject.toml must not drift apart."""
    import tomllib

    from scansnap_ocr.config import VERSION

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    assert tomllib.loads(pyproject.read_text())["project"]["version"] == VERSION
