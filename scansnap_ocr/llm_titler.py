"""Local LLM document titler (mlx-lm, Apple Silicon).

Reads the OCR text of a scanned document and produces a concise German filename
title of the form *sender + document type + subject* — the way people name files
manually. Keyword heuristics (see :mod:`scansnap_ocr.title`) can't comprehend a
document, so they routinely pick noise lines and force-append the wrong type; an
LLM that reads the text does dramatically better.

Runs fully on-device (privacy: these are personal documents and must stay local).
Requires the optional ``mlx-lm`` dependency and downloads a quantized model on
first use. Callers get graceful degradation: :func:`generate_llm_title` returns
``None`` on any failure so the caller can fall back to the heuristic titler.

The prompt building and output cleaning are pure functions (:func:`build_messages`,
:func:`clean_llm_title`) and unit-tested without loading a model.
"""

from __future__ import annotations

import logging
import re

from .config import (
    TITLE_DROP_WORDS,
    TITLE_LLM_MAX_CHARS,
    TITLE_LLM_MAX_TOKENS,
    TITLE_LLM_MODEL,
    TITLE_LLM_RELEASE_AFTER_USE,
)

logger = logging.getLogger(__name__)

# Upper bound on words in a generated title (hand-picked names typically run ~2-8 words).
MAX_TITLE_WORDS = 8

SYSTEM_PROMPT = (
    "Du erstellst aus dem OCR-Text eines gescannten Dokuments einen kurzen, "
    "praegnanten deutschen Dateititel. Der Titel besteht aus 3 bis 6 durch "
    "Leerzeichen getrennten Woertern und enthaelt, soweit erkennbar und in dieser "
    "Reihenfolge: (1) Absender/Firma/Behoerde, (2) Dokumententyp (Rechnung, "
    "Bescheid, Bußgeldbescheid, Kuendigung, Vertrag, Mitteilung, Angebot, Quittung, "
    "Mahnung, Bescheinigung, Lieferschein), (3) das wichtigste Thema bzw. genannte "
    "Personennamen. Nenne den ABSENDER/die Firma, NICHT den Empfaenger oder "
    "Adressaten des Schreibens. Kein Datum, keine Adresse, keine Anfuehrungszeichen, "
    "keine Wortwiederholungen. Verwende nur Woerter, die im Text vorkommen; erfinde "
    "keine Namen. Antworte ausschliesslich mit dem Titel als normale Woerter, "
    "getrennt durch Leerzeichen."
)

# Few-shot examples steer the format (spaced words; sender -> type -> subject order)
# and cut hallucination. The example inputs deliberately avoid rare product nouns so
# their tokens don't leak into unrelated titles (an earlier draft leaked "Kallax").
FEW_SHOT = [
    (
        "Stadtwerke Bielefeld GmbH\nIhre Jahresrechnung\nKundennummer 100234\n"
        "Abrechnung Ihrer Stromlieferung fuer den Zeitraum ...",
        "Stadtwerke Bielefeld Rechnung Strom",
    ),
    (
        "Der Buergermeister der Stadt Hameln\nBussgeldbescheid\n"
        "Aktenzeichen 12/345\nOrdnungswidrigkeit: zulaessige Geschwindigkeit ...",
        "Stadt Hameln Bussgeldbescheid Geschwindigkeit",
    ),
    (
        "Techniker Krankenkasse\nMeldebescheinigung zur Sozialversicherung\n"
        "Fuer: Mustermann, Erika\nBeschaeftigungszeitraum ...",
        "Techniker Krankenkasse Meldebescheinigung Sozialversicherung",
    ),
]

_LABEL_PREFIX = re.compile(r"^\s*(titel|title|dateiname|filename)\s*[:\-–]\s*", re.I)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-zäöüß])(?=[A-ZÄÖÜ])")
_UNSAFE = re.compile(r'[<>:"/\\|?*]')


def _user_prompt(text: str) -> str:
    return f"OCR-Text:\n\n{text.strip()[:TITLE_LLM_MAX_CHARS]}\n\nTitel:"


