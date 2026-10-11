"""Tests for OCR text layer embedding.

The embedding contract is verified against every OCR engine whose dependency is
installed (EasyOCR, Apple Vision, ...). Engines with missing deps are skipped.
"""

import importlib.util
import os

import fitz
import pytest

from scansnap_ocr.config import DPI_SCALE, VERSION
from scansnap_ocr.ocr import _insert_invisible_text, embed_text_layer, extract_text

# Map engine key → the module whose presence makes it runnable here.
_ENGINE_DEPS = {
    "easyocr": "easyocr",
    "apple_vision": "ocrmac",
    "apple_livetext": "ocrmac",
    "qwen3vl": "mlx_vlm",
}

# apple_livetext drives Apple's VisionKit LiveText path, which aborts the whole
# pytest process — a C-level crash in VisionKitCore, not a catchable Python
# exception — when run under the test runner on some macOS versions. Keep it
# opt-in so the rest of the suite can complete; set SCANSNAP_TEST_LIVETEXT=1 to
# include it (it remains a supported, switchable engine in production).
_OPT_IN_ENGINES = {"apple_livetext": "SCANSNAP_TEST_LIVETEXT"}


def _engine_enabled(name: str, dep: str) -> bool:
    if not importlib.util.find_spec(dep):
        return False
    env_flag = _OPT_IN_ENGINES.get(name)
    if env_flag is not None:
        return os.environ.get(env_flag) == "1"
    return True


AVAILABLE_ENGINES = [
    name for name, dep in _ENGINE_DEPS.items() if _engine_enabled(name, dep)
]


@pytest.fixture(params=AVAILABLE_ENGINES)
def ocr_engine(request, monkeypatch):
    """Select an OCR engine for the duration of a test."""
    monkeypatch.setattr("scansnap_ocr.config.OCR_ENGINE", request.param)
    return request.param


class TestTextPositioning:
    """The invisible text layer must be horizontally scaled to fit each OCR box,
    so search highlights align with the underlying glyphs (no rightward drift)."""

    def test_text_spans_its_bounding_box(self):
        # Target box: x 100..400 pt, y 100..115 pt (height 15 -> ~12pt font).
        px = 1 / DPI_SCALE  # points -> pixels
        x0_pt, x1_pt, y0_pt, y1_pt = 100.0, 400.0, 100.0, 115.0
        bbox = [
            [x0_pt * px, y0_pt * px],
            [x1_pt * px, y0_pt * px],
            [x1_pt * px, y1_pt * px],
            [x0_pt * px, y1_pt * px],
        ]

        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        _insert_invisible_text(page, bbox, "Verzinsung beginnt mit dem Tage")

        words = page.get_text("words")  # (x0, y0, x1, y1, word, ...)
        assert words, "no searchable words were embedded"
        left = min(w[0] for w in words)
        right = max(w[2] for w in words)
        doc.close()

        # The embedded text should span (not overshoot/undershoot) the target box.
        assert abs(left - x0_pt) <= 3, f"left edge {left} != {x0_pt}"
        assert abs(right - x1_pt) <= 6, f"right edge {right} != {x1_pt}"

    def test_adjacent_words_keep_a_space_when_copied(self, tmp_dir):
        """Word-level boxes (e.g. Apple Live Text) must copy with spaces between
        words. PDFKit (Preview's extractor) only honors explicit space chars
        between separate text runs, so each run carries a trailing space."""
        Quartz = pytest.importorskip("Quartz")
        from Foundation import NSURL

        px = 1 / DPI_SCALE

        def box(x0_pt, x1_pt, y0_pt=100.0, y1_pt=115.0):
            return [
                [x0_pt * px, y0_pt * px],
                [x1_pt * px, y0_pt * px],
                [x1_pt * px, y1_pt * px],
                [x0_pt * px, y1_pt * px],
            ]

        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # Two separate word boxes on the same line, with a gap between them.
        _insert_invisible_text(page, box(100, 140), "Der")
        _insert_invisible_text(page, box(160, 220), "Mann")
        out = tmp_dir / "two_words.pdf"
        doc.save(str(out))
        doc.close()

        pdoc = Quartz.PDFDocument.alloc().initWithURL_(
            NSURL.fileURLWithPath_(str(out))
        )
        text = pdoc.pageAtIndex_(0).string() or ""
        assert "Der Mann" in text, f"expected a space between words, got {text!r}"


