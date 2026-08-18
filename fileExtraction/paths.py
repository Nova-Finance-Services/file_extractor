"""Path helpers for temporary and working files."""
import os
from pathlib import Path
from typing import Optional


def ensure_file_extension_path(file_path: str, file_extension: Optional[str]) -> str:
    """Rename temp files so libraries that require extensions (e.g. openpyxl) can open them."""
    if not file_extension:
        return file_path
    current_suffix = Path(file_path).suffix.lower()
    if current_suffix == file_extension:
        return file_path
    new_path = str(Path(file_path).with_suffix(file_extension))
    os.rename(file_path, new_path)
    return new_path
