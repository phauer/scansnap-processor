"""Tests for date extraction and title generation."""

from datetime import date

import scansnap_ocr.title as title_module
from scansnap_ocr.title import (
    _sanitize_title,
    extract_date,
    format_filename,
    generate_title,
    heuristic_title,
    resolve_filename_conflict,
)


class TestExtractDate:
    def test_extract_date_dd_mm_yyyy(self):
        text = "Datum: 17.03.2026\nSehr geehrte Damen und Herren"
        result = extract_date(text)
        assert result == date(2026, 3, 17)

    def test_extract_date_dd_mm_yy(self):
        text = "Berlin, 17.03.26\nBetreff: Ihre Anfrage"
        result = extract_date(text)
        assert result == date(2026, 3, 17)

    def test_extract_date_written_month(self):
        text = "München, den 17. März 2026\nRechnung Nr. 12345"
        result = extract_date(text)
        assert result == date(2026, 3, 17)

    def test_extract_date_prefers_top_of_page(self):
        text = "Datum: 17.03.2026\nText\nMore text\nAnother date: 01.01.2025"
        result = extract_date(text)
        assert result == date(2026, 3, 17)

    def test_extract_date_fallback_to_scan_date(self):
        text = "No dates in this document at all"
        result = extract_date(text, scan_filename="20260328111052.pdf")
        assert result == date(2026, 3, 28)

    def test_extract_date_no_date_no_filename(self):
        text = "No dates here"
        result = extract_date(text)
        assert result is None

    def test_extract_date_ignores_unreasonable_dates(self):
        text = "Datum: 01.01.1800\nAnother: 15.06.2025"
        result = extract_date(text)
        assert result == date(2025, 6, 15)

    def test_extract_date_single_digit_day(self):
        text = "Am 5.03.2026 wurde Ihr Antrag bearbeitet"
        result = extract_date(text)
        assert result == date(2026, 3, 5)


class TestHeuristicTitle:
    def test_heuristic_title_invoice(self):
        text = "DSL Bank GmbH\nRechnung Nr. 12345\nSehr geehrter Herr Mustermann"
        title = heuristic_title(text)
        assert "DSL Bank" in title or "Rechnung" in title

    def test_heuristic_title_fine(self):
        text = "Stadt Hameln\nBußgeldbescheid\nAktenzeichen: 123/456"
        title = heuristic_title(text)
        assert "Hameln" in title or "Bußgeldbescheid" in title

    def test_heuristic_title_with_company_suffix(self):
        text = "Allianz Versicherungs AG\nVersicherungsschein\nVertragsnummer"
        title = heuristic_title(text)
        assert "Allianz" in title

    def test_heuristic_title_fallback(self):
        text = ""
        title = heuristic_title(text)
        assert title == "Scan"

    def test_heuristic_title_fallback_whitespace(self):
        title = heuristic_title("   \n\n  ")
        assert title == "Scan"

    def test_heuristic_title_sanitizes_filename(self):
        text = "Sender/Company\nRechnung: Produkt"
        title = heuristic_title(text)
        assert "/" not in title
        assert ":" not in title
        assert "\\" not in title

    def test_heuristic_title_caps_length(self):
        text = ("Bayerische Landesbank für Wirtschaft und Finanzen GmbH\n"
                "Rechnung über die Erbringung von Dienstleistungen")
        title = heuristic_title(text)
        words = title.split()
        assert len(words) <= 6

    def test_heuristic_title_with_context(self):
        text = "Deutsche Bank AG\nMitteilung\nMandatsreferenz: ABC123"
        title = heuristic_title(text)
        # Should include sender, doc type, and possibly context
        assert "Deutsche Bank" in title or "Mitteilung" in title


class TestGenerateTitleDispatch:
    """generate_title() dispatches to the LLM and falls back to the heuristic.

    The LLM is mocked so these stay fast and never load a model.
    """

    def test_uses_llm_result_when_available(self, monkeypatch):
        # generate_title imports generate_llm_title lazily from llm_titler, so
        # patching it there is what generate_title sees.
        monkeypatch.setattr(title_module, "TITLE_ENGINE", "llm")
        import scansnap_ocr.llm_titler as titler_module
        monkeypatch.setattr(titler_module, "generate_llm_title",
                            lambda text: "IKEA Rechnung Kallax")
        assert generate_title("IKEA Deutschland GmbH Rechnung") == "IKEA Rechnung Kallax"

    def test_falls_back_to_heuristic_when_llm_returns_none(self, monkeypatch):
        monkeypatch.setattr(title_module, "TITLE_ENGINE", "llm")
        import scansnap_ocr.llm_titler as titler_module
        monkeypatch.setattr(titler_module, "generate_llm_title", lambda text: None)
        text = "Stadt Hameln\nBußgeldbescheid\nAktenzeichen: 123/456"
        result = generate_title(text)
        assert result == heuristic_title(text)
        assert "Hameln" in result or "Bußgeldbescheid" in result

    def test_heuristic_engine_skips_llm(self, monkeypatch):
        monkeypatch.setattr(title_module, "TITLE_ENGINE", "heuristic")
        import scansnap_ocr.llm_titler as titler_module

        def _boom(text):
            raise AssertionError("LLM should not be called in heuristic mode")

        monkeypatch.setattr(titler_module, "generate_llm_title", _boom)
        text = "DSL Bank GmbH\nRechnung Nr. 12345"
        assert generate_title(text) == heuristic_title(text)


class TestFormatFilename:
    def test_format_filename(self):
        result = format_filename(date(2026, 3, 17), "DSL Bank Mitteilung Mandatsreferenz")
        assert result == "260317 DSL Bank Mitteilung Mandatsreferenz.pdf"

    def test_format_filename_short_title(self):
        result = format_filename(date(2025, 4, 2), "Scan")
        assert result == "250402 Scan.pdf"


class TestResolveFilenameConflict:
    def test_no_conflict(self, tmp_path):
        result = resolve_filename_conflict(tmp_path, "260317 Test.pdf")
        assert result == "260317 Test.pdf"

    def test_format_filename_conflict(self, tmp_path):
        (tmp_path / "260317 Test.pdf").touch()
        result = resolve_filename_conflict(tmp_path, "260317 Test.pdf")
        assert result == "260317 Test_001.pdf"

    def test_multiple_conflicts(self, tmp_path):
        (tmp_path / "260317 Test.pdf").touch()
        (tmp_path / "260317 Test_001.pdf").touch()
        result = resolve_filename_conflict(tmp_path, "260317 Test.pdf")
        assert result == "260317 Test_002.pdf"


class TestSanitizeTitle:
    def test_removes_slashes(self):
        assert "/" not in _sanitize_title("Test/Title")

    def test_removes_backslashes(self):
        assert "\\" not in _sanitize_title("Test\\Title")

    def test_removes_colons(self):
        assert ":" not in _sanitize_title("Test: Title")

    def test_collapses_spaces(self):
        result = _sanitize_title("Too   many    spaces")
        assert "  " not in result
