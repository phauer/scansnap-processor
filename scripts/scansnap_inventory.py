#!/usr/bin/env python3
"""Inventory all ScanSnap PDFs under a root and classify each by processing state.

State is read from PDF metadata:
- `creator` containing "ScanSnap"  → a ScanSnap-created scan (in scope)
- `producer` "scansnap-processor … (Engine)" → processed by this pipeline, and which engine

States: never (ScanSnap original, never processed), easyocr, apple_vision,
apple_livetext, processed_other (processed but unrecognized engine/version).

Writes a reviewable Markdown overview and prints a summary. Read-only — it does
not modify any PDF.

Usage:
    python scripts/scansnap_inventory.py [--root ~/Documents] [--out scansnap-inventory.md]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import fitz


def classify_state(creator: str, producer: str) -> str:
    """Classify a ScanSnap PDF by its metadata. Assumes the file is ScanSnap-created."""
    if "scansnap-processor" not in producer:
        return "never"
    if "AppleLiveText" in producer:
        return "apple_livetext"
    if "AppleVision" in producer:
        return "apple_vision"
    if "EasyOCR" in producer:
        return "easyocr"
    return "processed_other"


# Order for display + which states are "stale" (need re-OCR to reach Apple Vision).
STATE_ORDER = ["never", "easyocr", "processed_other", "apple_livetext", "apple_vision"]
STALE_STATES = {"never", "easyocr", "processed_other"}
STATE_LABEL = {
    "never": "Never processed (ScanSnap originals)",
    "easyocr": "Processed by old EasyOCR",
    "processed_other": "Processed (unrecognized engine/version)",
    "apple_livetext": "Processed with Apple Live Text",
    "apple_vision": "Processed with Apple Vision (current default)",
}


def scan(root: Path) -> list[dict]:
    """Walk `root`, return one record per ScanSnap-created PDF."""
    records: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(filenames):
            if not name.lower().endswith(".pdf"):
                continue
            path = os.path.join(dirpath, name)
            try:
                doc = fitz.open(path)
                creator = doc.metadata.get("creator", "") or ""
                producer = doc.metadata.get("producer", "") or ""
                pages = doc.page_count
                doc.close()
            except Exception:
                continue
            if "ScanSnap" not in creator:
                continue
            records.append({
                "rel": "./" + os.path.relpath(path, root),
                "pages": pages,
                "size": os.path.getsize(path),
                "state": classify_state(creator, producer),
                "producer": producer,
            })
    return records


def mb(n: int) -> float:
    return n / 1_000_000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(os.path.expanduser("~/Documents")))
    parser.add_argument("--out", type=Path, default=Path("scansnap-inventory.md"))
    args = parser.parse_args()

    records = scan(args.root)
    by_state: dict[str, list[dict]] = {s: [] for s in STATE_ORDER}
    for r in records:
        by_state.setdefault(r["state"], []).append(r)

    lines: list[str] = ["# ScanSnap PDF Inventory", ""]
    lines.append(f"Root: `{args.root}`")
    lines.append(f"**{len(records)} ScanSnap PDFs**, "
                 f"{sum(r['pages'] for r in records)} pages, "
                 f"{mb(sum(r['size'] for r in records)):.0f} MB total")
    lines.append("")

    # Summary table
    lines.append("## Summary by state")
    lines.append("")
    lines.append("| State | Files | Pages | Size |")
    lines.append("|---|---|---|---|")
    for s in STATE_ORDER:
        rs = by_state.get(s, [])
        if not rs:
            continue
        lines.append(f"| {STATE_LABEL[s]} | {len(rs)} | "
                     f"{sum(r['pages'] for r in rs)} | {mb(sum(r['size'] for r in rs)):.0f} MB |")

    # Re-OCR scope (stale states) + a page-size view of the "never" group.
    stale = [r for r in records if r["state"] in STALE_STATES]
    stale_pages = sum(r["pages"] for r in stale)
    lines.append("")
    lines.append("## Re-OCR scope (everything not already Apple Vision)")
    lines.append("")
    lo, hi = stale_pages / 60, stale_pages * 1.5 / 60
    lines.append(f"**{len(stale)} files / {stale_pages} pages.** "
                 f"At ~1s/page with Apple Vision ≈ **{lo:.0f}–{hi:.0f} min**.")
    never = by_state.get("never", [])
    big = [r for r in never if r["pages"] > 8]
    if big:
        lines.append("")
        lines.append(f"Of the never-processed files, **{len(big)} are >8 pages** "
                     f"({sum(r['pages'] for r in big)} pages) — these were skipped by the old "
                     f"`--max-pages 8` EasyOCR limit and are now cheap with Apple Vision.")

    # Detailed lists per state
    for s in STATE_ORDER:
        rs = by_state.get(s, [])
        if not rs:
            continue
        lines.append("")
        lines.append(f"## {STATE_LABEL[s]} ({len(rs)})")
        lines.append("")
        for r in sorted(rs, key=lambda r: (-r["pages"], r["rel"])):
            lines.append(f"- {r['rel']} ({r['pages']}p, {mb(r['size']):.1f} MB)")

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Console summary
    print(f"Scanned {args.root} → {len(records)} ScanSnap PDFs")
    for s in STATE_ORDER:
        rs = by_state.get(s, [])
        if rs:
            print(f"  {s:16} {len(rs):4} files  {sum(r['pages'] for r in rs):5} pages  "
                  f"{mb(sum(r['size'] for r in rs)):6.0f} MB")
    print(f"Re-OCR scope (not apple_vision): {len(stale)} files / {stale_pages} pages")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
