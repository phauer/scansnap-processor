"""Shared settings for ScanSnap OCR processor."""

import os
import re
from pathlib import Path

# Version — bump when OCR logic changes to allow re-processing detection.
# Keep in sync with pyproject.toml (enforced by tests/test_config.py).
VERSION = "1.1.0"

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_DIR / "logs"


def _path_env(name: str, default: Path) -> Path:
    """Read a path from the environment (``~`` expanded), falling back to ``default``
    on a missing or empty value."""
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else default


def _int_env(name: str, default: int) -> int:
    """Read an int from the environment, falling back to ``default`` on a missing
    or non-numeric value (a typo shouldn't crash the import / the 24/7 watcher)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Paths
# Folder ScanSnap writes new scans into (watched by watcher.py, default for
# process_new.py). Override with SCANSNAP_FOLDER.
SCANSNAP_FOLDER = _path_env(
    "SCANSNAP_FOLDER", Path.home() / "Documents" / "ScanSnap Home folder"
)
# Root that the relative paths in scansnap-pdfs.md (re_ocr.py) are resolved
# against. Override with SCANSNAP_DOCS_DIR.
DOCS_DIR = _path_env("SCANSNAP_DOCS_DIR", Path.home() / "Documents")

# OCR settings
# Engine selection. One of: "easyocr", "apple_vision", "apple_livetext", "qwen3vl".
# Override at runtime with the SCANSNAP_OCR_ENGINE environment variable.
OCR_ENGINE = os.environ.get("SCANSNAP_OCR_ENGINE", "apple_vision")
OCR_LANGUAGES = ["de", "en"]
OCR_DPI = 300
DPI_SCALE = 72 / OCR_DPI  # Convert pixel coords to PDF points

# Filename patterns
NEW_SCAN_PATTERN = re.compile(r"^(\d{14})\.pdf$")

# Title generation
MAX_TITLE_WORDS = 6
FALLBACK_TITLE = "Scan"

# Title engine: "llm" (local LLM reads the OCR text — best quality, names files
# sender → type → subject) or "heuristic" (keyword matching, no model). The LLM path
# falls back to the heuristic automatically when the model is unavailable or fails.
# Override at runtime with SCANSNAP_TITLE_ENGINE.
TITLE_ENGINE = os.environ.get("SCANSNAP_TITLE_ENGINE", "llm")

# Local MLX LLM used when TITLE_ENGINE == "llm". Runs fully on-device (personal
# documents must stay local). Default is a 3B model (~2 GB, ~3s/doc) — a good fit
# for the 24/7 watcher on 16 GB. Override to a larger model for higher quality at
# the cost of speed and RAM, e.g. mlx-community/Qwen2.5-7B-Instruct-4bit.
TITLE_LLM_MODEL = os.environ.get(
    "SCANSNAP_TITLE_MODEL", "mlx-community/Qwen2.5-3B-Instruct-4bit"
)
# Max characters of OCR text (from the first pages) sent to the LLM.
TITLE_LLM_MAX_CHARS = _int_env("SCANSNAP_TITLE_MAX_CHARS", 2500)
# Max new tokens the LLM may emit for a title.
TITLE_LLM_MAX_TOKENS = 40

# Release the title model from RAM after each title (vs. keeping it resident).
# The 24/7 watcher sets SCANSNAP_TITLE_RELEASE=1 (see the LaunchAgent plist) so its
# ~1.7 GB is only held for the few seconds of naming, then freed — reloading costs
# ~0.9s on the next scan (files stay in the OS cache). CLI batch runs leave this off
# (default) so the model stays resident across many files in one run.
TITLE_LLM_RELEASE_AFTER_USE = os.environ.get("SCANSNAP_TITLE_RELEASE", "0") == "1"

# Words stripped from generated titles (case-insensitive, whole-word). Typical use:
# your own surname — it appears as the *recipient* on nearly every document and is
# noise in a title. Comma-separated via SCANSNAP_TITLE_DROP_WORDS, e.g.
# "Mustermann,Musterfrau". Empty by default.
TITLE_DROP_WORDS = [
    w.strip()
    for w in os.environ.get("SCANSNAP_TITLE_DROP_WORDS", "").split(",")
    if w.strip()
]

# Watcher
WATCHER_SETTLE_TIME = 3.0  # seconds to wait for file to stabilize
WATCHER_SIZE_CHECK_INTERVAL = 0.5  # seconds between size checks