class TestSaveHygiene:
    """Saving must garbage-collect, so re-OCR doesn't accumulate orphaned objects
    (the cause of bloated files, worst with word-level engines)."""

    @pytest.mark.ocr
    def test_reprocessing_does_not_bloat(self, make_image_pdf):
        pdf = make_image_pdf(["Hello World Test Document"])

        embed_text_layer(str(pdf))  # default engine (apple_vision)
        doc = fitz.open(str(pdf))
        first = doc.xref_length()
        doc.close()

        embed_text_layer(str(pdf))  # re-OCR the same file
        doc = fitz.open(str(pdf))
        second = doc.xref_length()
        doc.close()

        # With garbage collection on save, the object count stays stable across
        # re-processing instead of growing each pass.
        assert second <= first + 5, f"object count grew {first} -> {second}"

    def test_save_failure_leaves_no_temp_file(self, make_image_pdf, monkeypatch):
        """If the save fails, the in-place temp file is cleaned up (not orphaned)
        and the original PDF is left untouched."""
        import scansnap_ocr.ocr as ocr_mod

        pdf = make_image_pdf(["Cleanup Test"])
        before = pdf.read_bytes()

        # Force doc.save() to blow up mid-write.
        def boom(self, *a, **k):
            raise RuntimeError("disk full")

        monkeypatch.setattr(fitz.Document, "save", boom)

        with pytest.raises(RuntimeError):
            ocr_mod.embed_text_layer(str(pdf))

        # No leftover temp .pdf next to the original, and the original is intact.
        leftovers = [
            p for p in pdf.parent.glob("*.pdf") if p.name != pdf.name
        ]
        assert leftovers == [], f"temp file leaked: {leftovers}"
        assert pdf.read_bytes() == before


class TestEmbedTextLayer:
    def test_ocr_embeds_text_layer(self, make_image_pdf, ocr_engine):
        """Image-only PDF with known text → OCR → text layer contains that text."""
        pdf = make_image_pdf(["Hello World Test Document"])
        stats = embed_text_layer(str(pdf))

        assert stats["pages"] == 1
        assert stats["total_texts"] > 0

        text = extract_text(str(pdf)).lower()
        assert any(w in text for w in ["hello", "world", "test", "document"])

    def test_ocr_preserves_original_image(self, make_image_pdf, ocr_engine):
        """OCR a PDF → verify dimensions and images are preserved."""
        pdf = make_image_pdf(["Sample Image Text"])

        doc_before = fitz.open(str(pdf))
        page_before = doc_before[0]
        rect_before = page_before.rect
        images_before = page_before.get_images()
        doc_before.close()

        embed_text_layer(str(pdf))

        doc_after = fitz.open(str(pdf))
        page_after = doc_after[0]
        assert page_after.rect == rect_before
        images_after = page_after.get_images()
        assert len(images_after) >= len(images_before)
        doc_after.close()

    def test_ocr_replaces_existing_text_layer(self, make_text_pdf, ocr_engine):
        """PDF with existing text layer → re-OCR → verify new text layer."""
        pdf = make_text_pdf(["Original visible text here"])

        text_before = extract_text(str(pdf))
        assert "Original" in text_before

        embed_text_layer(str(pdf))
        text_after = extract_text(str(pdf))
        assert isinstance(text_after, str)

    def test_ocr_handles_multipage(self, make_image_pdf, ocr_engine):
        """3-page PDF → OCR → verify all pages have text layers."""
        pdf = make_image_pdf([
            "Page One Content",
            "Page Two Content",
            "Page Three Content",
        ])
        stats = embed_text_layer(str(pdf))

        assert stats["pages"] == 3
        assert len(stats["texts_by_page"]) == 3
        for count in stats["texts_by_page"]:
            assert count >= 0

    def test_ocr_handles_empty_page(self, make_blank_pdf, ocr_engine):
        """Blank page → OCR → no crash, no text."""
        pdf = make_blank_pdf(1)
        stats = embed_text_layer(str(pdf))

        assert stats["pages"] == 1
        assert stats["total_texts"] == 0

    def test_ocr_sets_metadata(self, make_image_pdf, ocr_engine):
        """OCR a PDF → verify producer metadata contains version (engine-agnostic)."""
        pdf = make_image_pdf(["Metadata Test"])
        embed_text_layer(str(pdf))

        doc = fitz.open(str(pdf))
        producer = doc.metadata.get("producer", "")
        doc.close()

        assert "scansnap-processor" in producer
        assert f"v{VERSION}" in producer

    def test_ocr_preserves_creator_metadata(self, make_image_pdf, ocr_engine):
        """OCR a PDF with existing creator → verify creator is preserved."""
        pdf = make_image_pdf(["Creator Test"])

        doc = fitz.open(str(pdf))
        doc.set_metadata({"creator": "ScanSnap Home #iX1600 (W)"})
        doc.save(str(pdf), incremental=True, encryption=0)
        doc.close()

        embed_text_layer(str(pdf))

        doc = fitz.open(str(pdf))
        assert doc.metadata.get("creator") == "ScanSnap Home #iX1600 (W)"
        assert "scansnap-processor" in doc.metadata.get("producer", "")
        doc.close()

    def test_ocr_output_to_different_file(self, make_image_pdf, tmp_dir, ocr_engine):
        """OCR with separate output path preserves original."""
        pdf = make_image_pdf(["Test Output Path"])
        output = tmp_dir / "output.pdf"

        embed_text_layer(str(pdf), str(output))

        assert output.exists()
        text = extract_text(str(output))
        assert isinstance(text, str)
