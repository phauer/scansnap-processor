"""Photo folder → markdown: OCR phone photos (HEIC etc.) into one text document."""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .config import PHOTO_EXTENSIONS, PHOTO_MAX_EDGE, PHOTO_MIN_CHARS
from .engines import get_engine

logger = logging.getLogger(__name__)

_TERMINAL = ".!?:;\"'»«“”‘’)…"
_KEEP_HYPHEN_BEFORE = {"und", "oder", "bzw.", "sowie"}


# Numbered heading such as "3 Musterthemen" or "3.18 Muster gründen" (chapter numbers,
# no trailing dot so "1. Auflage" is not one).
_HEADING_RE = re.compile(r"(\d{1,2}(?:\.\d{1,2}){0,3}) +([A-ZÄÖÜ].{2,80})")
# Running header/footer such as "52 | 3 Titel" or "3.18 Titel | 53".
_PIPE_FURNITURE_RE = re.compile(r"\d{1,4} *\|.*|.*\| *\d{1,4}")
# Running header like "3.6 Titel 39" (chapter number, title, page number as a last box).
_NUMBERED_HEADER_RE = re.compile(r"\d{1,2}(?:\.\d{1,2})* +[A-ZÄÖÜ].*\D \d{1,3}")


def _is_page_header(ln: Line) -> bool:
    return bool(
        _PIPE_FURNITURE_RE.fullmatch(ln.text.strip())
        or (
            ln.cells
            and re.fullmatch(r"\d{1,3}", ln.cells[-1].text.strip())
            and _NUMBERED_HEADER_RE.fullmatch(ln.text.strip())
        )
    )


def heading_level(text: str) -> int | None:
    """Markdown level (2-6) if ``text`` is a numbered heading, else None.

    Depth follows the number ("3" → 2, "3.18" → 3, "3.1.2" → 4). Lines ending in a digit
    (table of contents entries with page numbers), sentence punctuation or a dot leader
    are not headings. Photo box heights are too noisy (perspective) to use for this.
    """
    m = _HEADING_RE.fullmatch(text.strip())
    if not m:
        return None
    title = m.group(2).rstrip()
    if not title[-1].isalpha() or ".." in title or "•" in title:
        return None  # page-number / dot-leader TOC entries, sentence ends
    return min(m.group(1).count(".") + 2, 6)


@dataclass
class Line:
    """One recognized text line in image pixel coordinates (origin top-left)."""

    text: str
    left: float
    right: float
    top: float
    bottom: float
    #: The separate boxes of a row that merged several (table cells), left to right.
    cells: list[Line] = field(default_factory=list)

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
                cells=list(row),
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


def _furniture_core(text: str) -> str:
    """A header line without its page-number decoration, lowercased: "36 | 3 Titel",
    "| 3 Titel", "42 3 Titel" and "3 Titel | 37" all become "3 titel"."""
    t = text.strip()
    t = re.sub(r"^\|\s*", "", t)
    t = re.sub(r"^\d{1,4}\s*\|\s*", "", t)
    t = re.sub(r"^\d{1,4}\s+(?=\d)", "", t)  # page number glued to a chapter number
    t = re.sub(r"\s*\|\s*\d{1,4}$", "", t)
    return re.sub(r"\s+", " ", t).lower()


def _strip_page_furniture(pages: list[list[Line]]) -> list[list[Line]]:
    """Drop bare page numbers and running headers/footers.

    A running header repeats the current chapter title at the top (or bottom) of many
    pages, often with a page number or pipe attached ("36 | 3 Titel") or with the page
    number lost by the OCR ("3 Titel"). A line whose undecorated text is the first or last
    line of 3+ pages is furniture. The first undecorated occurrence is kept: it is usually
    the chapter's real heading, not a header.
    """
    def key(t: str) -> str:
        return re.sub(r"\d+", "#", _furniture_core(t))

    stage1 = []
    for lines in pages:
        lines = list(lines)
        while lines and (re.fullmatch(r"[-–\s]*\d{1,4}[-–\s]*", lines[0].text)
                         or _is_page_header(lines[0])):
            lines.pop(0)
        while lines and (re.fullmatch(r"[-–\s]*\d{1,4}[-–\s]*", lines[-1].text)
                         or _is_page_header(lines[-1])):
            lines.pop()
        stage1.append(lines)

    def norm(t: str) -> str:
        return re.sub(r"\s+", " ", t.strip().lower())

    counts: dict[tuple[str, str], int] = {}
    plain_variants: dict[tuple[str, str], set[str]] = {}  # undecorated texts per header
    for lines in stage1:
        if lines:
            for pos, ln in (("top", lines[0]), ("bottom", lines[-1])):
                k = (pos, key(ln.text))
                counts[k] = counts.get(k, 0) + 1
                if _furniture_core(ln.text) == norm(ln.text):
                    plain_variants.setdefault(k, set()).add(norm(ln.text))

    kept_plain: set[tuple[str, str]] = set()

    def is_furniture(pos: str, ln: Line) -> bool:
        k = (pos, key(ln.text))
        if counts.get(k, 0) < 3:
            return False
        # Decorated (page number / pipe attached) or plain texts that differ between pages
        # (a varying page number): always furniture.
        decorated = _furniture_core(ln.text) != norm(ln.text) or len(plain_variants[k]) > 1
        if decorated or k in kept_plain:
            return True
        kept_plain.add(k)
        return False

    cleaned = []
    for lines in stage1:
        if len(pages) >= 3:
            if lines and is_furniture("top", lines[0]):
                lines.pop(0)
            if lines and is_furniture("bottom", lines[-1]):
                lines.pop()
        cleaned.append(lines)
    return cleaned


