"""Health and service-info routes."""
from flask import Blueprint, jsonify

from fileExtraction import (
    CONFIG,
    DOC_AVAILABLE,
    DOCX_AVAILABLE,
    PDF_AVAILABLE,
    SUPPORTED_EXTENSIONS,
    XLSX_AVAILABLE,
)

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "pdf_support": PDF_AVAILABLE,
        "docx_support": DOCX_AVAILABLE,
        "doc_support": DOC_AVAILABLE,
        "xlsx_support": XLSX_AVAILABLE,
        "max_file_size_mb": CONFIG["MAX_FILE_SIZE"] / (1024 * 1024),
        "auth_required": bool(CONFIG.get("FILE_EXTRACTOR_KEY", "")),
    }), 200


@health_bp.route("/", methods=["GET"])
def index():
    """API information endpoint."""
    return jsonify({
        "service": "Nova Flask worker",
        "version": "1.1.0",
        "endpoints": {
            "/extract": "Extract content from file URL (GET/POST) - Requires API key",
            "/extract-base64": "Extract content from base64-encoded file (POST) - Requires API key",
            "/chatbot-document-processing": "Queue Exact document batch processing (POST, Celery worker) - Requires API key",
            "/r2r/accounting-agent/enqueue": "Queue R2R accounting agent org-close jobs (POST, Celery worker) - Requires API key",
            "/health": "Health check (GET)",
        },
        "supported_formats": SUPPORTED_EXTENSIONS,
        "authentication": "Bearer token in Authorization header" if CONFIG.get("FILE_EXTRACTOR_KEY") else "Disabled",
    }), 200
