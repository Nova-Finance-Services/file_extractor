"""File extraction utilities (format detection, download, extract)."""
from fileExtraction.base64_input import decode_base64_to_temp_file
from fileExtraction.capabilities import (
    DOC_AVAILABLE,
    DOCX_AVAILABLE,
    PDF_AVAILABLE,
    XLSX_AVAILABLE,
)
from fileExtraction.config import CONFIG, get_config
from fileExtraction.constants import SUPPORTED_EXTENSIONS
from fileExtraction.detection import (
    detect_file_extension,
    infer_content_type_from_magic,
    is_xlsx_bytes,
    is_xlsx_file,
    resolve_content_type,
)
from fileExtraction.download import download_file
from fileExtraction.extractors import (
    EXTRACTION_FUNCTIONS,
    extract_csv,
    extract_doc,
    extract_docx,
    extract_pdf,
    extract_txt,
    extract_xlsx,
    try_extract_with_fallback,
)
from fileExtraction.mime import (
    content_type_from_filename,
    extension_from_content_type,
    resolve_file_extension,
)
from fileExtraction.paths import ensure_file_extension_path
from fileExtraction.security import validate_url

__all__ = [
    "CONFIG",
    "DOC_AVAILABLE",
    "DOCX_AVAILABLE",
    "EXTRACTION_FUNCTIONS",
    "PDF_AVAILABLE",
    "SUPPORTED_EXTENSIONS",
    "XLSX_AVAILABLE",
    "decode_base64_to_temp_file",
    "detect_file_extension",
    "download_file",
    "ensure_file_extension_path",
    "content_type_from_filename",
    "extension_from_content_type",
    "extract_csv",
    "extract_doc",
    "extract_docx",
    "extract_pdf",
    "extract_txt",
    "extract_xlsx",
    "get_config",
    "infer_content_type_from_magic",
    "is_xlsx_bytes",
    "is_xlsx_file",
    "resolve_content_type",
    "resolve_file_extension",
    "try_extract_with_fallback",
    "validate_url",
]
