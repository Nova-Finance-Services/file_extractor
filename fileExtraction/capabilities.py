"""Optional library availability flags."""
import logging

logger = logging.getLogger(__name__)

try:
    import pypdf  # noqa: F401

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("pypdf not available. PDF extraction disabled.")

try:
    from docx import Document  # noqa: F401

    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    logger.warning("python-docx not available. DOCX extraction disabled.")

try:
    import docx2python  # noqa: F401

    DOC_AVAILABLE = True
except ImportError:
    DOC_AVAILABLE = False
    logger.warning("docx2python not available. DOC extraction disabled.")

try:
    from openpyxl import load_workbook  # noqa: F401

    XLSX_AVAILABLE = True
except ImportError:
    XLSX_AVAILABLE = False
    logger.warning("openpyxl not available. XLSX extraction disabled.")
