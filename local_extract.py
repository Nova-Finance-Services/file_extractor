"""Shared helpers for local file extraction (CLI + tests)."""
from pathlib import Path

from fileExtraction import (
    SUPPORTED_EXTENSIONS,
    detect_file_extension,
    ensure_file_extension_path,
    try_extract_with_fallback,
)

ROOT = Path(__file__).resolve().parent
TESTING_FILES_DIR = ROOT / "testing_files"


def list_testing_files():
    if not TESTING_FILES_DIR.is_dir():
        return []
    return sorted(
        path
        for path in TESTING_FILES_DIR.iterdir()
        if path.is_file()
        and path.suffix.lower() in set(SUPPORTED_EXTENSIONS)
        and not path.name.startswith(".")
    )


def extract_local_file(file_path: Path) -> dict:
    file_path = file_path.resolve()
    if not file_path.is_file():
        return {"success": False, "error": f"File not found: {file_path}"}

    extension = detect_file_extension(str(file_path))
    working_path = ensure_file_extension_path(str(file_path), extension)
    extension = Path(working_path).suffix.lower() or extension

    content, detected_ext, error = try_extract_with_fallback(working_path, extension)

    if error:
        return {
            "success": False,
            "error": error,
            "file_type": detected_ext or extension,
            "source_file": str(file_path),
        }

    if content is None:
        return {
            "success": False,
            "error": "Unsupported file type or failed to extract content",
            "file_type": detected_ext or extension,
            "source_file": str(file_path),
        }

    return {
        "success": True,
        "content": content,
        "file_type": detected_ext or extension,
        "content_length": len(content),
        "source_file": str(file_path),
    }
