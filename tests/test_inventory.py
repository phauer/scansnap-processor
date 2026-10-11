"""Unit tests for the ScanSnap inventory state classifier."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "scansnap_inventory",
    Path(__file__).resolve().parent.parent / "scripts" / "scansnap_inventory.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
classify_state = _mod.classify_state


@pytest.mark.parametrize(
    "producer, expected",
    [
        ("", "never"),
        ("ScanSnap Manager", "never"),  # producer left by the scanner, not us
        ("scansnap-processor v1.0.0 (EasyOCR)", "easyocr"),
        ("scansnap-processor v1.1.0 (AppleVision)", "apple_vision"),
        ("scansnap-processor v1.1.0 (AppleLiveText)", "apple_livetext"),
        ("scansnap-processor v9.9 (SomethingElse)", "processed_other"),
    ],
)
def test_classify_state(producer, expected):
    assert classify_state("ScanSnap Home #iX1600 (W)", producer) == expected
