"""Photo folder → markdown: OCR phone photos (HEIC etc.) into one text document."""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .config import PHOTO_EXTENSIONS, PHOTO_MAX_EDGE, PHOTO_MIN_CHARS
from .engines import get_engine

logger = logging.getLogger(__name__)

_TERMINAL = ".!?:;\"'»«“”‘’)…"
_KEEP_HYPHEN_BEFORE = {"und", "oder", "bzw.", "sowie"}


@dataclass
class Line:
    """One recognized text line in image pixel coordinates (origin top-left)."""

    text: str
    left: float
    right: float
    top: float
    bottom: float

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 1.0)

    @property
    def center(self) -> float:
        return (self.top + self.bottom) / 2


def list_photos(folder: Path) -> list[Path]:
    """Image files directly in ``folder``, sorted by name (case-insensitive ext)."""
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in PHOTO_EXTENSIONS
         and not p.name.startswith(".")),
        key=lambda p: p.name.lower(),
    )


def load_image(path: Path, max_edge: int = PHOTO_MAX_EDGE) -> np.ndarray:
    """Decode a photo to an RGB array, honoring EXIF orientation and bounding its size."""
    import pillow_heif

    pillow_heif.register_heif_opener()
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        if max(img.size) > max_edge:
            img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        return np.array(img)


def _to_lines(results) -> list[Line]:
    lines = []
    for bbox, text, _conf in results:
        text = text.strip()
        if not text:
            continue
        xs = [pt[0] for pt in bbox]
        ys = [pt[1] for pt in bbox]
        lines.append(Line(text, min(xs), max(xs), min(ys), max(ys)))
    return order_lines(lines)


def order_lines(lines: list[Line]) -> list[Line]:
    """Reading order: group boxes sharing a row (center within half a line height),
    rows top to bottom, boxes left to right."""
    rows: list[list[Line]] = []
    for ln in sorted(lines, key=lambda x: x.center):
        if rows and abs(ln.center - statistics.mean(r.center for r in rows[-1])) < ln.height / 2:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    out = []
    for row in rows:
        row.sort(key=lambda x: x.left)
        if len(row) == 1:
            out.append(row[0])
        else:
            out.append(Line(
                " ".join(r.text for r in row),
                row[0].left, max(r.right for r in row),
                min(r.top for r in row), max(r.bottom for r in row),
            ))
    return out


def ocr_photo(image: np.ndarray, min_chars: int = PHOTO_MIN_CHARS) -> list[Line]:
    """OCR one photo; if almost nothing is found, retry rotated and keep the best."""
    engine = get_engine()
    best = _to_lines(engine.recognize(image))
    if sum(len(ln.text) for ln in best) >= min_chars:
        return best
    best_chars = sum(len(ln.text) for ln in best)
    for k in (1, 2, 3):
        lines = _to_lines(engine.recognize(np.ascontiguousarray(np.rot90(image, k))))
        chars = sum(len(ln.text) for ln in lines)
        if chars > best_chars:
            best, best_chars = lines, chars
        if best_chars >= min_chars:
            break
    return best


def _join(prev: str, nxt: str) -> str:
    """Join two consecutive lines, removing a hyphenation break when safe."""
    if re.search(r"[A-Za-zÄÖÜäöüß]-$", prev):
        if nxt[:1].islower():
            if nxt.split()[0].lower() not in _KEEP_HYPHEN_BEFORE:
                return prev[:-1] + nxt
        elif nxt[:1].isupper():
            return prev + nxt  # compound like "Ab-Bau": keep the hyphen
    return prev + " " + nxt


def _strip_page_furniture(pages: list[list[Line]]) -> list[list[Line]]:
    """Drop bare page numbers and headers/footers repeated on 3+ pages."""
    def key(t: str) -> str:
        return re.sub(r"\d+", "#", t.strip().lower())

    counts: dict[tuple[str, str], int] = {}
    for lines in pages:
        if lines:
            for pos, ln in (("top", lines[0]), ("bottom", lines[-1])):
                counts[(pos, key(ln.text))] = counts.get((pos, key(ln.text)), 0) + 1
    cleaned = []
    for lines in pages:
        lines = list(lines)
        while lines and re.fullmatch(r"[-–\s]*\d{1,4}[-–\s]*", lines[0].text):
            lines.pop(0)
        while lines and re.fullmatch(r"[-–\s]*\d{1,4}[-–\s]*", lines[-1].text):
            lines.pop()
        if len(pages) >= 3:
            if lines and counts.get(("top", key(lines[0].text)), 0) >= 3:
                lines.pop(0)
            if lines and counts.get(("bottom", key(lines[-1].text)), 0) >= 3:
                lines.pop()
        cleaned.append(lines)
    return cleaned


def reflow(pages: list[list[Line]]) -> str:
    """Turn per-photo lines into paragraphs separated by blank lines."""
    pages = _strip_page_furniture(pages)
    paragraphs: list[str] = []
    carry = False  # last paragraph may continue on the next page
    for lines in pages:
        if not lines:
            continue
        med_h = statistics.median(ln.height for ln in lines)
        widest = max(ln.right - ln.left for ln in lines)
        cur: str | None = None
        prev: Line | None = None
        for ln in lines:
            new_par = cur is None
            if prev is not None:
                gap = ln.top - prev.bottom
                short_end = (prev.right - prev.left) < 0.7 * widest and prev.text[-1] in _TERMINAL
                if gap > 0.9 * med_h or short_end:
                    new_par = True
            if new_par:
                if cur is not None:
                    paragraphs.append(cur)
                if cur is None and carry and paragraphs and ln.text[:1].islower():
                    cur = paragraphs.pop()
                    cur = _join(cur, ln.text)
                else:
                    cur = ln.text
            else:
                cur = _join(cur, ln.text)
            prev = ln
        if cur is not None:
            paragraphs.append(cur)
            carry = cur[-1] not in _TERMINAL
    return "\n\n".join(paragraphs)


def build_markdown(title: str, names: list[str], pages: list[list[Line]], raw: bool = False) -> str:
    """Assemble the markdown document for the photos (``names`` parallel to ``pages``)."""
    parts = [f"# {title}"]
    if raw:
        for name, lines in zip(names, pages, strict=True):
            parts.append(f"## {name}\n\n" + "\n".join(ln.text for ln in lines))
    else:
        parts.append(reflow(pages))
    return "\n\n".join(p for p in parts if p) + "\n"
