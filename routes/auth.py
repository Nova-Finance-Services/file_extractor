"""Bearer API-key decorator used by all protected routes."""
import logging
from functools import wraps

from flask import jsonify, request

from fileExtraction import CONFIG

logger = logging.getLogger(__name__)


def require_api_key(f):
    """Decorator to require API key authentication."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = CONFIG.get("FILE_EXTRACTOR_KEY", "")

        if not api_key:
            logger.warning("No API key configured. Authentication disabled.")
            return f(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            logger.warning("Missing Authorization header")
            return jsonify({
                "error": "Missing Authorization header. Please provide API key in Authorization header.",
            }), 401

        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:]
        else:
            provided_key = auth_header

        if provided_key != api_key:
            logger.warning("Invalid API key attempt from %s", request.remote_addr)
            return jsonify({"error": "Invalid API key"}), 401

        return f(*args, **kwargs)

    return decorated_function
