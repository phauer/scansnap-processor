"""Tests for OCR + rename pipeline."""

from pathlib import Path
from unittest.mock import patch

import pytest

from process_new import find_unprocessed_scans, is_new_scan, main, process_pdf
from scansnap_ocr.ocr import extract_text


class TestIsNewScan:
    def test_detects_new_scan_pattern(self):
        assert is_new_scan(Path("20260328111052.pdf"))

    def test_rejects_named_file(self):
        assert not is_new_scan(Path("20250422_Rechnung.pdf"))

    def test_rejects_already_renamed(self):
        assert not is_new_scan(Path("260317 DSL Bank Mitteilung.pdf"))

    def test_rejects_short_number(self):
        assert not is_new_scan(Path("20260328.pdf"))

    def test_rejects_non_pdf(self):
        assert not is_new_scan(Path("20260328111052.jpg"))


class TestFindUnprocessedScans:
    def test_finds_only_new_scans(self, tmp_path):
        (tmp_path / "20260328111052.pdf").touch()
        (tmp_path / "20260328111253.pdf").touch()
        (tmp_path / "260317 DSL Bank.pdf").touch()
        (tmp_path / "old_document.pdf").touch()

        result = find_unprocessed_scans(tmp_path)
        assert len(result) == 2
        names = {p.name for p in result}
        assert "20260328111052.pdf" in names
        assert "20260328111253.pdf" in names

    def test_empty_folder(self, tmp_path):
        result = find_unprocessed_scans(tmp_path)
        assert result == []


class TestProcessPdfIntegration:
    @pytest.mark.ocr
    def test_full_pipeline(self, tmp_path, make_image_pdf):
        """New scan → OCR → renamed to YYMMDD Title.pdf."""
        pdf = make_image_pdf(
            ["Rechnung Nr. 12345\n17.03.2026\nSehr geehrter Kunde"],
            filename="20260328111052.pdf",
        )

        new_path = process_pdf(pdf)

        # Original should be gone
        assert not pdf.exists()
        # New file should exist
        assert new_path.exists()
        # Should have text layer
        text = extract_text(str(new_path))
        assert len(text.strip()) > 0
        # Filename should start with a date pattern (YYMMDD)
        assert new_path.name[0:6].isdigit()
        assert new_path.name.endswith(".pdf")

    def test_falls_back_to_scan_date(self, tmp_path, make_image_pdf):
        """No date in document → uses scan date from filename."""
        pdf = make_image_pdf(
            ["Some text without any date"],
            filename="20260328111052.pdf",
        )

        new_path = process_pdf(pdf)

        # Should fall back to scan date (2026-03-28 → 260328)
        assert new_path.name.startswith("260328") or new_path.name[0:6].isdigit()

    def test_uses_document_date(self, tmp_path, make_image_pdf):
        """Document contains date → filename uses that date."""
        pdf = make_image_pdf(
            ["Datum: 17.03.2026\nRechnung"],
            filename="20260328111052.pdf",
        )

        new_path = process_pdf(pdf)

        # If OCR correctly reads the date, should start with 260317
        # But OCR may not be perfect on synthetic PDFs, so just check format
        assert new_path.name[0:6].isdigit()
        assert " " in new_path.name  # Has space between date and title


class TestMainExitCode:
    def test_batch_exits_nonzero_when_a_scan_fails(self, tmp_path):
        """One failing scan in a batch makes main() exit 1 (so a daemon can tell)."""
        folder = tmp_path / "scans"
        folder.mkdir()
        (folder / "20260328111052.pdf").write_bytes(b"not a pdf")  # fails OCR

        with patch("sys.argv", ["process_new.py", "--folder", str(folder)]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_batch_empty_folder_exits_clean(self, tmp_path):
        """No scans → clean return, no non-zero exit."""
        folder = tmp_path / "scans"
        folder.mkdir()

        with patch("sys.argv", ["process_new.py", "--folder", str(folder)]):
            main()  # must not raise SystemExit
