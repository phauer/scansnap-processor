"""Tests for batch re-OCR script."""

from unittest.mock import patch

import pytest

from re_ocr import main, mark_done, parse_list


class TestParseList:
    def test_parses_pending_entries(self, tmp_path):
        md = tmp_path / "list.md"
        md.write_text(
            "# Header\n\n"
            "- [ ] ./folder/doc1.pdf (3p)\n"
            "- [ ] ./doc2.pdf (1p)\n"
        )
        entries = parse_list(md)
        assert len(entries) == 2
        assert entries[0] == (2, "./folder/doc1.pdf", False, 3)
        assert entries[1] == (3, "./doc2.pdf", False, 1)

    def test_parses_done_entries(self, tmp_path):
        md = tmp_path / "list.md"
        md.write_text("- [x] ./done.pdf (2p)\n")
        entries = parse_list(md)
        assert len(entries) == 1
        assert entries[0] == (0, "./done.pdf", True, 2)

    def test_parses_mixed(self, tmp_path):
        md = tmp_path / "list.md"
        md.write_text(
            "- [x] ./done.pdf (2p)\n"
            "- [ ] ./pending.pdf (1p)\n"
        )
        entries = parse_list(md)
        assert entries[0][2] is True
        assert entries[1][2] is False

    def test_ignores_non_list_lines(self, tmp_path):
        md = tmp_path / "list.md"
        md.write_text(
            "# Header\n"
            "\n"
            "**Total: 2 files**\n"
            "\n"
            "- [ ] ./doc.pdf (1p)\n"
        )
        entries = parse_list(md)
        assert len(entries) == 1


class TestMarkDone:
    def test_marks_entry_as_done(self, tmp_path):
        md = tmp_path / "list.md"
        md.write_text(
            "# Header\n"
            "- [ ] ./doc1.pdf (3p)\n"
            "- [ ] ./doc2.pdf (1p)\n"
        )
        mark_done(md, 1)
        lines = md.read_text().splitlines()
        assert lines[1] == "- [x] ./doc1.pdf (3p)"
        assert lines[2] == "- [ ] ./doc2.pdf (1p)"

    def test_does_not_double_mark(self, tmp_path):
        md = tmp_path / "list.md"
        md.write_text("- [x] ./already.pdf (1p)\n")
        # mark_done on an already-done line shouldn't break it
        mark_done(md, 0)
        lines = md.read_text().splitlines()
        assert lines[0] == "- [x] ./already.pdf (1p)"


