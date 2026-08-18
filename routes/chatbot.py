"""Chatbot Exact-document processing enqueue route."""
import logging

from flask import Blueprint, jsonify, request

from routes.auth import require_api_key
from routes.limiter import limiter

logger = logging.getLogger(__name__)

chatbot_bp = Blueprint("chatbot", __name__)


@chatbot_bp.route("/chatbot-document-processing", methods=["POST"])
@limiter.limit("10 per minute")
@require_api_key
def chatbot_document_processing():
    """
    Queue chatbot document processing (Exact attachments → extract → summarize → update body).
    """
    data = request.get_json() or {}
    organization = data.get("organization") or {}
    documents = data.get("documents") or []

    if not organization.get("organization_id"):
        return jsonify({"error": "organization.organization_id is required"}), 400
    if not organization.get("access_token") or organization.get("division") is None:
        return jsonify({"error": "organization.access_token and organization.division are required"}), 400
    if not isinstance(documents, list) or len(documents) == 0:
        return jsonify({"error": "documents must be a non-empty array"}), 400

    environment = (data.get("environment") or "prod").strip().lower()
    if environment not in ("dev", "prod"):
        return jsonify({"error": "environment must be 'dev' or 'prod'"}), 400

    valid_documents = [
        doc for doc in documents
        if isinstance(doc, dict) and str(doc.get("id") or "").strip()
    ]
    if not valid_documents:
        return jsonify({"error": "documents must include at least one entry with a non-empty id"}), 400

    payload = {
        "request_id": data.get("request_id"),
        "environment": environment,
        "batch_size": data.get("batch_size", 20),
        "organization": organization,
        "documents": valid_documents,
    }

    try:
        from tasks import process_chatbot_documents

        async_result = process_chatbot_documents.delay(payload)
    except Exception as exc:
        logger.error("Failed to enqueue chatbot document processing: %s", exc, exc_info=True)
        return jsonify({
            "error": "Failed to enqueue task. Check CELERY_BROKER_URL / REDIS_URL and worker.",
            "details": str(exc),
        }), 503

    logger.info(
        "Enqueued chatbot document processing task_id=%s request_id=%s env=%s org=%s docs=%s",
        async_result.id,
        payload.get("request_id"),
        environment,
        organization.get("organization_id"),
        len(valid_documents),
    )
    return jsonify({
        "success": True,
        "message": "Chatbot document processing queued",
        "task_id": async_result.id,
        "request_id": payload.get("request_id"),
        "environment": environment,
        "documents_queued": len(valid_documents),
    }), 202
