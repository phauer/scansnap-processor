"""Core OCR: PDF → OCR engine → embed invisible text layer.

The OCR engine is pluggable (see ``scansnap_ocr.engines``). Every engine returns
results in the same ``(bbox, text, confidence)`` shape, so the text-layer
embedding below is engine-agnostic.
"""

import io
import logging
import os
import tempfile

import fitz  # pymupdf
import numpy as np
from PIL import Image

from .config import DPI_SCALE, OCR_DPI, VERSION
from .engines import get_engine

logger = logging.getLogger(__name__)


def render_page_to_image(page: fitz.Page, dpi: int = OCR_DPI) -> np.ndarray:
    """Render a PDF page to a numpy array at the given DPI."""
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return np.array(img)


def embed_text_layer(pdf_path: str, output_path: str | None = None) -> dict:
    """OCR a PDF and embed an invisible text layer.

    Args:
        pdf_path: Path to the input PDF.
        output_path: Where to save. If None, overwrites in place.

    Returns:
        dict with 'pages', 'total_texts', 'texts_by_page' keys.
    """
    if output_path is None:
        output_path = pdf_path

    engine = get_engine()
    doc = fitz.open(pdf_path)
    stats = {"pages": len(doc), "total_texts": 0, "texts_by_page": []}

    for page_num in range(len(doc)):
        page = doc[page_num]

        # Render BEFORE removing text (captures visual content)
        image = render_page_to_image(page)

        # Remove any existing text (to re-OCR cleanly)
        _remove_text_layer(page)

        # OCR the rendered image
        results = engine.recognize(image)

        page_text_count = 0
        for bbox, text, _confidence in results:
            if not text.strip():
                continue
            _insert_invisible_text(page, bbox, text)
            page_text_count += 1

        stats["total_texts"] += page_text_count
        stats["texts_by_page"].append(page_text_count)

    doc.set_metadata({
        "producer": f"scansnap-processor v{VERSION} ({engine.name})",
        "creator": doc.metadata.get("creator", ""),
    })

    # Save with garbage collection + compression. Each text block is written via
    # its own TextWriter (needed for per-block horizontal scaling), which creates
    # many duplicate font/resource objects — especially for word-level engines
    # like Apple Live Text (thousands of word runs). garbage=4 deduplicates those
    # identical objects and drops orphans left by re-OCR/redaction; deflate
    # compresses the streams. Without this, files are 30-60% larger.
    save_opts = dict(garbage=4, deflate=True)

    # pymupdf can't save non-incrementally to the same file.
    # Save to a temp file, then replace the original.
    if output_path == pdf_path:
        dir_name = os.path.dirname(pdf_path) or "."
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=dir_name)
        os.close(fd)
        try:
            doc.save(tmp_path, **save_opts)
            doc.close()
            os.replace(tmp_path, output_path)
        except Exception:
            # Close best-effort so a failing close() can't mask cleanup, then
            # remove the temp file if os.replace never consumed it.
            try:
                doc.close()
            except Exception:
                pass
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
    else:
        doc.save(output_path, **save_opts)
        doc.close()

    return stats


def _remove_text_layer(page: fitz.Page):
    """Remove existing text content from a page while preserving images."""
    # Get all text blocks and redact them (removes text but keeps images)
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if block.get("type") == 0:  # text block
            rect = fitz.Rect(block["bbox"])
            page.add_redact_annot(rect)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)


# Reused across the thousands of text blocks per document.
_FONT = fitz.Font("helv")


def _horizontal_scale(text: str, fontsize: float, target_width: float) -> float:
    """Scale factor so `text` rendered in _FONT spans exactly `target_width`.

    OCR engines (especially Apple Vision) return one box per *line*. Helvetica's
    glyph advances don't match the scanned font's, so without scaling the invisible
    text drifts rightward along the line and search highlights land beside the words.
    Stretching the line to its box width snaps start/end/interior positions back.
    """
    natural = _FONT.text_length(text, fontsize=fontsize)
    if natural <= 0 or target_width <= 0:
        return 1.0
    return target_width / natural


def _insert_invisible_text(page: fitz.Page, bbox, text: str):
    """Insert invisible, searchable text positioned over the given bounding box.

    bbox: 4-point pixel polygon [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] at OCR_DPI.
    The text is scaled horizontally to fit the box width so search highlights
    align with the underlying scanned glyphs.
    """
    # Convert pixel coordinates to PDF points
    x_coords = [pt[0] for pt in bbox]
    y_coords = [pt[1] for pt in bbox]

    x0 = min(x_coords) * DPI_SCALE
    y0 = min(y_coords) * DPI_SCALE
    x1 = max(x_coords) * DPI_SCALE
    y1 = max(y_coords) * DPI_SCALE

    # Calculate font size to roughly fit the text in the bbox height
    bbox_height = y1 - y0
    fontsize = max(bbox_height * 0.8, 4)  # minimum 4pt

    baseline_y = y1 - bbox_height * 0.1
    # Scale based on the word itself (not the trailing space below), so the word
    # still fills its box and the space lands in the inter-word gap.
    scale_x = _horizontal_scale(text, fontsize, x1 - x0)
    # Scale horizontally around the left edge of the box (the text start).
    morph = (fitz.Point(x0, baseline_y), fitz.Matrix(scale_x, 1))

    # Append a trailing space so word-level boxes (e.g. Apple Live Text) keep
    # spaces between words when a paragraph is copied. PDFKit/Preview only honor
    # explicit space chars between separate text runs — it won't infer them from
    # gaps. Harmless for line-level engines (one extra space at end of line).
    draw_text = text + " "

    # Insert invisible text (render mode 3 = invisible)
    text_writer = fitz.TextWriter(page.rect)
    try:
        text_writer.append(
            pos=(x0, baseline_y),
            text=draw_text,
            fontsize=fontsize,
            font=_FONT,
        )
        text_writer.write_text(page, render_mode=3, opacity=0, morph=morph)
    except Exception:
        # Fallback: insert as plain invisible text
        try:
            page.insert_text(
                point=(x0, y1),
                text=draw_text,
                fontsize=fontsize,
                render_mode=3,
                overlay=True,
                morph=morph,
            )
        except Exception:
            # Both paths failed: this block's text is lost from the layer. Log it
            # so missing searchable text is visible in diagnostics, then skip.
            logger.warning(
                "Could not embed OCR text block on page %s: %r",
                getattr(page, "number", "?"),
                text[:60],
            )


def extract_text(pdf_path: str) -> str:
    """Extract text from a PDF (for testing/verification)."""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    doc.close()
    return text


def extract_text_by_page(pdf_path: str) -> list[str]:
    """Extract text from each page of a PDF."""
    doc = fitz.open(pdf_path)
    texts = []
    for page in doc:
        texts.append(page.get_text())
    doc.close()
    return texts
