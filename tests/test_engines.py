"""Unit tests for OCR engine helpers (pure functions, no models loaded)."""

import pytest

from scansnap_ocr.engines import get_engine
from scansnap_ocr.engines.apple_vision_engine import vision_bbox_to_polygon
from scansnap_ocr.engines.qwen_vlm_engine import parse_grounded_output


class TestVisionBboxConversion:
    """Apple Vision returns normalized (0-1), bottom-left-origin boxes.
    The adapter must produce a top-left-origin pixel polygon."""

    def test_full_image_box(self):
        # Whole image → whole pixel rect.
        poly = vision_bbox_to_polygon((0.0, 0.0, 1.0, 1.0), 100, 200)
        assert poly == [[0, 0], [100, 0], [100, 200], [0, 200]]

    def test_top_left_quadrant(self):
        # Vision y is the bottom edge; a box at the visual top has high y.
        # x=0, y=0.5, w=0.5, h=0.5 → top-left quadrant in pixel space.
        poly = vision_bbox_to_polygon((0.0, 0.5, 0.5, 0.5), 100, 200)
        assert poly == [[0.0, 0.0], [50.0, 0.0], [50.0, 100.0], [0.0, 100.0]]

    def test_bottom_right_quadrant(self):
        # x=0.5, y=0.0, w=0.5, h=0.5 → bottom-right quadrant in pixel space.
        poly = vision_bbox_to_polygon((0.5, 0.0, 0.5, 0.5), 100, 200)
        assert poly == [[50.0, 100.0], [100.0, 100.0], [100.0, 200.0], [50.0, 200.0]]

    def test_polygon_is_four_points(self):
        poly = vision_bbox_to_polygon((0.1, 0.2, 0.3, 0.4), 1000, 1400)
        assert len(poly) == 4
        assert all(len(pt) == 2 for pt in poly)


class TestQwenGroundingParser:
    def test_parses_clean_json(self):
        raw = '[{"text": "Rechnung", "bbox": [10, 20, 110, 50]}]'
        results = parse_grounded_output(raw, 1000, 1400)
        assert len(results) == 1
        bbox, text, conf = results[0]
        assert text == "Rechnung"
        assert conf == 1.0
        assert bbox == [[10, 20], [110, 20], [110, 50], [10, 50]]

    def test_tolerates_prose_and_fences(self):
        raw = 'Here is the JSON:\n```json\n[{"text": "Köln", "bbox": [0, 0, 50, 20]}]\n```'
        results = parse_grounded_output(raw, 500, 500)
        assert [r[1] for r in results] == ["Köln"]

    def test_clamps_out_of_range_coords(self):
        raw = '[{"text": "x", "bbox": [-10, -5, 9999, 9999]}]'
        (bbox, _t, _c) = parse_grounded_output(raw, 100, 200)[0]
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        assert min(xs) >= 0 and max(xs) <= 100
        assert min(ys) >= 0 and max(ys) <= 200

    def test_skips_invalid_entries(self):
        raw = '[{"text": "", "bbox": [0,0,1,1]}, {"text": "ok"}, {"text": "good", "bbox": [1,2,3,4]}]'
        results = parse_grounded_output(raw, 100, 100)
        # Empty text skipped; missing bbox skipped; only "good" survives.
        assert [r[1] for r in results] == ["good"]

    def test_no_json_returns_empty(self):
        assert parse_grounded_output("I cannot read this image.", 100, 100) == []

    def test_malformed_json_returns_empty(self):
        assert parse_grounded_output("[{bad json", 100, 100) == []


class TestEngineFactory:
    def test_unknown_engine_raises(self):
        with pytest.raises(ValueError, match="Unknown OCR engine"):
            get_engine("does_not_exist")
