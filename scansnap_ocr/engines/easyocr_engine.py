"""EasyOCR engine (deep learning, CPU). The original/default reference engine."""

from __future__ import annotations

import numpy as np

from ..config import OCR_LANGUAGES
from .base import OcrResult


class EasyOcrEngine:
    """Wraps EasyOCR. Output is already in the canonical (bbox, text, confidence)
    shape with a 4-point pixel polygon, so no coordinate conversion is needed."""

    name = "EasyOCR"

    def __init__(self) -> None:
        self._reader = None

    def _get_reader(self):
        """Lazy-init the EasyOCR reader (heavy ~5-10s model load)."""
        if self._reader is None:
            import easyocr

            self._reader = easyocr.Reader(OCR_LANGUAGES, gpu=False)
        return self._reader

    def recognize(self, image: np.ndarray) -> list[OcrResult]:
        return self._get_reader().readtext(image)