_TOC_HEADING_RE = re.compile(
    r"(?:\d{1,4} *[|/]? *)?Inhaltsverzeichnis(?: *[|/]? *\d{1,4})?", re.IGNORECASE
)
_NUM_ONLY_RE = re.compile(r"\d{1,4}")
_ORPHAN_NUMBERING_RE = re.compile(r"\d{1,2}(?:\.\d{1,2})+")
_TOC_NUMBERED_RE = re.compile(r"(\d{1,2}(?:\.\d{1,2}){0,3}) +(\S.*)")


def _tocish(text: str) -> bool:
    """Does this line look like part of a table of contents?"""
    t = text.strip()
    return bool(
        _NUM_ONLY_RE.fullmatch(t)
        or _ORPHAN_NUMBERING_RE.fullmatch(t)
        or _TOC_HEADING_RE.fullmatch(t)
        or re.search(r"\s\d{1,3}$|\.\.|•", t)
        or _TOC_NUMBERED_RE.fullmatch(t)
    )


def find_toc_pages(pages: list[list[Line]]) -> list[int]:
    """Indices of the consecutive pages forming the table of contents.

    Starts at the first page with an "Inhaltsverzeichnis" line and continues while at
    least 60 % of a page's lines look like TOC entries (page numbers, dot leaders,
    numbered titles).
    """
    start = next(
        (i for i, lines in enumerate(pages)
         if any(_TOC_HEADING_RE.fullmatch(ln.text.strip()) for ln in lines)),
        None,
    )
    if start is None:
        return []
    idx = [start]
    for i in range(start + 1, len(pages)):
        lines = pages[i]
        if not lines or sum(_tocish(ln.text) for ln in lines) < 0.6 * len(lines):
            break
        idx.append(i)
    return idx


def _successors(number: str) -> list[str]:
    """Numbers that may directly follow ``number`` in a TOC: its first child, its next
    sibling, then the next sibling of each ancestor ("3.20" → 3.20.1, 3.21, 4)."""
    parts = [int(x) for x in number.split(".")]
    out = [number + ".1"]
    for k in range(len(parts), 0, -1):
        out.append(".".join(str(x) for x in [*parts[: k - 1], parts[k - 1] + 1]))
    return out


def render_toc(pages: list[list[Line]]) -> str:
    """Render TOC pages as a nested markdown list (page numbers dropped).

    The OCR of a TOC is messy: page numbers and dot leaders trail the titles, margin tab
    numbers ("4.5") leak in, page numbers are detached onto their own lines, and an
    entry's own number is sometimes detached ("orphan", e.g. ``4.9.4``) or glued to the
    wrong title. Numbers are therefore checked against the sequence: an entry's number
    must be a possible successor of the previous one (first child, next sibling, or an
    ancestor's next sibling); otherwise it is replaced by the first unused orphan number
    that fits. Nesting follows the number depth ("2.1.1" is three levels deep).
    """
    entries: list[list[str | None]] = []  # [number or None, title]
    orphans: list[str] = []
    for lines in pages:
        max_right = max((ln.right for ln in lines), default=0)
        for ln in lines:
            t = ln.text.strip()
            if _TOC_HEADING_RE.fullmatch(t):
                continue
            if _NUM_ONLY_RE.fullmatch(t):  # chapter number (left) or page number (right)
                if ln.left < 0.5 * max_right:
                    orphans.append(t)
                continue
            if _ORPHAN_NUMBERING_RE.fullmatch(t):
                orphans.append(t)
                continue
            t = re.sub(r"\s+\d\.\d{1,2}$", "", t)  # margin tab number
            t = re.sub(r"[\s.•·…]+$", "", t)
            t = re.sub(r"\s+\d{1,3}$", "", t)  # page number
            t = re.sub(r"[\s.•·…]+$", "", t)
            if not t:
                continue
            if _ORPHAN_NUMBERING_RE.fullmatch(t):  # detached number that had a page number
                orphans.append(t)
                continue
            m = _TOC_NUMBERED_RE.fullmatch(t)
            entries.append([m.group(1), m.group(2)] if m else [None, t])

    prev: str | None = None
    for i, entry in enumerate(entries):
        number = entry[0]
        if prev is None:
            if number:
                prev = number
            continue
        allowed = _successors(prev)
        if number not in allowed:
            number = next((o for o in orphans if o in allowed), number)
            if number is None:
                # No orphan fits: infer the next sibling, but only if the next numbered
                # entry confirms it (keeps genuinely unnumbered ones like "Schlusswort").
                nxt = next((e[0] for e in entries[i + 1:] if e[0]), None)
                guess = allowed[1]
                if nxt and (nxt == guess or nxt in _successors(guess)):
                    number = guess
            entry[0] = number
        if number:
            if number in orphans:
                orphans.remove(number)
            prev = number

    out = []
    for number, title in entries:
        depth = number.count(".") if number else 0
        out.append("  " * depth + "- " + (f"{number} {title}" if number else title))
    return "\n".join(out)


