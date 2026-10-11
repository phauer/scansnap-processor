#!/usr/bin/env python3
"""Batch re-OCR ScanSnap PDFs listed in scansnap-pdfs.md.

Uses the markdown file as both input and progress tracker.
Marks each file as done after processing, so the script can be
aborted and resumed at any time.
"""

import argparse
import re
import sys
import time
from pathlib import Path

import fitz

from scansnap_ocr.config import DOCS_DIR
from scansnap_ocr.ocr import embed_text_layer

DEFAULT_LIST = Path(__file__).parent / "scansnap-pdfs.md"
LOG_FILE = Path(__file__).parent / "logs" / "re_ocr_diff.log"

# Matches lines like "- [ ] ./path/to/file.pdf (3p)" or "- [x] ./path/to/file.pdf (3p)"
LINE_PATTERN = re.compile(r"^- \[([ x])\] (\./.*\.pdf) \((\d+)p\)$")


def parse_list(list_path: Path) -> list[tuple[int, str, bool, int]]:
    """Parse the markdown file. Returns (line_index, rel_path, is_done, pages) tuples."""
    lines = list_path.read_text().splitlines()
    entries = []
    for i, line in enumerate(lines):
        m = LINE_PATTERN.match(line)
        if m:
            done = m.group(1) == "x"
            rel_path = m.group(2)
            pages = int(m.group(3))
            entries.append((i, rel_path, done, pages))
    return entries


def read_first_page_text(pdf_path: Path) -> str:
    """Extract text from the first page of a PDF."""
    try:
        doc = fitz.open(str(pdf_path))
        text = doc[0].get_text().strip() if len(doc) > 0 else ""
        doc.close()
        return text
    except Exception:
        return "(could not read)"


def log_diff(log_path: Path, rel_path: str, before: str, after: str, elapsed: float) -> None:
    """Append a before/after text comparison to the log file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(f"{'=' * 80}\n")
        f.write(f"FILE: {rel_path}\n")
        f.write(f"TIME: {elapsed:.1f}s\n")
        f.write(f"{'-' * 40} BEFORE {'-' * 33}\n")
        f.write(before or "(no text)")
        f.write(f"\n{'-' * 40} AFTER {'-' * 34}\n")
        f.write(after or "(no text)")
        f.write("\n\n")


def mark_done(list_path: Path, line_index: int) -> None:
    """Mark a single line as done by prepending [x]."""
    lines = list_path.read_text().splitlines()
    line = lines[line_index]
    lines[line_index] = line.replace("- [ ] ./", "- [x] ./", 1)
    list_path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Batch re-OCR ScanSnap PDFs from a list")
    parser.add_argument("list_file", nargs="?", type=Path, default=DEFAULT_LIST,
                        help="Markdown file with PDF list (default: scansnap-pdfs.md)")
    parser.add_argument("-n", "--limit", type=int, default=None,
                        help="Only process this many files, then stop")
    parser.add_argument("--max-pages", type=int, default=8,
                        help="Skip PDFs with more than this many pages (default: 8)")
    args = parser.parse_args()

    list_path = args.list_file

    if not list_path.exists():
        print(f"Error: {list_path} not found", file=sys.stderr)
        sys.exit(1)

    entries = parse_list(list_path)
    pending = [(i, p, pages) for i, p, done, pages in entries if not done]
    total = len(entries)
    already_done = total - len(pending)

    skipped_large = [(i, p, pages) for i, p, pages in pending if pages > args.max_pages]
    pending = [(i, p, pages) for i, p, pages in pending if pages <= args.max_pages]
    if skipped_large:
        print(f"Skipping {len(skipped_large)} files with >{args.max_pages} pages")

    if args.limit is not None:
        pending = pending[:args.limit]

    if already_done > 0:
        remaining = total - already_done
        print(f"Resuming: {already_done}/{total} already done, "
              f"processing {len(pending)} of {remaining} remaining")
    else:
        print(f"Processing {len(pending)} of {total} files")

    if not pending:
        print("Nothing to do.")
        return

    errors = []       # genuine processing failures (signal a non-zero exit)
    missing = []      # files no longer on disk — an expected "moved/renamed" skip
    for idx, (line_index, rel_path, _pages) in enumerate(pending):
        pdf_path = DOCS_DIR / rel_path
        progress = f"[{already_done + idx + 1}/{total}]"

        if not pdf_path.exists():
            print(f"  {progress} SKIP (not found): {rel_path}")
            missing.append(rel_path)
            mark_done(list_path, line_index)
            continue

        before_text = read_first_page_text(pdf_path)

        start = time.time()
        try:
            stats = embed_text_layer(str(pdf_path))
            elapsed = time.time() - start

            after_text = read_first_page_text(pdf_path)
            log_diff(LOG_FILE, rel_path, before_text, after_text, elapsed)

            print(
                f"  {progress} {rel_path}: "
                f"{stats['pages']}p, {stats['total_texts']} texts, {elapsed:.1f}s"
            )
            mark_done(list_path, line_index)
        except Exception as e:
            elapsed = time.time() - start
            print(f"  {progress} ERROR {rel_path}: {e} ({elapsed:.1f}s)")
            errors.append((rel_path, str(e)))

    done_count = already_done + len(pending) - len(errors)
    print(f"\nDone. {done_count}/{total} files processed.")
    if missing:
        print(f"{len(missing)} missing (skipped): " + ", ".join(missing))
    if errors:
        print(f"\n{len(errors)} errors:")
        for path, err in errors:
            print(f"  {path}: {err}")
        # Signal failure so callers (run-re-ocr.sh / cron) can detect it.
        sys.exit(1)


if __name__ == "__main__":
    main()
