"""Pluggable OCR engines.

Each engine implements the :class:`OcrEngine` protocol and returns results in
EasyOCR's native shape — a list of ``(bbox, text, confidence)`` tuples where
``bbox`` is a 4-point pixel polygon ``[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]`` in the
coordinate space of the rendered page image (origin top-left). Keeping this
contract means the downstream text-layer embedding in ``ocr.py`` is engine-agnostic.
"""

from __future__ import annotations

from .base import OcrEngine, OcrResult

_ENGINES: dict[str, OcrEngine] = {}


def get_engine(name: str | None = None) -> OcrEngine:
    """Return a lazily-instantiated singleton OCR engine.

    Args:
        name: Engine key ("easyocr", "apple_vision", "qwen3vl"). Defaults to the
            value of ``config.OCR_ENGINE``.
    """
    from ..config import OCR_ENGINE

    name = name or OCR_ENGINE
    if name not in _ENGINES:
        _ENGINES[name] = _build_engine(name)
    return _ENGINES[name]


def _build_engine(name: str) -> OcrEngine:
    if name == "easyocr":
        from .easyocr_engine import EasyOcrEngine

        return EasyOcrEngine()
    if name == "apple_vision":
        from .apple_vision_engine import AppleVisionEngine

        return AppleVisionEngine()
    if name == "apple_livetext":
        from .apple_livetext_engine import AppleLiveTextEngine

        return AppleLiveTextEngine()
    if name == "qwen3vl":
        from .qwen_vlm_engine import QwenVlmEngine

        return QwenVlmEngine()
    raise ValueError(
        f"Unknown OCR engine {name!r}. "
        f"Expected one of: easyocr, apple_vision, apple_livetext, qwen3vl."
    )


__all__ = ["OcrEngine", "OcrResult", "get_engine"]