class TestReOcrIntegration:
    @pytest.mark.ocr
    def test_processes_and_marks_done(self, tmp_path, make_image_pdf):
        """Process files from a list, mark each as done."""
        docs = tmp_path / "Documents"
        docs.mkdir()

        import shutil
        pdf = make_image_pdf(["Hello World"], filename="test.pdf")
        shutil.copy2(pdf, docs / "test.pdf")

        md = tmp_path / "list.md"
        md.write_text(
            "# ScanSnap PDFs\n\n"
            "- [ ] ./test.pdf (1p)\n"
        )

        with patch("re_ocr.DOCS_DIR", docs), \
             patch("re_ocr.DEFAULT_LIST", md), \
             patch("sys.argv", ["re_ocr.py"]):
            main()

        # File should be marked done
        entries = parse_list(md)
        assert entries[0][2] is True

        # PDF should have text layer
        from scansnap_ocr.ocr import extract_text
        text = extract_text(str(docs / "test.pdf"))
        assert len(text.strip()) > 0

    def test_writes_before_after_log(self, tmp_path, make_image_pdf):
        """Processing a file writes before/after text to the diff log."""
        docs = tmp_path / "Documents"
        docs.mkdir()
        log = tmp_path / "diff.log"

        import shutil
        pdf = make_image_pdf(["Log Test Content"], filename="logtest.pdf")
        shutil.copy2(pdf, docs / "logtest.pdf")

        md = tmp_path / "list.md"
        md.write_text("- [ ] ./logtest.pdf (1p)\n")

        with patch("re_ocr.DOCS_DIR", docs), \
             patch("re_ocr.DEFAULT_LIST", md), \
             patch("re_ocr.LOG_FILE", log), \
             patch("sys.argv", ["re_ocr.py"]):
            main()

        assert log.exists()
        content = log.read_text()
        assert "logtest.pdf" in content
        assert "BEFORE" in content
        assert "AFTER" in content

    def test_resumes_from_last_position(self, tmp_path, make_image_pdf):
        """Already-done files are skipped on resume."""
        docs = tmp_path / "Documents"
        docs.mkdir()

        import shutil
        pdf = make_image_pdf(["Resume Test"], filename="pending.pdf")
        shutil.copy2(pdf, docs / "pending.pdf")

        md = tmp_path / "list.md"
        md.write_text(
            "- [x] ./already_done.pdf (2p)\n"
            "- [ ] ./pending.pdf (1p)\n"
        )

        with patch("re_ocr.DOCS_DIR", docs), \
             patch("re_ocr.DEFAULT_LIST", md), \
             patch("sys.argv", ["re_ocr.py"]):
            main()

        entries = parse_list(md)
        assert entries[0][2] is True  # was already done
        assert entries[1][2] is True  # now done too

    def test_skips_missing_files(self, tmp_path):
        """Missing files are marked done and reported."""
        docs = tmp_path / "Documents"
        docs.mkdir()

        md = tmp_path / "list.md"
        md.write_text("- [ ] ./nonexistent.pdf (1p)\n")

        with patch("re_ocr.DOCS_DIR", docs), \
             patch("re_ocr.DEFAULT_LIST", md), \
             patch("sys.argv", ["re_ocr.py"]):
            main()

        entries = parse_list(md)
        assert entries[0][2] is True  # marked done (skipped)

    def test_limit_stops_after_n(self, tmp_path):
        """--limit N only processes N files."""
        docs = tmp_path / "Documents"
        docs.mkdir()

        md = tmp_path / "list.md"
        md.write_text(
            "- [ ] ./a.pdf (1p)\n"
            "- [ ] ./b.pdf (1p)\n"
            "- [ ] ./c.pdf (1p)\n"
        )
        # Create all three files (but they'll fail OCR — that's fine,
        # we just want to check that only 2 are attempted)
        for name in ["a.pdf", "b.pdf", "c.pdf"]:
            (docs / name).write_bytes(b"not a pdf")

        # The invalid PDFs fail OCR, so main() exits non-zero after reporting them.
        with patch("re_ocr.DOCS_DIR", docs), \
             patch("re_ocr.DEFAULT_LIST", md), \
             patch("sys.argv", ["re_ocr.py", "-n", "2"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

        entries = parse_list(md)
        # Only the first two were attempted (errored, not marked done); the third
        # was never reached because of --limit.
        assert entries[2][2] is False  # c.pdf was never reached


class TestReOcrExitCode:
    def test_exits_nonzero_on_processing_error(self, tmp_path):
        """A file that fails OCR makes main() exit 1 (so cron/tee can detect it)."""
        docs = tmp_path / "Documents"
        docs.mkdir()
        (docs / "broken.pdf").write_bytes(b"not a pdf")

        md = tmp_path / "list.md"
        md.write_text("- [ ] ./broken.pdf (1p)\n")

        with patch("re_ocr.DOCS_DIR", docs), \
             patch("re_ocr.DEFAULT_LIST", md), \
             patch("sys.argv", ["re_ocr.py"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_missing_file_is_not_a_hard_error(self, tmp_path):
        """A file that no longer exists is a soft skip — no non-zero exit."""
        docs = tmp_path / "Documents"
        docs.mkdir()

        md = tmp_path / "list.md"
        md.write_text("- [ ] ./gone.pdf (1p)\n")

        with patch("re_ocr.DOCS_DIR", docs), \
             patch("re_ocr.DEFAULT_LIST", md), \
             patch("sys.argv", ["re_ocr.py"]):
            main()  # must not raise SystemExit

        assert parse_list(md)[0][2] is True  # still marked done

    def test_max_pages_skips_large_files(self, tmp_path, make_image_pdf):
        """--max-pages skips files with too many pages."""
        docs = tmp_path / "Documents"
        docs.mkdir()

        import shutil
        small = make_image_pdf(["Small"], filename="small.pdf")
        shutil.copy2(small, docs / "small.pdf")

        md = tmp_path / "list.md"
        md.write_text(
            "- [ ] ./small.pdf (1p)\n"
            "- [ ] ./large.pdf (20p)\n"
        )

        with patch("re_ocr.DOCS_DIR", docs), \
             patch("re_ocr.DEFAULT_LIST", md), \
             patch("sys.argv", ["re_ocr.py", "--max-pages", "5"]):
            main()

        entries = parse_list(md)
        assert entries[0][2] is True   # small processed
        assert entries[1][2] is False  # large skipped

    def test_all_done_nothing_to_do(self, tmp_path):
        """When all entries are done, prints nothing to do."""
        md = tmp_path / "list.md"
        md.write_text("- [x] ./done.pdf (1p)\n")

        with patch("re_ocr.DEFAULT_LIST", md), \
             patch("sys.argv", ["re_ocr.py"]):
            main()  # should not crash
