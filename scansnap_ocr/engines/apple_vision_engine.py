"""Apple Vision OCR engine (macOS, Neural-Engine accelerated).

Wraps the `ocrmac` bridge to Apple's VNRecognizeTextRequest. Vision returns
normalized bounding boxes (0-1) with a bottom-left origin; this adapter converts
them to the 4-point pixel polygon (origin top-left) that the text-layer embedding
expects. The conversion is isolated in :func:`vision_bbox_to_polygon` so it can be
unit-tested without invoking Vision.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .base import BBox, OcrResult

# Vision language codes (BCP-47), unlike EasyOCR's "de"/"en".
VISION_LANGUAGES = ["de-DE", "en-US"]


def vision_bbox_to_polygon(
    bbox: tuple[float, float, float, float], width: int, height: int
) -> BBox:
    """Convert a Vision bounding box to a 4-point pixel polygon.

    Args:
        bbox: ``(x, y, w, h)`` normalized to 0-1, origin **bottom-left**
            (Apple Vision convention).
        width, height: Pixel dimensions of the rendered page image.

    Returns:
        ``[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]`` in pixels, origin **top-left**.
    """
    x, y, w, h = bbox
    x1 = x * width
    x2 = (x + w) * width
    # Flip Y: Vision's origin is bottom-left, the image's is top-left.
    y_top = (1 - y - h) * height
    y_bottom = (1 - y) * height
    return [[x1, y_top], [x2, y_top], [x2, y_bottom], [x1, y_bottom]]


class AppleVisionEngine:
    """Wraps Apple's Vision OCR via the ocrmac bridge."""

    name = "AppleVision"

    def __init__(self) -> None:
        # Import lazily so non-macOS environments can still import the package.
        from ocrmac import ocrmac

        self._ocrmac = ocrmac

    def recognize(self, image: np.ndarray) -> list[OcrResult]:
        pil = Image.fromarray(image)
        width, height = pil.width, pil.height

        raw = self._ocrmac.OCR(
            pil,
            recognition_level="accurate",
            language_preference=VISION_LANGUAGES,
        ).recognize()

        results: list[OcrResult] = []
        for text, confidence, bbox in raw:
            if not text.strip():
                continue
            polygon = vision_bbox_to_polygon(bbox, width, height)
            results.append((polygon, text, float(confidence)))
        return results
