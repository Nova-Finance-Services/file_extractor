"""Decode base64 and data-URL payloads into temporary files."""
import base64
import binascii
import logging
import tempfile
from pathlib import Path

from fileExtraction.config import CONFIG
from fileExtraction.detection import detect_file_extension, is_xlsx_bytes, resolve_content_type
from fileExtraction.mime import extension_from_content_type, resolve_file_extension
from fileExtraction.paths import ensure_file_extension_path

logger = logging.getLogger(__name__)


def decode_base64_to_temp_file(
    base64_input: str,
    filename: str | None = None,
    content_type: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """
    Decode base64 (or data URL) into a temporary file.

    Returns:
        (file_path, file_extension, error_message)
    """
    if len(base64_input) > CONFIG["MAX_FILE_SIZE"] * 2:
        max_mb = CONFIG["MAX_FILE_SIZE"] / (1024 * 1024)
        return None, None, f"Base64 payload too large. Maximum file size: {max_mb:.1f}MB"

    if "," in base64_input and base64_input.strip().lower().startswith("data:"):
        try:
            header, payload = base64_input.split(",", 1)
            base64_input = payload.strip()
            if ";" in header and ":" in header:
                detected_mime = header.split(":", 1)[1].split(";", 1)[0].strip()
                if detected_mime and not content_type:
                    content_type = detected_mime
        except ValueError:
            return None, None, "Invalid data URL format for base64 payload"

    try:
        file_bytes = base64.b64decode(base64_input, validate=True)
    except binascii.Error:
        return None, None, "Invalid base64 data"

    if not file_bytes:
        return None, None, "Decoded file is empty"

    if len(file_bytes) > CONFIG["MAX_FILE_SIZE"]:
        max_mb = CONFIG["MAX_FILE_SIZE"] / (1024 * 1024)
        return None, None, f"File too large. Maximum size: {max_mb:.1f}MB"

    file_extension = resolve_file_extension(filename, content_type)
    if not file_extension:
        resolved_mime = resolve_content_type(content_type, filename, file_bytes)
        file_extension = extension_from_content_type(resolved_mime)
    if not file_extension and is_xlsx_bytes(file_bytes):
        file_extension = ".xlsx"

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_extension or ".tmp")
    try:
        temp_file.write(file_bytes)
    finally:
        temp_file.close()

    file_path = ensure_file_extension_path(
        temp_file.name,
        file_extension or detect_file_extension(temp_file.name),
    )
    file_extension = Path(file_path).suffix.lower() or file_extension
    logger.info(
        "Decoded base64 file filename=%s content_type=%s bytes=%s extension=%s",
        filename,
        content_type,
        len(file_bytes),
        file_extension,
    )
    return file_path, file_extension, None
