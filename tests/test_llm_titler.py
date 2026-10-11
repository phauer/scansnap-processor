"""Tests for the local LLM titler's pure helpers (no model loaded).

The model-backed path (LlmTitler.title / generate_llm_title) is exercised
end-to-end only when SCANSNAP_TEST_LLM=1 is set, to keep the default suite fast
and offline.
"""

import os

import pytest

from scansnap_ocr.config import TITLE_LLM_MAX_CHARS
from scansnap_ocr.llm_titler import (
    LlmTitler,
    build_messages,
    clean_llm_title,
    generate_llm_title,
)


class TestCleanLlmTitle:
    def test_empty_and_whitespace(self):
        assert clean_llm_title("") == ""
        assert clean_llm_title("   \n  ") == ""

    def test_plain_title_passthrough(self):
        assert clean_llm_title("IKEA Rechnung Kallax") == "IKEA Rechnung Kallax"

    def test_takes_first_line_only(self):
        assert clean_llm_title("Stadt Hameln Bescheid\nnoch mehr Text") == "Stadt Hameln Bescheid"

    def test_strips_label_prefix(self):
        assert clean_llm_title("Titel: IKEA Rechnung") == "IKEA Rechnung"
        assert clean_llm_title("Dateiname - AOK Bescheid") == "AOK Bescheid"

    def test_strips_quotes(self):
        assert clean_llm_title('"IKEA Rechnung"') == "IKEA Rechnung"
        assert clean_llm_title("“AOK Bescheid”") == "AOK Bescheid"

    def test_underscores_become_spaces(self):
        assert clean_llm_title("ikea_rechnung_kallax") == "ikea rechnung kallax"

    def test_splits_long_camelcase(self):
        assert clean_llm_title("Firma MeningokokkenRechnung") == "Firma Meningokokken Rechnung"

    def test_preserves_short_forms_like_gmbh(self):
        # "GmbH"/"AG" must not be split into "Gmb H" / "A G".
        assert clean_llm_title("IKEA Deutschland GmbH Rechnung") == "IKEA Deutschland GmbH Rechnung"
        assert clean_llm_title("Rheinland Immobilien AG Rechnung") == "Rheinland Immobilien AG Rechnung"

    def test_removes_filesystem_unsafe_chars(self):
        cleaned = clean_llm_title("Sender/Firma: Rechnung*?")
        for ch in '/:*?<>"\\|':
            assert ch not in cleaned

    def test_collapses_whitespace(self):
        assert clean_llm_title("Too   many    spaces") == "Too many spaces"

    def test_caps_word_count(self):
        raw = "eins zwei drei vier fuenf sechs sieben acht neun zehn"
        assert len(clean_llm_title(raw, max_words=8).split()) == 8

    def test_strips_trailing_punctuation(self):
        assert clean_llm_title("IKEA Rechnung Kallax.") == "IKEA Rechnung Kallax"

    def test_collapses_adjacent_duplicate_words(self):
        assert clean_llm_title("NÜRNBERGER Antrag Versicherung Firma Firma") == \
            "NÜRNBERGER Antrag Versicherung Firma"
        assert clean_llm_title("Makler Makler Rheinland") == "Makler Rheinland"

    def test_keeps_nonadjacent_repeats(self):
        # meaningful repeats that aren't adjacent are preserved
        assert clean_llm_title("Static Typing Dynamic Typing") == "Static Typing Dynamic Typing"

    def test_drops_configured_noise_words(self):
        # recipient surname is stripped (case-insensitive) but first names stay
        assert clean_llm_title(
            "Techniker Krankenkasse Meldebescheinigung Mustermann Erika", drop_words=["Mustermann"]
        ) == "Techniker Krankenkasse Meldebescheinigung Erika"
        assert clean_llm_title("NÜRNBERGER Antrag mustermann", drop_words=["Mustermann"]) == \
            "NÜRNBERGER Antrag"

    def test_no_drop_words_keeps_everything(self):
        assert clean_llm_title("Firma Rechnung Mustermann", drop_words=[]) == "Firma Rechnung Mustermann"


class TestBuildMessages:
    def test_structure_system_fewshot_user(self):
        messages = build_messages("Meine Firma GmbH Rechnung")
        assert messages[0]["role"] == "system"
        # few-shot pairs alternate user/assistant, then a final user turn
        assert messages[-1]["role"] == "user"
        assert "Meine Firma GmbH Rechnung" in messages[-1]["content"]
        roles = [m["role"] for m in messages]
        assert roles.count("assistant") >= 1  # at least one few-shot answer

    def test_truncates_long_text(self):
        long_text = "A" * (TITLE_LLM_MAX_CHARS + 500)
        messages = build_messages(long_text)
        # user content includes the wrapper plus at most MAX_CHARS of the doc text
        assert messages[-1]["content"].count("A") <= TITLE_LLM_MAX_CHARS


class TestGenerateLlmTitleGraceful:
    def test_returns_none_on_titler_error(self, monkeypatch):
        import scansnap_ocr.llm_titler as mod

        class Boom:
            def title(self, text):
                raise RuntimeError("model missing")

        monkeypatch.setattr(mod, "_titler", Boom())
        assert generate_llm_title("some text") is None

    def test_returns_none_on_import_error(self, monkeypatch):
        import scansnap_ocr.llm_titler as mod

        class NoMlx:
            def title(self, text):
                raise ImportError("No module named 'mlx_lm'")

        monkeypatch.setattr(mod, "_titler", NoMlx())
        assert generate_llm_title("some text") is None


class TestUnloadAndRelease:
    def test_unload_is_safe_when_not_loaded(self):
        LlmTitler().unload()  # must not raise even though nothing is loaded

    def test_unload_clears_loaded_state(self):
        titler = LlmTitler()
        titler._model = object()
        titler._tokenizer = object()
        titler._sampler = object()
        titler.unload()
        assert titler._model is None
        assert titler._tokenizer is None
        assert titler._sampler is None

    def test_release_after_use_unloads(self, monkeypatch):
        import scansnap_ocr.llm_titler as mod

        calls = {"unload": 0}

        class FakeTitler:
            def title(self, text):
                return "Firma Rechnung"

            def unload(self):
                calls["unload"] += 1

        monkeypatch.setattr(mod, "TITLE_LLM_RELEASE_AFTER_USE", True)
        monkeypatch.setattr(mod, "_titler", FakeTitler())
        assert generate_llm_title("some text") == "Firma Rechnung"
        assert calls["unload"] == 1

    def test_no_release_keeps_resident(self, monkeypatch):
        import scansnap_ocr.llm_titler as mod

        calls = {"unload": 0}

        class FakeTitler:
            def title(self, text):
                return "Firma Rechnung"

            def unload(self):
                calls["unload"] += 1

        monkeypatch.setattr(mod, "TITLE_LLM_RELEASE_AFTER_USE", False)
        monkeypatch.setattr(mod, "_titler", FakeTitler())
        generate_llm_title("some text")
        assert calls["unload"] == 0


@pytest.mark.skipif(
    os.environ.get("SCANSNAP_TEST_LLM") != "1",
    reason="set SCANSNAP_TEST_LLM=1 to run the model-backed titler test",
)
class TestLlmTitlerIntegration:
    def test_produces_title_from_real_text(self):
        text = (
            "IKEA Deutschland GmbH & Co. KG\n"
            "Rechnung\nKundennummer 12345\nKALLAX Regal weiß\nBetrag 79,00 EUR"
        )
        title = generate_llm_title(text)
        assert title
        assert "IKEA" in title
