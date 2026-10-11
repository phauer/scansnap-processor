"""Qwen3-VL OCR engine (local VLM via mlx-vlm, Apple Silicon).

This is the high-accuracy contender — a vision-language model that transcribes the
whole page and, when prompted, returns grounding boxes per line. It is heavier than
Apple Vision (multi-GB model, slower per page) and the grounding-box output is the
less robust part of the integration, so the parsing is isolated in the pure
:func:`parse_grounded_output` helper (unit-tested without invoking the model).

Requires the optional ``mlx-vlm`` dependency and a Qwen3-VL MLX model.
"""

from __future__ import annotations

import json

import numpy as np
from PIL import Image

from .base import BBox, OcrResult

# An MLX-quantized Qwen3-VL checkpoint. Override via constructor if desired.
DEFAULT_MODEL = "mlx-community/Qwen3-VL-8B-Instruct-4bit"

# Ask for one JSON object per text line with an absolute-pixel bounding box.
GROUNDING_PROMPT = (
    "Transcribe all text in this document image. Return a JSON array where each "
    "element is an object with keys 'text' (the line of text, preserving German "
    "characters like ä ö ü ß) and 'bbox' ([x1, y1, x2, y2] in absolute pixel "
    "coordinates, origin top-left). Output only the JSON array."
)


def parse_grounded_output(raw: str, width: int, height: int) -> list[OcrResult]:
    """Parse a Qwen3-VL grounding response into canonical OCR results.

    Tolerates models that wrap the JSON in prose or markdown fences. Clamps boxes
    to the image bounds. ``width``/``height`` are used to clamp out-of-range
    coordinates the model may emit.

    Returns a list of ``(polygon, text, confidence)``. Confidence is a fixed 1.0 —
    VLMs do not emit per-line confidence.
    """
    array_text = _extract_json_array(raw)
    if array_text is None:
        return []
    try:
        items = json.loads(array_text)
    except json.JSONDecodeError:
        return []

    results: list[OcrResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        bbox = item.get("bbox")
        if not text or not _is_xyxy(bbox):
            continue
        x1, y1, x2, y2 = (float(v) for v in bbox)
        x1, x2 = sorted((_clamp(x1, 0, width), _clamp(x2, 0, width)))
        y1, y2 = sorted((_clamp(y1, 0, height), _clamp(y2, 0, height)))
        polygon: BBox = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        results.append((polygon, text, 1.0))
    return results


def _extract_json_array(raw: str) -> str | None:
    """Pull the outermost JSON array out of a model response."""
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    return raw[start : end + 1]


def _is_xyxy(bbox) -> bool:
    return (
        isinstance(bbox, (list, tuple))
        and len(bbox) == 4
        and all(isinstance(v, (int, float)) for v in bbox)
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class QwenVlmEngine:
    """Wraps a Qwen3-VL model via mlx-vlm for grounded OCR."""

    name = "Qwen3-VL"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self._model_id = model
        self._model = None
        self._processor = None
        self._config = None

    def _load(self):
        """Lazy-load the MLX model (multi-GB; downloaded on first use)."""
        if self._model is None:
            from mlx_vlm import load
            from mlx_vlm.utils import load_config

            self._model, self._processor = load(self._model_id)
            self._config = load_config(self._model_id)
        return self._model, self._processor, self._config

    def recognize(self, image: np.ndarray) -> list[OcrResult]:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        model, processor, config = self._load()
        pil = Image.fromarray(image)

        formatted = apply_chat_template(
            processor, config, GROUNDING_PROMPT, num_images=1
        )
        raw = generate(model, processor, formatted, [pil], max_tokens=4096, verbose=False)
        text = raw if isinstance(raw, str) else getattr(raw, "text", str(raw))
        return parse_grounded_output(text, pil.width, pil.height)
