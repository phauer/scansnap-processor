"""Shared test fixtures: sample PDF generation, temp dirs."""

from pathlib import Path

import fitz  # pymupdf
import pytest


def pytest_collection_modifyitems(items):
    """Tests parametrized over OCR engines run real OCR → mark them ``ocr`` (needs a
    Metal GPU for Apple Vision; CI deselects them with ``-m "not ocr"``)."""
    for item in items:
        if "ocr_engine" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.ocr)


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory."""
    return tmp_path


@pytest.fixture
def make_text_pdf(tmp_path):
    """Factory fixture: create a PDF with known text on each page."""

    def _make(pages: list[str], filename: str = "test.pdf") -> Path:
        path = tmp_path / filename
        doc = fitz.open()
        for text in pages:
            page = doc.new_page(width=595, height=842)  # A4
            # Write text visibly so OCR can read it
            tw = fitz.TextWriter(page.rect)
            tw.append(pos=(72, 100), text=text, fontsize=24, font=fitz.Font("helv"))
            tw.write_text(page)
        doc.save(str(path))
        doc.close()
        return path

    return _make


@pytest.fixture
def make_image_pdf(tmp_path):
    """Factory fixture: create an image-only PDF (text rendered as image)."""

    def _make(pages: list[str], filename: str = "scan.pdf") -> Path:
        path = tmp_path / filename
        doc = fitz.open()
        for text in pages:
            # Create a temporary doc with text, render to image, insert into new doc
            tmp_doc = fitz.open()
            tmp_page = tmp_doc.new_page(width=595, height=842)
            tw = fitz.TextWriter(tmp_page.rect)
            tw.append(pos=(72, 100), text=text, fontsize=24, font=fitz.Font("helv"))
            tw.write_text(tmp_page)

            # Render to pixmap at 300 DPI
            mat = fitz.Matrix(300 / 72, 300 / 72)
            pix = tmp_page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            tmp_doc.close()

            # Create image-only page
            page = doc.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=img_bytes)

        doc.save(str(path))
        doc.close()
        return path

    return _make


@pytest.fixture
def make_blank_pdf(tmp_path):
    """Factory fixture: create a PDF with blank pages."""

    def _make(num_pages: int = 1, filename: str = "blank.pdf") -> Path:
        path = tmp_path / filename
        doc = fitz.open()
        for _ in range(num_pages):
            doc.new_page(width=595, height=842)
        doc.save(str(path))
        doc.close()
        return path

    return _make


