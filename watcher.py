#!/usr/bin/env python3
"""Folder watcher daemon: auto-processes new ScanSnap PDFs."""

import logging
import subprocess
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from process_new import process_pdf
from scansnap_ocr.config import (
    LOG_DIR,
    NEW_SCAN_PATTERN,
    SCANSNAP_FOLDER,
    WATCHER_SETTLE_TIME,
    WATCHER_SIZE_CHECK_INTERVAL,
)

LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "watcher.log"),
    ],
)
log = logging.getLogger(__name__)


NOTIFIER = "/opt/homebrew/bin/terminal-notifier"


def notify(title: str, message: str, reveal_path: Path | None = None) -> None:
    """Send a macOS notification. Clicking opens Finder to reveal_path if given."""
    try:
        cmd = [NOTIFIER, "-title", title, "-message", message]
        if reveal_path:
            cmd += ["-execute", f'open -R "{reveal_path}"']
        subprocess.Popen(cmd)
    except Exception:
        log.debug("Failed to send notification", exc_info=True)


class ScanHandler(FileSystemEventHandler):
    """Handles new PDF files appearing in the ScanSnap folder."""

    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)

        # Only process PDFs in the root folder (not subdirectories)
        if path.parent != SCANSNAP_FOLDER:
            return

        # Only process .pdf files
        if path.suffix.lower() != ".pdf":
            log.debug(f"Ignoring non-PDF: {path.name}")
            return

        # Only process new scan pattern
        if not NEW_SCAN_PATTERN.match(path.name):
            log.debug(f"Ignoring non-scan file: {path.name}")
            return

        log.info(f"New scan detected: {path.name}")
        notify("ScanSnap OCR", f"Processing {path.name}…")

        # Wait for file to stabilize (ScanSnap may still be writing)
        if not self._wait_for_stable(path):
            log.warning(f"File never stabilized, skipping: {path.name}")
            return

        # Process the file
        try:
            new_path = process_pdf(path)
            log.info(f"Processed: {path.name} → {new_path.name}")
            notify("ScanSnap OCR", f"Done → {new_path.name}", reveal_path=new_path)
        except Exception as e:
            log.error(f"Error processing {path.name}: {e}", exc_info=True)

    def _wait_for_stable(self, path: Path, timeout: float = 30.0) -> bool:
        """Wait until a file's size is stable (not being written to)."""
        if not path.exists():
            return False

        elapsed = 0.0
        last_size = -1
        stable_time = 0.0

        while elapsed < timeout:
            try:
                current_size = path.stat().st_size
            except OSError:
                return False

            if current_size == last_size and current_size > 0:
                stable_time += WATCHER_SIZE_CHECK_INTERVAL
                if stable_time >= WATCHER_SETTLE_TIME:
                    return True
            else:
                stable_time = 0.0
                last_size = current_size

            time.sleep(WATCHER_SIZE_CHECK_INTERVAL)
            elapsed += WATCHER_SIZE_CHECK_INTERVAL

        return False


def main():
    folder = SCANSNAP_FOLDER
    if not folder.exists():
        log.error(f"ScanSnap folder not found: {folder}")
        sys.exit(1)

    log.info(f"Watching: {folder}")
    handler = ScanHandler()
    observer = Observer()
    observer.schedule(handler, str(folder), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopping watcher...")
        observer.stop()
    observer.join()
    log.info("Watcher stopped.")


if __name__ == "__main__":
    main()
