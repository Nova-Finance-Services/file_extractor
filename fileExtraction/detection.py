"""File type detection from bytes, paths, and magic numbers."""
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

from fileExtraction.constants import SUPPORTED_EXTENSIONS


def is_xlsx_bytes(file_bytes: bytes) -> bool:
    """Detect XLSX payloads by ZIP structure."""
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
            return any(name.startswith("xl/") for name in archive.namelist())
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def is_xlsx_file(file_path: str) -> bool:
    """Detect XLSX files by ZIP structure (Office Open XML spreadsheet)."""
    try:
        if not zipfile.is_zipfile(file_path):
            return False
        with zipfile.ZipFile(file_path) as archive:
            return any(name.startswith("xl/") for name in archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def infer_content_type_from_magic(file_bytes: bytes) -> Optional[str]:
    if len(file_bytes) >= 4 and file_bytes[:4] == b"%PDF":
        return "application/pdf"
    if len(file_bytes) >= 3 and file_bytes[0] == 0xFF and file_bytes[1] == 0xD8 and file_bytes[2] == 0xFF:
        return "image/jpeg"
    if (
        len(file_bytes) >= 8
        and file_bytes[0] == 0x89
        and file_bytes[1] == 0x50
        and file_bytes[2] == 0x4E
        and file_bytes[3] == 0x47
    ):
        return "image/png"
    return None


def detect_file_extension(file_path: str) -> Optional[str]:
    """Infer file extension from path suffix or file signature."""
    suffix = Path(file_path).suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS:
        return suffix
    if is_xlsx_file(file_path):
        return ".xlsx"
    return None


def resolve_content_type(
    content_type: Optional[str],
    filename: Optional[str] = None,
    file_bytes: Optional[bytes] = None,
) -> Optional[str]:
    """Pick the best content type from header, filename, or magic bytes."""
    ct = (content_type or "").strip().lower()
    if ct and ct != "application/octet-stream":
        return content_type

    if file_bytes:
        magic = infer_content_type_from_magic(file_bytes)
        if magic:
            return magic

    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if name.endswith(".doc"):
        return "application/msword"
    if name.endswith(".csv"):
        return "text/csv"
    if name.endswith(".txt"):
        return "text/plain"
    return content_type