# --- Tables -----------------------------------------------------------------------
# Vision returns each table cell as its own box, so tables are found geometrically: runs
# of rows made of several short boxes. Prose never looks like that (one wide box per row,
# or long boxes in two-column layouts).

_NUMERIC_RE = re.compile(r"[−–+-]?\s?\d[\d.,]*\s?(?:€|%|EUR|Euro)?")
_MAX_CELL_CHARS = 30  # average cell length above this means prose columns, not a table


@dataclass
class Table:
    header: list[str]  # all empty when the table has no header row
    rows: list[list[str]]
    numeric: list[bool]  # per column: right-align

    @property
    def ncols(self) -> int:
        return len(self.numeric)

    @property
    def has_header(self) -> bool:
        return any(self.header)

    def render(self) -> str:
        def row(cells: list[str]) -> str:
            return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"

        sep = "| " + " | ".join("---:" if n else "---" for n in self.numeric) + " |"
        return "\n".join([row(self.header), sep, *(row(r) for r in self.rows)])


def _is_number(text: str) -> bool:
    return bool(_NUMERIC_RE.fullmatch(text.strip()))


def _is_table_row(ln: Line) -> bool:
    if len(ln.cells) < 2:
        return False
    return sum(len(c.text) for c in ln.cells) / len(ln.cells) <= _MAX_CELL_CHARS


def _overlap(a_left: float, a_right: float, b_left: float, b_right: float) -> float:
    return min(a_right, b_right) - max(a_left, b_left)


def _merge_split_rows(rows: list[tuple[list[str], bool]]) -> list[tuple[list[str], bool]]:
    """Rejoin one logical row that the OCR split in two (photo perspective makes the
    right-hand cells sit lower than the left-hand ones).

    Two consecutive multi-box rows are merged when their value columns are complementary
    (no column filled in both) and the union fills every column. Labels (column 0) are
    joined, so a wrapped label whose halves landed on different rows also works.
    """
    out: list[tuple[list[str], bool]] = []
    for cells, single in rows:
        if out and not single and not out[-1][1]:
            prev = out[-1][0]
            merged = [(prev[0] + " " + cells[0]).strip()] + [
                (a + b) if not (a and b) else None for a, b in zip(prev[1:], cells[1:], strict=True)
            ]
            if None not in merged and all(merged):
                out[-1] = (merged, False)  # type: ignore[assignment]
                continue
        out.append((cells, single))
    return out


