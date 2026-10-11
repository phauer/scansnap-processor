"""OCR engine interface and shared types."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

# A 4-point polygon in page-image pixel coordinates (origin top-left):
# [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
BBox = list[list[float]]

# EasyOCR-shaped result: (bbox, text, confidence).
OcrResult = tuple[BBox, str, float]


@runtime_checkable
class OcrEngine(Protocol):
    """A pluggable OCR backend.

    Engines must return results in EasyOCR's native shape so the text-layer
    embedding in ``ocr.py`` works unchanged regardless of the backend.
    """

    #: Human-readable engine name, embedded in PDF producer metadata.
    name: str

    def recognize(self, image: np.ndarray) -> list[OcrResult]:
        """Run OCR on a rendered page image.

        Args:
            image: RGB(A) page image as a numpy array (rendered at ``OCR_DPI``).

        Returns:
            A list of ``(bbox, text, confidence)`` tuples. ``bbox`` is a 4-point
            pixel polygon in the image's coordinate space (origin top-left).
        """
        ...
