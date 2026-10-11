"""Apple Live Text OCR engine (macOS Sonoma+, via ocrmac's LiveText path).

Live Text is the newer engine behind macOS's "select text in images" feature
(VisionKit / VKCImageAnalyzer), generally stronger than the classic Vision
`VNRecognizeTextRequest`. Unlike Vision (one box per line), Live Text in
``unit="token"`` mode returns **word-level** boxes, which lets the invisible text
layer align more tightly with the scan — so search highlights sit on individual
words rather than spanning a whole line.

ocrmac normalizes Live Text boxes to the same bottom-left-origin convention as
Vision, so the conversion helper is shared with the Apple Vision engine.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .apple_vision_engine import VISION_LANGUAGES, vision_bbox_to_polygon
from .base import OcrResult

# "token" → word-level boxes (tighter highlight alignment); "line" → one box per
# line (same granularity as the Vision engine).
LIVETEXT_UNIT = "token"


class AppleLiveTextEngine:
    """Wraps Apple's Live Text OCR via the ocrmac bridge."""

    name = "AppleLiveText"

    def __init__(self, unit: str = LIVETEXT_UNIT) -> None:
        from ocrmac import ocrmac

        self._ocrmac = ocrmac
        self._unit = unit

    def recognize(self, image: np.ndarray) -> list[OcrResult]:
        pil = Image.fromarray(image)
        width, height = pil.width, pil.height

        # LiveText rejects recognition_level / confidence_threshold — omit them.
        raw = self._ocrmac.OCR(
            pil,
            framework="livetext",
            language_preference=VISION_LANGUAGES,
            unit=self._unit,
        ).recognize()

        results: list[OcrResult] = []
        for text, confidence, bbox in raw:
            if not text.strip():
                continue
            polygon = vision_bbox_to_polygon(bbox, width, height)
            results.append((polygon, text, float(confidence)))
        return results
