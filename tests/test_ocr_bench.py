"""Unit tests for the benchmark's checkpoint loading (no OCR, no real documents)."""

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ocr_bench", _ROOT / "scripts" / "ocr_bench.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
load_checkpoints = _mod.load_checkpoints
checkpoints_for = _mod.checkpoints_for


class TestLoadCheckpoints:
    def test_missing_file_means_speed_only(self, tmp_path):
        assert load_checkpoints(tmp_path / "nope.json") == {}

    def test_loads_mapping(self, tmp_path):
        f = tmp_path / "cp.json"
        f.write_text(json.dumps({"Rechnung": ["RECHNUNG", "Ärztliche"]}), encoding="utf-8")
        assert load_checkpoints(f) == {"Rechnung": ["RECHNUNG", "Ärztliche"]}

    @pytest.mark.parametrize("payload", [["a", "b"], {"Rechnung": "RECHNUNG"}, {"x": [1, 2]}])
    def test_rejects_wrong_shape(self, tmp_path, payload):
        f = tmp_path / "cp.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            load_checkpoints(f)

    def test_example_file_is_valid(self):
        assert load_checkpoints(_ROOT / "bench-checkpoints.example.json")


class TestCheckpointsFor:
    CP = {"Bußgeldbescheid": ["Bußgeldbescheid"], "Umzug": ["Kostenübersicht"]}

    def test_matches_filename_substring_case_insensitive(self):
        assert checkpoints_for("2025 Stadt bußgeldbescheid.pdf", self.CP) == ["Bußgeldbescheid"]
        assert checkpoints_for("Angebot umzug.pdf", self.CP) == ["Kostenübersicht"]

    def test_no_match_returns_empty(self):
        assert checkpoints_for("random.pdf", self.CP) == []
        assert checkpoints_for("anything.pdf", {}) == []