def _build_table(block: list[Line]) -> Table | None:
    # Column bands: union of overlapping x-intervals of all cells in table rows
    # (headers are centered, numbers right-aligned, labels left-aligned, but they overlap).
    intervals = sorted((c.left, c.right) for ln in block for c in ln.cells)
    cols: list[list[float]] = []
    for left, right in intervals:
        if cols and left <= cols[-1][1]:
            cols[-1][1] = max(cols[-1][1], right)
        else:
            cols.append([left, right])
    if len(cols) < 2:
        return None

    def col_of(box: Line) -> int:
        return max(range(len(cols)), key=lambda i: _overlap(box.left, box.right, *cols[i]))

    rows: list[tuple[list[str], bool]] = []  # (cells per column, is single-box wrap row)
    for ln in block:
        cells = [""] * len(cols)
        boxes = ln.cells or [ln]
        for box in boxes:
            i = col_of(box)
            cells[i] = (cells[i] + " " + box.text).strip()
        rows.append((cells, len(boxes) == 1))

    rows = _merge_split_rows(rows)
    n_numbers = sum(_is_number(c) for cells, _ in rows for c in cells)
    if n_numbers < 2:
        return None  # text-only two-box rows (ISBN lines, label/value pairs) are not tables
    n_header = 0
    if n_numbers:
        while n_header < len(rows) and not rows[n_header][1] and not any(
            _is_number(c) for c in rows[n_header][0]
        ):
            n_header += 1
    else:
        n_header = 1
    header = [""] * len(cols)
    for cells, _ in rows[:n_header]:
        header = [(h + " " + c).strip() for h, c in zip(header, cells, strict=True)]

    body: list[list[str]] = []
    for cells, single in rows[n_header:]:
        if single and (body or n_header):
            target = body[-1] if body else header
            target[:] = [(t + " " + c).strip() for t, c in zip(target, cells, strict=True)]
        else:
            body.append(cells)
    if not body:
        return None
    numeric = []
    for i in range(len(cols)):
        vals = [r[i] for r in body if r[i]]
        numeric.append(bool(vals) and sum(_is_number(v) for v in vals) >= 0.6 * len(vals))
    return Table(header, body, numeric)


def find_tables(lines: list[Line]) -> list[Line | Table]:
    """Replace runs of table rows in a page's lines by :class:`Table` objects."""
    if not lines:
        return []
    med_h = statistics.median(ln.height for ln in lines)
    out: list[Line | Table] = []
    block: list[Line] = []

    def flush() -> None:
        if sum(1 for ln in block if len(ln.cells) >= 2) >= 2:
            table = _build_table(block)
            if table:
                out.append(table)
                block.clear()
                return
        out.extend(block)
        block.clear()

    for ln in lines:
        if block and ln.top - block[-1].bottom > 2 * med_h:
            flush()
        if _is_table_row(ln):
            block.append(ln)
        elif (
            block
            and not ln.cells
            and (
                _is_number(ln.text)  # a stray cell whose row grouping drifted
                or (
                    len(ln.text) <= 45
                    and ln.text[-1] not in ".!?:;"
                    and ln.left - min(b.left for b in block) <= 0.1 * (
                        max(b.right for b in block) - min(b.left for b in block)
                    )
                )  # wrapped row label ("Solidaritätszuschlag")
            )
        ):
            block.append(ln)
        else:
            flush()
            out.append(ln)
    flush()
    return out


def reflow(pages: list[list[Line]], tables: bool = True) -> str:
    """Turn per-photo lines into paragraphs separated by blank lines.

    With ``tables`` (default), runs of multi-box rows become markdown tables; a table at
    the top of a photo that continues one ending the previous photo is merged into it.
    """
    pages = _strip_page_furniture(pages)
    toc = find_toc_pages(pages)
    paragraphs: list[str | Table] = []
    carry = False  # last paragraph may continue on the next page
    for page_idx, lines in enumerate(pages):
        if toc and page_idx == toc[0]:
            paragraphs.append("## Inhaltsverzeichnis")
            paragraphs.append(render_toc([pages[i] for i in toc]))
            carry = False
        if page_idx in toc or not lines:
            continue
        med_h = statistics.median(ln.height for ln in lines)
        widest = max(ln.right - ln.left for ln in lines)
        cur: str | None = None
        prev: Line | None = None
        segments = find_tables(lines) if tables else lines
        for seg_idx, ln in enumerate(segments):
            if isinstance(ln, Table):
                if cur is not None:
                    paragraphs.append(cur)
                last = paragraphs[-1] if paragraphs else None
                if (seg_idx == 0 and isinstance(last, Table) and not ln.has_header
                        and ln.ncols == last.ncols):
                    last.rows.extend(ln.rows)  # table continues from the previous photo
                else:
                    paragraphs.append(ln)
                cur, prev, carry = None, None, False
                continue
            level = heading_level(ln.text)
            if level:
                if cur is not None:
                    paragraphs.append(cur)
                paragraphs.append("#" * level + " " + ln.text.strip())
                cur, prev, carry = None, None, False
                continue
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
        else:
            carry = False
    return "\n\n".join(p.render() if isinstance(p, Table) else p for p in paragraphs)


def build_markdown(
    title: str, names: list[str], pages: list[list[Line]], raw: bool = False, tables: bool = True
) -> str:
    """Assemble the markdown document for the photos (``names`` parallel to ``pages``)."""
    parts = [f"# {title}"]
    if raw:
        for name, lines in zip(names, pages, strict=True):
            parts.append(f"## {name}\n\n" + "\n".join(ln.text for ln in lines))
    else:
        parts.append(reflow(pages, tables=tables))
    return "\n\n".join(p for p in parts if p) + "\n"
