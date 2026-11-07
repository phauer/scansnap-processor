"""Tests for the photo folder → markdown feature (no real OCR, made-up text)."""

import numpy as np
import pytest
from PIL import Image

import photos_to_md
from scansnap_ocr import photos
from scansnap_ocr.photos import Line, build_markdown, list_photos, load_image, reflow


def L(text, top, left=0, right=500, h=20):
    return Line(text, left, right, top, top + h)


def page(*texts, start=0, step=24):
    return [L(t, start + i * step) for i, t in enumerate(texts)]


class TestListPhotos:
    def test_sorted_filtered(self, tmp_path):
        for n in ["IMG_2.HEIC", "img_1.jpg", "IMG_3.PNG", "notes.txt", "doc.pdf", ".hidden.jpg"]:
            (tmp_path / n).write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "IMG_0.jpg").write_bytes(b"x")
        assert [p.name for p in list_photos(tmp_path)] == ["img_1.jpg", "IMG_2.HEIC", "IMG_3.PNG"]

    def test_empty(self, tmp_path):
        assert list_photos(tmp_path) == []


class TestReflow:
    def test_joins_lines_and_hyphenation(self):
        out = reflow([page("Die Ver-", "sicherung gilt für", "alle Kinder.")])
        assert out == "Die Versicherung gilt für alle Kinder."

    def test_keeps_hyphen_before_und(self):
        assert "Be- und Entladen" in reflow([page("Das Be-", "und Entladen geht.")])

    def test_keeps_hyphen_before_capital(self):
        assert "Ab-Bau" in reflow([page("Der Ab-", "Bau läuft.")])

    def test_paragraph_break_on_gap(self):
        lines = [L("Erster Absatz.", 0), L("Zweiter Absatz.", 80)]
        assert reflow([lines]) == "Erster Absatz.\n\nZweiter Absatz."

    def test_page_numbers_dropped(self):
        out = reflow([page("12", "Text eins", "13"), page("Text zwei")])
        assert "12" not in out and "13" not in out

    def test_running_header_dropped(self):
        pages = [page(f"Kapitel Eins {i}", "Inhalt A.", "Mehr B.") for i in range(3)]
        out = reflow(pages)
        assert "Kapitel" not in out and "Inhalt A." in out

    def test_paragraph_continues_across_pages(self):
        out = reflow([page("Der Satz geht", "noch weiter"), page("und endet hier.")])
        assert out == "Der Satz geht noch weiter und endet hier."

    def test_no_merge_after_sentence_end(self):
        out = reflow([page("Fertig."), page("und klein.")])
        assert out == "Fertig.\n\nund klein."

    def test_empty(self):
        assert reflow([]) == ""
        assert reflow([[]]) == ""


class TestBuildMarkdown:
    def test_raw_sections(self):
        md = build_markdown("Titel", ["a.heic"], [page("Zeile 1", "Zeile 2")], raw=True)
        assert md == "# Titel\n\n## a.heic\n\nZeile 1\nZeile 2\n"

    def test_reflowed(self):
        assert build_markdown("T", ["a"], [page("Hallo Welt.")]) == "# T\n\nHallo Welt.\n"


class TestOrderLines:
    def test_same_row_merged_left_to_right(self):
        a, b = L("rechts", 0, left=300, right=400), L("links", 2, left=0, right=100)
        [row] = photos.order_lines([a, b])
        assert row.text == "links rechts"


class TestLoadImage:
    def test_exif_rotation_and_downscale(self, tmp_path):
        img = Image.new("RGB", (400, 200), "white")
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90° CW on display
        path = tmp_path / "a.jpg"
        img.save(path, exif=exif)
        arr = load_image(path, max_edge=100)
        assert arr.shape == (100, 50, 3)

    def test_heic_roundtrip(self, tmp_path):
        pillow_heif = pytest.importorskip("pillow_heif")
        pillow_heif.register_heif_opener()
        path = tmp_path / "a.heic"
        Image.new("RGB", (64, 32), "white").save(path)
        assert load_image(path).shape == (32, 64, 3)


class FakeEngine:
    name = "fake"

    def __init__(self, text_when):
        self.text_when = text_when
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        if self.text_when(image):
            return [([[0, 0], [100, 0], [100, 20], [0, 20]], "x" * 50, 0.9)]
        return []


class TestOcrPhoto:
    def test_rotation_retry(self, monkeypatch):
        img = np.zeros((10, 20, 3), dtype=np.uint8)
        eng = FakeEngine(lambda a: a.shape[0] == 20)  # only the 90°-rotated image "has text"
        monkeypatch.setattr(photos, "get_engine", lambda: eng)
        lines = photos.ocr_photo(img)
        assert lines and eng.calls == 2

    def test_no_retry_when_text_found(self, monkeypatch):
        eng = FakeEngine(lambda a: True)
        monkeypatch.setattr(photos, "get_engine", lambda: eng)
        photos.ocr_photo(np.zeros((10, 20, 3), dtype=np.uint8))
        assert eng.calls == 1


class TestCli:
    def _patch(self, monkeypatch, fail=()):
        def fake_ocr(image):
            return [L("Hallo Welt.", 0)]

        def fake_load(path):
            if path.name in fail:
                raise ValueError("broken")
            return np.zeros((2, 2, 3), dtype=np.uint8)

        monkeypatch.setattr(photos_to_md, "ocr_photo", fake_ocr)
        monkeypatch.setattr(photos_to_md, "load_image", fake_load)

    def test_missing_folder(self, tmp_path):
        assert photos_to_md.main([str(tmp_path / "nope")]) == 1

    def test_empty_folder(self, tmp_path):
        assert photos_to_md.main([str(tmp_path)]) == 1

    def test_default_output(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        folder = tmp_path / "buch"
        folder.mkdir()
        (folder / "a.heic").write_bytes(b"x")
        assert photos_to_md.main([str(folder)]) == 0
        assert (folder / "buch.md").read_text() == "# buch\n\nHallo Welt.\n"

    def test_output_and_raw(self, tmp_path, monkeypatch):
        self._patch(monkeypatch)
        (tmp_path / "a.jpg").write_bytes(b"x")
        out = tmp_path / "o.md"
        assert photos_to_md.main([str(tmp_path), "-o", str(out), "--raw"]) == 0
        assert "## a.jpg" in out.read_text()

    def test_failure_continues_and_exits_1(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, fail={"a.jpg"})
        (tmp_path / "a.jpg").write_bytes(b"x")
        (tmp_path / "b.jpg").write_bytes(b"x")
        out = tmp_path / "o.md"
        assert photos_to_md.main([str(tmp_path), "-o", str(out)]) == 1
        assert "Hallo Welt." in out.read_text()


@pytest.mark.ocr
def test_end_to_end_ocr(tmp_path):
    from PIL import ImageDraw, ImageFont

    img = Image.new("RGB", (1200, 300), "white")
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 60)
    ImageDraw.Draw(img).text((40, 100), "Musterstadt Hausnummer", fill="black", font=font)
    path = tmp_path / "t.png"
    img.save(path)
    text = " ".join(ln.text for ln in photos.ocr_photo(load_image(path)))
    assert "Musterstadt" in text