def build_messages(text: str) -> list[dict]:
    """Build the chat messages (system + few-shot + the document) for the LLM."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for src, title in FEW_SHOT:
        messages.append({"role": "user", "content": _user_prompt(src)})
        messages.append({"role": "assistant", "content": title})
    messages.append({"role": "user", "content": _user_prompt(text)})
    return messages


def _decamel(token: str) -> str:
    """Split mashed CamelCase compounds ("MeningokokkenRechnung") into words.

    Only applied to long tokens so real forms like "GmbH", "AG" or "McDonald"
    survive intact.
    """
    if len(token) > 12:
        return _CAMEL_BOUNDARY.sub(" ", token)
    return token


def clean_llm_title(
    raw: str,
    max_words: int = MAX_TITLE_WORDS,
    drop_words: list[str] | None = None,
) -> str:
    """Normalise a raw model response into a filesystem-safe title.

    Takes the first line, strips label prefixes/quotes, turns underscores and
    slashes into spaces, splits over-long CamelCase tokens, removes unsafe
    characters, drops configured noise words (e.g. the recipient surname),
    collapses adjacent duplicates and caps the word count. Returns "" when
    nothing usable remains.
    """
    if not raw or not raw.strip():
        return ""
    if drop_words is None:
        drop_words = TITLE_DROP_WORDS
    drop = {w.casefold() for w in drop_words}
    line = raw.strip().splitlines()[0]
    line = _LABEL_PREFIX.sub("", line)
    line = line.strip().strip("\"'“”`")
    line = line.replace("_", " ")
    tokens = [_decamel(tok) for tok in line.split()]
    line = " ".join(tokens)
    line = _UNSAFE.sub(" ", line)
    line = re.sub(r"\s+", " ", line).strip(" .,-;:")
    words = [w for w in line.split() if w.strip(".,;:").casefold() not in drop]
    return " ".join(_dedupe_adjacent(words)[:max_words])


def _dedupe_adjacent(words: list[str]) -> list[str]:
    """Drop consecutive duplicate words (case-insensitive), e.g. "Firma Firma"."""
    out: list[str] = []
    for word in words:
        if not out or out[-1].casefold() != word.casefold():
            out.append(word)
    return out


class LlmTitler:
    """Lazy-loading wrapper around an mlx-lm model for document titling."""

    def __init__(self, model_id: str = TITLE_LLM_MODEL) -> None:
        self._model_id = model_id
        self._model = None
        self._tokenizer = None
        self._sampler = None

    def _load(self):
        """Load the MLX model on first use (downloaded on first ever call)."""
        if self._model is None:
            from mlx_lm import load
            from mlx_lm.sample_utils import make_sampler

            logger.info("Loading title LLM: %s", self._model_id)
            self._model, self._tokenizer = load(self._model_id)
            self._sampler = make_sampler(temp=0.0)  # deterministic
        return self._model, self._tokenizer, self._sampler

    def title(self, text: str) -> str | None:
        """Generate a cleaned title for OCR ``text``; None if text is empty."""
        if not text or not text.strip():
            return None
        from mlx_lm import generate

        model, tokenizer, sampler = self._load()
        prompt = tokenizer.apply_chat_template(
            build_messages(text), add_generation_prompt=True
        )
        raw = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=TITLE_LLM_MAX_TOKENS,
            sampler=sampler,
            verbose=False,
        )
        return clean_llm_title(raw) or None

    def unload(self) -> None:
        """Free the model from RAM (and the MLX metal cache) if it was loaded.

        A subsequent :meth:`title` call transparently reloads it (~0.9s warm).
        """
        if self._model is None:
            return
        self._model = None
        self._tokenizer = None
        self._sampler = None
        import gc

        gc.collect()
        try:
            import mlx.core as mx

            mx.clear_cache()
        except Exception as exc:  # pragma: no cover - best-effort cache release
            logger.debug("mlx cache clear failed during unload: %s", exc)


_titler: LlmTitler | None = None


def get_titler() -> LlmTitler:
    """Return the process-wide titler singleton (keeps the model resident)."""
    global _titler
    if _titler is None:
        _titler = LlmTitler()
    return _titler


def generate_llm_title(text: str) -> str | None:
    """Return an LLM-generated title, or None if the LLM is unavailable/failed.

    Never raises — the caller falls back to the heuristic titler on None. Covers
    the common cases where ``mlx-lm`` isn't installed (non-macOS, EasyOCR hosts)
    or the model can't be downloaded.
    """
    try:
        return get_titler().title(text)
    except ImportError:
        logger.warning("mlx-lm not installed; falling back to heuristic titler")
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("LLM titler failed (%s); falling back to heuristic", exc)
        return None
    finally:
        # In the 24/7 watcher (SCANSNAP_TITLE_RELEASE=1) free the ~1.7 GB model
        # after each title so idle RAM stays at baseline; CLI runs keep it resident.
        if TITLE_LLM_RELEASE_AFTER_USE and _titler is not None:
            _titler.unload()
