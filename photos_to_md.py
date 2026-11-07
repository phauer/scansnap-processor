#!/usr/bin/env python3
"""OCR a folder of photos (HEIC, JPG, PNG) into a single markdown file."""

import argparse
import sys
from pathlib import Path

from tqdm import tqdm

from scansnap_ocr.photos import build_markdown, list_photos, load_image, ocr_photo


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OCR a folder of photos into one markdown file")
    parser.add_argument("folder", type=Path, help="Folder with photos")
    parser.add_argument("-o", "--output", type=Path,
                        help="Output file (default: <folder>/<foldername>.md)")
    parser.add_argument("--raw", action="store_true",
                        help="Keep OCR line breaks, one '## <photo>' section per photo")
    args = parser.parse_args(argv)

    folder = args.folder.expanduser().resolve()
    if not folder.is_dir():
        print(f"Error: Folder not found: {folder}", file=sys.stderr)
        return 1
    photos = list_photos(folder)
    if not photos:
        print(f"Error: No photos found in {folder}", file=sys.stderr)
        return 1

    names, pages, failures = [], [], []
    for photo in tqdm(photos, desc="OCR", unit="photo"):
        try:
            pages.append(ocr_photo(load_image(photo)))
            names.append(photo.name)
        except Exception as e:
            print(f"  Error processing {photo.name}: {e}", file=sys.stderr)
            failures.append(photo.name)

    output = args.output or folder / f"{folder.name}.md"
    output.write_text(build_markdown(folder.name, names, pages, raw=args.raw), encoding="utf-8")
    print(f"Wrote {output} ({len(pages)}/{len(photos)} photos)")
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
