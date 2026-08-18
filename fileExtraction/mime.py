"""MIME type and file extension resolution."""
from pathlib import Path
from typing import Optional


def extension_from_content_type(content_type: Optional[str]) -> Optional[str]:
    """
    Map MIME type to file extension.

    Order matters: spreadsheet types must be checked before wordprocessing,
    because spreadsheet MIME types contain 'officedocument'.
    """
    if not content_type:
        return None

    content_type_lower = content_type.lower().split(";")[0].strip()

    if "spreadsheetml" in content_type_lower or "excel" in content_type_lower:
        return ".xlsx"
    if "wordprocessingml" in content_type_lower:
        return ".docx"
    if content_type_lower in ("application/msword",) or "ms-word" in content_type_lower:
        return ".doc"
    if "pdf" in content_type_lower:
        return ".pdf"
    if "csv" in content_type_lower or content_type_lower == "text/csv":
        return ".csv"
    if content_type_lower == "text/plain":
        return ".txt"

    return None


def resolve_file_extension(
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Optional[str]:
    """Resolve lowercase extension (with dot) from filename or Content-Type."""
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix:
            return suffix
    return extension_from_content_type(content_type)


_EXTENSION_TO_CONTENT_TYPE = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def content_type_from_filename(filename: Optional[str]) -> Optional[str]:
    """Infer MIME type from a filename extension."""
    extension = resolve_file_extension(filename=filename)
    if not extension:
        return None
    return _EXTENSION_TO_CONTENT_TYPE.get(extension)
