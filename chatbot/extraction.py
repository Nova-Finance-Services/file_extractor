"""Extract text from attachment bytes (library first, OCR fallback)."""
import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from fileExtraction import (
    detect_file_extension,
    ensure_file_extension_path,
    is_xlsx_bytes,
    resolve_content_type,
    resolve_file_extension,
    try_extract_with_fallback,
)
from chatbot.ocr_space import (
    extract_text_from_image_base64,
    extract_text_from_pdf_base64,
    is_ocr_available,
)

logger = logging.getLogger(__name__)


def _extract_with_libraries(file_bytes: bytes, filename: Optional[str], content_type: Optional[str]) -> str:
    file_extension = resolve_file_extension(filename, content_type)
    if not file_extension and is_xlsx_bytes(file_bytes):
        file_extension = ".xlsx"

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_extension or ".tmp")
    try:
        temp_file.write(file_bytes)
        temp_file.close()
        working_path = ensure_file_extension_path(
            temp_file.name,
            file_extension or detect_file_extension(temp_file.name),
        )
        extension = Path(working_path).suffix.lower() or file_extension
        content, _, error = try_extract_with_fallback(working_path, extension)
        if error or not content:
            return ""
        return content.strip()
    finally:
        if os.path.exists(temp_file.name):
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass
        if "working_path" in locals() and working_path != temp_file.name and os.path.exists(working_path):
            try:
                os.unlink(working_path)
            except OSError:
                pass


def extract_text_from_bytes(
    file_bytes: bytes,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> str:
    """Extract text using in-process libraries, then OCR if needed."""
    if not file_bytes:
        return ""

    content_type = resolve_content_type(content_type, filename, file_bytes)
    name = (filename or "").lower()
    ct = (content_type or "").lower()

    try:
        text = _extract_with_libraries(file_bytes, filename, content_type)
        if text:
            return text
    except Exception as exc:
        logger.warning("Library extraction failed for %s: %s", filename, exc)

    if not is_ocr_available():
        return ""

    payload_b64 = base64.b64encode(file_bytes).decode("utf-8")
    is_pdf = "pdf" in ct or name.endswith(".pdf")
    is_xlsx = "spreadsheetml" in ct or name.endswith(".xlsx")
    is_image = ct.startswith("image/") or any(
        name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
    )

    if is_xlsx:
        return ""
    try:
        if is_pdf:
            return extract_text_from_pdf_base64(payload_b64)
        if is_image:
            return extract_text_from_image_base64(payload_b64, content_type, filename)
        return extract_text_from_image_base64(payload_b64, content_type, filename)
    except Exception as exc:
        logger.warning("OCR extraction failed for %s: %s", filename, exc)
        return ""
