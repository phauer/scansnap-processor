#!/usr/bin/env python3
"""OCR + rename a new ScanSnap PDF."""

import argparse
import sys
import time
from pathlib import Path

from scansnap_ocr.config import NEW_SCAN_PATTERN, SCANSNAP_FOLDER
from scansnap_ocr.ocr import embed_text_layer, extract_text
from scansnap_ocr.title import (
    _parse_scan_date,
    extract_date,
    format_filename,
    generate_title,
    resolve_filename_conflict,
)


def is_new_scan(path: Path) -> bool:
    """Check if a file matches the new scan pattern (14 digits)."""
    return bool(NEW_SCAN_PATTERN.match(path.name))


def find_unprocessed_scans(folder: Path) -> list[Path]:
    """Find all unprocessed new scans in the folder (root only)."""
    return sorted(
        p for p in folder.glob("*.pdf")
        if is_new_scan(p)
    )


def process_pdf(pdf_path: Path) -> Path:
    """OCR a PDF and rename it. Returns the new path."""
    print(f"Processing: {pdf_path.name}")

    # Step 1: OCR
    start = time.time()
    stats = embed_text_layer(str(pdf_path))
    ocr_time = time.time() - start
    print(f"  OCR: {stats['pages']} pages, {stats['total_texts']} text blocks, {ocr_time:.1f}s")

    # Step 2: Extract text and generate title
    text = extract_text(str(pdf_path))
    doc_date = extract_date(text, pdf_path.name)
    title = generate_title(text)

    if doc_date is None:
        # Last resort: use scan date from filename, or today
        doc_date = _parse_scan_date(pdf_path.name)
        if doc_date is None:
            from datetime import date
            doc_date = date.today()

    # Step 3: Rename
    new_name = format_filename(doc_date, title)
    new_name = resolve_filename_conflict(pdf_path.parent, new_name)
    new_path = pdf_path.parent / new_name

    pdf_path.rename(new_path)
    print(f"  Renamed: {pdf_path.name} → {new_name}")

    return new_path


def main():
    parser = argparse.ArgumentParser(description="OCR + rename new ScanSnap PDFs")
    parser.add_argument("path", nargs="?", type=Path, help="Path to a specific PDF to process")
    parser.add_argument("--folder", type=Path, default=SCANSNAP_FOLDER, help="ScanSnap folder")
    args = parser.parse_args()

    if args.path:
        # Process a specific file
        pdf_path = args.path.resolve()
        if not pdf_path.exists():
            print(f"Error: File not found: {pdf_path}", file=sys.stderr)
            sys.exit(1)
        process_pdf(pdf_path)
    else:
        # Process all unprocessed scans
        folder = args.folder
        if not folder.exists():
            print(f"Error: Folder not found: {folder}", file=sys.stderr)
            sys.exit(1)

        scans = find_unprocessed_scans(folder)
        if not scans:
            print("No unprocessed scans found.")
            return

        print(f"Found {len(scans)} unprocessed scan(s)")
        failures = []
        for pdf in scans:
            try:
                process_pdf(pdf)
            except Exception as e:
                print(f"  Error processing {pdf.name}: {e}", file=sys.stderr)
                failures.append(pdf.name)

        if failures:
            print(
                f"Done. {len(scans) - len(failures)}/{len(scans)} processed, "
                f"{len(failures)} failed.",
                file=sys.stderr,
            )
            # Signal failure so callers (cron / a supervising daemon) can detect it.
            sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
