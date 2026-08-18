"""Synchronous file-text extraction routes."""
import logging
import os

from flask import Blueprint, jsonify, request

from fileExtraction import (
    SUPPORTED_EXTENSIONS,
    decode_base64_to_temp_file,
    download_file,
    try_extract_with_fallback,
    validate_url,
)
from routes.auth import require_api_key
from routes.limiter import limiter

logger = logging.getLogger(__name__)

extraction_bp = Blueprint("extraction", __name__)


@extraction_bp.route("/extract", methods=["POST", "GET"])
@limiter.limit("30 per minute")
@require_api_key
def extract():
    """Extract content from file URL."""
    file_path = None
    try:
        if request.method == "POST":
            data = request.get_json() or {}
            file_url = data.get("url") or request.form.get("url")
            filename = data.get("filename")
            content_type = data.get("contentType") or data.get("content_type")
        else:
            file_url = request.args.get("url")
            filename = request.args.get("filename")
            content_type = request.args.get("contentType") or request.args.get("content_type")

        if not file_url:
            logger.warning("Extraction request without URL")
            return jsonify({
                "error": 'Missing file URL. Provide "url" parameter in query string (GET) or JSON body (POST)',
            }), 400

        is_valid, error_msg = validate_url(file_url)
        if not is_valid:
            logger.warning("Invalid URL rejected: %s", file_url[:100])
            return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

        logger.info(
            "Extraction request for URL: %s... filename=%s content_type=%s",
            file_url[:100],
            filename,
            content_type,
        )

        file_path, file_extension, error = download_file(
            file_url,
            filename=filename,
            content_type_hint=content_type,
        )
        if error:
            logger.error("Download failed: %s", error)
            return jsonify({"error": error}), 400

        content, detected_ext, extract_error = try_extract_with_fallback(file_path, file_extension)

        if extract_error:
            logger.error("Extraction failed: %s", extract_error)
            return jsonify({
                "error": f"Failed to extract content: {extract_error}",
                "file_type": detected_ext or file_extension,
            }), 400

        if content is None:
            logger.warning("Could not extract content from file: %s", file_extension)
            return jsonify({
                "error": "Unsupported file type or failed to extract content",
                "file_type": detected_ext or file_extension,
                "supported_types": SUPPORTED_EXTENSIONS,
            }), 400

        logger.info(
            "Successfully extracted %s file, length: %s",
            detected_ext or file_extension,
            len(content),
        )
        return jsonify({
            "success": True,
            "content": content,
            "file_type": detected_ext or file_extension,
            "content_length": len(content),
        }), 200

    except Exception as exc:
        logger.error("Unexpected error in extract endpoint: %s", exc, exc_info=True)
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except Exception as exc:
                logger.warning("Failed to delete temp file %s: %s", file_path, exc)


@extraction_bp.route("/extract-base64", methods=["POST"])
@limiter.limit("30 per minute")
@require_api_key
def extract_base64():
    """Extract content from base64-encoded file data."""
    file_path = None
    try:
        data = request.get_json() or {}
        base64_input = data.get("base64")
        filename = data.get("filename")
        content_type = data.get("contentType")

        if not base64_input or not isinstance(base64_input, str):
            logger.warning("Extraction request without valid base64 payload")
            return jsonify({"error": 'Missing base64 data. Provide "base64" in JSON body.'}), 400

        file_path, file_extension, error = decode_base64_to_temp_file(
            base64_input,
            filename=filename,
            content_type=content_type,
        )
        if error:
            return jsonify({"error": error}), 400

        content, detected_ext, extract_error = try_extract_with_fallback(file_path, file_extension)

        if extract_error:
            logger.error("Base64 extraction failed: %s", extract_error)
            return jsonify({
                "error": f"Failed to extract content: {extract_error}",
                "file_type": detected_ext or file_extension,
            }), 400

        if content is None:
            return jsonify({
                "error": "Unsupported file type or failed to extract content",
                "file_type": detected_ext or file_extension,
                "supported_types": SUPPORTED_EXTENSIONS,
            }), 400

        return jsonify({
            "success": True,
            "content": content,
            "file_type": detected_ext or file_extension,
            "content_length": len(content),
        }), 200

    except Exception as exc:
        logger.error("Unexpected error in extract-base64 endpoint: %s", exc, exc_info=True)
        return jsonify({"error": "Internal server error"}), 500
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except Exception as exc:
                logger.warning("Failed to delete temp file %s: %s", file_path, exc)
