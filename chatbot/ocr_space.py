"""OCR.space fallback when library extraction fails."""
import base64
import logging
from typing import Optional

import requests

from chatbot.config import SPACE_OCR_KEY

logger = logging.getLogger(__name__)

OCR_PARSE_IMAGE = "https://api.ocr.space/parse/image"


def is_ocr_available() -> bool:
    return bool(SPACE_OCR_KEY)


def _combine_parsed(data: dict) -> str:
    parts = []
    for item in data.get("ParsedResults") or []:
        text = item.get("ParsedText")
        if text:
            parts.append(str(text).strip())
    return "\n\n".join(parts).strip()


def _assert_success(data: dict, allow_partial: bool = True) -> None:
    code = data.get("OCRExitCode")
    if code == 1 or (allow_partial and code == 2):
        return
    errors = data.get("ErrorMessage") or []
    raise RuntimeError(f"OCR failed: {errors[0] if errors else data}")


def extract_text_from_pdf_base64(file_base64: str) -> str:
    if not is_ocr_available():
        raise RuntimeError("SPACE_OCR_KEY is not configured")

    raw = file_base64.split(",", 1)[-1].replace("\n", "").replace("\r", "")
    file_bytes = base64.b64decode(raw)

    files = {"file": ("document.pdf", file_bytes, "application/pdf")}
    data = {
        "apikey": SPACE_OCR_KEY,
        "filetype": "PDF",
        "language": "eng",
        "isOverlayRequired": "false",
        "detectOrientation": "true",
        "scale": "true",
        "OCREngine": "2",
    }
    response = requests.post(OCR_PARSE_IMAGE, files=files, data=data, timeout=120)
    response.raise_for_status()
    payload = response.json()
    _assert_success(payload, allow_partial=True)
    text = _combine_parsed(payload)
    if not text:
        raise RuntimeError("OCR returned empty text")
    return text


def extract_text_from_image_base64(
    file_base64: str,
    content_type: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    if not is_ocr_available():
        raise RuntimeError("SPACE_OCR_KEY is not configured")

    raw = file_base64.split(",", 1)[-1].replace("\n", "").replace("\r", "")
    mime = (content_type or "").split(";")[0].strip().lower()
    if not mime.startswith("image/"):
        name = (filename or "").lower()
        if name.endswith(".png"):
            mime = "image/png"
        elif name.endswith(".gif"):
            mime = "image/gif"
        elif name.endswith(".webp"):
            mime = "image/webp"
        else:
            mime = "image/jpeg"

    data = {
        "apikey": SPACE_OCR_KEY,
        "base64Image": f"data:{mime};base64,{raw}",
        "language": "eng",
        "isOverlayRequired": "false",
        "detectOrientation": "true",
        "scale": "true",
        "OCREngine": "2",
    }
    response = requests.post(OCR_PARSE_IMAGE, data=data, timeout=120)
    response.raise_for_status()
    payload = response.json()
    _assert_success(payload, allow_partial=False)
    text = _combine_parsed(payload)
    if not text:
        raise RuntimeError("OCR returned empty text")
    return text
