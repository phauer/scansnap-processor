"""Tests for folder watcher."""

from unittest.mock import MagicMock, patch

from watcher import ScanHandler


class TestScanHandler:
    def test_triggers_on_new_pdf(self, tmp_path):
        """New scan-pattern PDF triggers processing."""
        handler = ScanHandler()
        pdf_path = tmp_path / "20260328111052.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content for size > 0")

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(pdf_path)

        with patch.object(handler, "_wait_for_stable", return_value=True), \
             patch("watcher.process_pdf") as mock_process, \
             patch("watcher.SCANSNAP_FOLDER", tmp_path):
            handler.on_created(event)
            mock_process.assert_called_once_with(pdf_path)

    def test_ignores_non_pdf(self, tmp_path):
        """Non-PDF files are ignored."""
        handler = ScanHandler()
        jpg_path = tmp_path / "20260328111052.jpg"
        jpg_path.touch()

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(jpg_path)

        with patch("watcher.process_pdf") as mock_process, \
             patch("watcher.SCANSNAP_FOLDER", tmp_path):
            handler.on_created(event)
            mock_process.assert_not_called()

    def test_ignores_existing_named_files(self, tmp_path):
        """Already-named files (not matching scan pattern) are ignored."""
        handler = ScanHandler()
        pdf_path = tmp_path / "260317 DSL Bank.pdf"
        pdf_path.touch()

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(pdf_path)

        with patch("watcher.process_pdf") as mock_process, \
             patch("watcher.SCANSNAP_FOLDER", tmp_path):
            handler.on_created(event)
            mock_process.assert_not_called()

    def test_ignores_directories(self, tmp_path):
        """Directory creation events are ignored."""
        handler = ScanHandler()
        event = MagicMock()
        event.is_directory = True
        event.src_path = str(tmp_path / "subdir")

        with patch("watcher.process_pdf") as mock_process:
            handler.on_created(event)
            mock_process.assert_not_called()

    def test_ignores_subdirectory_files(self, tmp_path):
        """Files in subdirectories are ignored (root folder only)."""
        handler = ScanHandler()
        subdir = tmp_path / "archive"
        subdir.mkdir()
        pdf_path = subdir / "20260328111052.pdf"
        pdf_path.touch()

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(pdf_path)

        with patch("watcher.process_pdf") as mock_process, \
             patch("watcher.SCANSNAP_FOLDER", tmp_path):
            handler.on_created(event)
            mock_process.assert_not_called()


class TestWaitForStable:
    def test_waits_for_stable_filesize(self, tmp_path):
        """File that is immediately stable returns True."""
        handler = ScanHandler()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 some content here")

        with patch("watcher.WATCHER_SETTLE_TIME", 0.3), \
             patch("watcher.WATCHER_SIZE_CHECK_INTERVAL", 0.1):
            result = handler._wait_for_stable(pdf_path, timeout=5.0)
        assert result is True

    def test_returns_false_for_missing_file(self, tmp_path):
        """Missing file returns False immediately."""
        handler = ScanHandler()
        result = handler._wait_for_stable(tmp_path / "nonexistent.pdf", timeout=1.0)
        assert result is False
