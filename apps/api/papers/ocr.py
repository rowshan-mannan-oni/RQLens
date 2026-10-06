"""OCR for scanned pages, with positions, so citations still open at a highlighted line.

Uses RapidOCR (ONNX models bundled in the pip package; no system install). Each page is
rendered at OCR_DPI, read into text lines with boxes, and the lines are turned into the
parser's `Line` and `Block` objects in PDF points. Character boxes are spread evenly along the
line, which is enough for line-level highlights.

OCR is optional: without the `ocr` extra, `available()` is false and scanned papers are
marked "needs OCR" as before.
"""

import logging
import re
import threading
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

OCR_DPI = 300  # fewer words run together than at 200 dpi, and not slower
MIN_CONFIDENCE = 0.5

_engine: Any = None
_lock = threading.Lock()


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        import wordninja  # noqa: F401
    except ImportError:
        return False
    return True


def _get_engine() -> Any:
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        return _engine


def ocr_lines(page: Any) -> list[tuple[str, tuple[float, float, float, float], float]]:
    """Text lines of one PDF page: (text, (x0, y0, x1, y1) in points, confidence)."""
    pix = page.get_pixmap(dpi=OCR_DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    with _lock:  # the ONNX session is not shared safely between threads
        engine = _engine
    result, _ = (engine or _get_engine())(img)
    scale = 72 / OCR_DPI
    out = []
    for box, text, confidence in result or []:
        if not str(text).strip() or float(confidence) < MIN_CONFIDENCE:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        rect = (min(xs) * scale, min(ys) * scale, max(xs) * scale, max(ys) * scale)
        out.append((str(text).strip(), rect, float(confidence)))
    return out


GLUED = re.compile(r"[A-Za-z]{14,}")


def unglue(text: str) -> str:
    """Put back spaces OCR lost in tightly set text ("Reviewersreportedspending"): long runs
    of letters are split into the most likely English words."""
    import wordninja

    def split(m: re.Match[str]) -> str:
        word = m.group(0)
        parts = wordninja.split(word)
        if len(parts) < 2 or sum(map(len, parts)) != len(word):
            return word
        if sum(len(p) for p in parts) / len(parts) < 2.5:
            return word  # splitting into letters means it is not English prose
        return " ".join(parts)

    text = GLUED.sub(split, text)
    # "code.We" -> "code. We": OCR often drops the space after a full stop.
    return re.sub(r"(?<=[a-z]{2})([.!?])(?=[A-Z][a-z])", r"\1 ", text)
