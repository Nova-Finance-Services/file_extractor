"""Orchestrate chatbot document processing for one organization batch."""
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from chatbot.config import (
    DOCUMENT_PROCESSING_API_DELAY_MS,
    DOCUMENT_PROCESSING_COUNT_REMAINING,
    VALID_ENVIRONMENTS,
)
from chatbot.exact_client import ExactClient
from chatbot.extraction import extract_text_from_bytes
from chatbot.logs import log_organization_run
from chatbot.summarization import summarize_attachment_text

logger = logging.getLogger(__name__)


def classify_document_category(type_description: Optional[str]) -> str:
    normalized = re.sub(r"\s+", " ", (type_description or "").strip().lower())
    if "purchase" in normalized and "invoice" in normalized:
        return "purchase_invoice"
    if "purchase" in normalized and "order" in normalized:
        return "purchase_order"
    if "invoice" in normalized:
        return "sales_invoice"
    if "sales" in normalized and "order" in normalized:
        return "sales_order"
    if "order" in normalized:
        return "sales_order"
    return "other"


def _is_body_empty(body: Any) -> bool:
    if body is None:
        return True
    if isinstance(body, str):
        return body.strip() == ""
    return False


def process_single_document(
    exact: ExactClient,
    document: dict[str, Any],
    prefetched_attachments: Optional[list[dict]] = None,
) -> dict[str, Any]:
    document_id = str(document.get("id") or document.get("ID") or "").strip()
    if not document_id:
        return {"success": False, "reason": "missing_document_id"}

    if not _is_body_empty(document.get("body") or document.get("Body")):
        return {"success": True, "skipped": True, "reason": "body_already_set"}

    type_description = document.get("type_description") or document.get("TypeDescription")
    document_category = classify_document_category(
        type_description if isinstance(type_description, str) else None
    )

    attachments = prefetched_attachments or exact.fetch_attachments_for_document(document_id)
    if not attachments:
        return {"success": False, "reason": "no_attachments"}

    extracted_chunks = []
    for attachment in attachments:
        url = attachment.get("url") or ""
        file_name = attachment.get("file_name") or attachment.get("fileName")
        content_type = attachment.get("content_type") or attachment.get("contentType")

        try:
            file_bytes, header_type, header_name = exact.download_attachment(url)
            if header_name and not file_name:
                file_name = header_name
            if header_type and (not content_type or content_type == "application/octet-stream"):
                content_type = header_type
            extracted = extract_text_from_bytes(file_bytes, file_name, content_type)
        except Exception as exc:
            logger.warning(
                "Attachment download/extract failed document=%s file=%s: %s",
                document_id,
                file_name,
                exc,
            )
            extracted = ""

        if not extracted.strip():
            continue
        label = (file_name or "attachment").strip()
        extracted_chunks.append(f"--- {label} ---\n{extracted.strip()}")

    if not extracted_chunks:
        return {"success": False, "reason": "attachment_text_empty"}

    combined_text = "\n\n".join(extracted_chunks)
    summary = summarize_attachment_text(combined_text, document_category)
    if not summary:
        return {"success": False, "reason": "summary_failed"}

    body_json = {
        "source": "chatbot-document-processing-cron",
        "schema_version": 1,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "document_type_id": document.get("type") or document.get("Type"),
        "document_type_description": type_description,
        "document_category": document_category,
        "attachment_summaries": [
            {"file_name": att.get("file_name") or att.get("fileName"), "summary": summary["combined_summary"]}
            for att in attachments
        ],
        "combined_summary": summary["combined_summary"],
        "key_points": summary["key_points"],
    }

    exact.update_document_body(document_id, body_json)
    return {"success": True, "body": body_json}


def _finalize_org_log(
    request_id: str,
    org_log: dict[str, Any],
    batch_size: int,
    environment: str,
    start_time: float,
    exact: Optional[ExactClient] = None,
) -> dict[str, Any]:
    if exact and DOCUMENT_PROCESSING_COUNT_REMAINING and org_log.get("document_type_ids"):
        try:
            org_log["remaining_unprocessed_count"] = exact.count_unprocessed_documents(
                org_log["document_type_ids"]
            )
        except Exception as exc:
            logger.warning(
                "Failed remaining_unprocessed_count org=%s: %s",
                org_log.get("organization_id"),
                exc,
            )
            org_log["errors"].append(f"remaining_count_failed:{exc}")

    duration_ms = int((time.time() - start_time) * 1000)
    log_organization_run(request_id, org_log, batch_size, duration_ms, environment)
    return org_log


def process_organization_batch(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = payload.get("request_id") or ""
    batch_size = int(payload.get("batch_size") or 20)
    environment = (payload.get("environment") or "prod").strip().lower()
    organization = payload.get("organization") or {}
    documents = payload.get("documents") or []
    start = time.time()

    org_log = {
        "organization_id": organization.get("organization_id") or "",
        "processed_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "remaining_unprocessed_count": 0,
        "document_type_ids": organization.get("document_type_ids") or [],
        "errors": [],
        "skipped": [],
    }

    if environment not in VALID_ENVIRONMENTS:
        org_log["failed_count"] = len(documents)
        org_log["errors"].append(f"invalid_environment:{environment}")
        return _finalize_org_log(request_id, org_log, batch_size, environment, start)

    organization_id = org_log["organization_id"]
    access_token = organization.get("access_token") or ""
    division = organization.get("division")

    if not organization_id or not access_token or division is None:
        org_log["errors"].append("invalid_organization_connection")
        org_log["failed_count"] = len(documents)
        return _finalize_org_log(request_id, org_log, batch_size, environment, start)

    exact = ExactClient(access_token=access_token, division=int(division))

    for index, document in enumerate(documents):
        document_id = str(document.get("id") or document.get("ID") or "unknown")
        attachments = document.get("attachments")
        try:
            result = process_single_document(
                exact,
                document,
                prefetched_attachments=attachments if isinstance(attachments, list) else None,
            )
            if result.get("skipped"):
                org_log["skipped_count"] += 1
                org_log["skipped"].append(f"{document_id}:{result.get('reason', 'skipped')}")
            elif result.get("success"):
                org_log["processed_count"] += 1
                logger.info(
                    "[chatbot] processed organization=%s document=%s",
                    organization_id,
                    document_id,
                )
            else:
                org_log["failed_count"] += 1
                org_log["errors"].append(f"{document_id}:{result.get('reason', 'unknown')}")
        except Exception as exc:
            org_log["failed_count"] += 1
            org_log["errors"].append(f"{document_id}:{exc}")
            logger.exception(
                "[chatbot] failed organization=%s document=%s",
                organization_id,
                document_id,
            )

        if DOCUMENT_PROCESSING_API_DELAY_MS > 0 and index < len(documents) - 1:
            time.sleep(DOCUMENT_PROCESSING_API_DELAY_MS / 1000)

    return _finalize_org_log(
        request_id, org_log, batch_size, environment, start, exact=exact
    )
