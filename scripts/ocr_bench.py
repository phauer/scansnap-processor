#!/usr/bin/env python3
"""Benchmark OCR engines on real German documents.

Reuses the methodology from OCR-Analysis.md: render each PDF page to 300 DPI,
run each engine, and record per-page wall-clock time and extracted text. Where a
document matches a known checkpoint set (umlauts, EUR amounts, IBANs, etc.), score
each engine on how many checkpoints it reproduced.

Usage:
    python scripts/ocr_bench.py DOC1.pdf DOC2.pdf ... \
        [--engines easyocr apple_vision] [--out OCR-Bench-Results.md] [--max-pages N] \
        [--checkpoints bench-checkpoints.json]

The PDF paths are passed explicitly so no personal-document paths are hardcoded.
Checkpoints live in a local, gitignored JSON file for the same reason — they are
strings from your own documents. See bench-checkpoints.example.json for the format.
Without a checkpoint file the benchmark still measures speed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import fitz

# Allow running as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scansnap_ocr.engines import get_engine  # noqa: E402
from scansnap_ocr.ocr import render_page_to_image  # noqa: E402

DEFAULT_CHECKPOINTS = Path(__file__).resolve().parent.parent / "bench-checkpoints.json"


def load_checkpoints(path: Path) -> dict[str, list[str]]:
    """Load accuracy checkpoints keyed by a substring of the filename.

    Each string should appear verbatim (case-insensitive) in a correct
    transcription — e.g. umlaut words, EUR amounts, IBANs, form fields. Returns an
    empty mapping when the file doesn't exist (speed-only benchmark).
    """
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(v, list) and all(isinstance(x, str) for x in v) for v in data.values()
    ):
        raise ValueError(f"{path}: expected an object mapping strings to string lists")
    return data


def checkpoints_for(filename: str, checkpoints: dict[str, list[str]]) -> list[str]:
    for key, expected in checkpoints.items():
        if key.lower() in filename.lower():
            return expected
    return []


def run_engine_on_pdf(engine, pdf_path: Path, max_pages: int | None):
    """Return (full_text, total_seconds, n_pages) for one engine on one PDF."""
    doc = fitz.open(str(pdf_path))
    n_pages = len(doc) if max_pages is None else min(len(doc), max_pages)
    texts: list[str] = []
    elapsed = 0.0
    for page_num in range(n_pages):
        image = render_page_to_image(doc[page_num])
        start = time.perf_counter()
        results = engine.recognize(image)
        elapsed += time.perf_counter() - start
        texts.append(" ".join(t for _bbox, t, _conf in results))
    doc.close()
    return "\n".join(texts), elapsed, n_pages


def score(text: str, expected: list[str]) -> tuple[int, int]:
    """Return (hits, total) of expected strings present (case-insensitive)."""
    if not expected:
        return (0, 0)
    lower = text.lower()
    hits = sum(1 for e in expected if e.lower() in lower)
    return (hits, len(expected))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDF files to benchmark")
    parser.add_argument(
        "--engines",
        nargs="+",
        default=["easyocr", "apple_vision"],
        help="Engine keys to compare (default: easyocr apple_vision)",
    )
    parser.add_argument("--out", type=Path, default=Path("OCR-Bench-Results.md"))
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument(
        "--checkpoints",
        type=Path,
        default=DEFAULT_CHECKPOINTS,
        help="JSON file with accuracy checkpoints (default: bench-checkpoints.json)",
    )
    args = parser.parse_args()
    checkpoints = load_checkpoints(args.checkpoints)
    if not checkpoints:
        print(f"NOTE: no checkpoints in {args.checkpoints} — measuring speed only",
              file=sys.stderr)

    pdfs = [p for p in args.pdfs if p.exists()]
    missing = [p for p in args.pdfs if not p.exists()]
    for p in missing:
        print(f"WARN: skipping missing file {p}", file=sys.stderr)
    if not pdfs:
        print("ERROR: no input PDFs exist", file=sys.stderr)
        return 1

    engines = {name: get_engine(name) for name in args.engines}

    lines: list[str] = ["# OCR Engine Benchmark", ""]
    # Aggregates per engine: total pages, total seconds, total hits, total checks.
    agg = {name: [0, 0.0, 0, 0] for name in args.engines}

    for pdf in pdfs:
        expected = checkpoints_for(pdf.name, checkpoints)
        lines.append(f"## {pdf.name}")
        lines.append("")
        lines.append("| Engine | Pages | Time | s/page | Checkpoints |")
        lines.append("|---|---|---|---|---|")
        for name, engine in engines.items():
            text, secs, pages = run_engine_on_pdf(engine, pdf, args.max_pages)
            hits, total = score(text, expected)
            per_page = secs / pages if pages else 0.0
            cp = f"{hits}/{total}" if total else "—"
            lines.append(
                f"| {engine.name} | {pages} | {secs:.1f}s | {per_page:.2f}s | {cp} |"
            )
            agg[name][0] += pages
            agg[name][1] += secs
            agg[name][2] += hits
            agg[name][3] += total
            print(f"{pdf.name} / {engine.name}: {pages}p {secs:.1f}s {cp}")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Engine | Total pages | Avg s/page | Checkpoints |")
    lines.append("|---|---|---|---|")
    for name in args.engines:
        pages, secs, hits, total = agg[name]
        per_page = secs / pages if pages else 0.0
        cp = f"{hits}/{total}" if total else "—"
        lines.append(
            f"| {engines[name].name} | {pages} | {per_page:.2f}s | {cp} |"
        )

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
