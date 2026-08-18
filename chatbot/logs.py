"""Persist document processing logs via Supabase edge function."""
import logging
from typing import Any

import requests

from chatbot.config import FILE_EXTRACTOR_KEY, resolve_supabase_functions_url

logger = logging.getLogger(__name__)

LOG_FUNCTION_PATH = "/functions/v1/chatbot-document-processing-log"


def log_organization_run(
    request_id: str,
    org_log: dict[str, Any],
    batch_size: int,
    duration_ms: int,
    environment: str,
) -> None:
    api_key = FILE_EXTRACTOR_KEY

    try:
        base_url = resolve_supabase_functions_url(environment)
    except ValueError as exc:
        logger.error("Invalid environment for logging: %s", exc)
        return

    if not base_url or not api_key:
        logger.warning(
            "Supabase functions URL for %s or FILE_EXTRACTOR_KEY not configured; skipping log",
            environment,
        )
        return

    payload = {
        "request_id": request_id,
        "batch_size": batch_size,
        "duration_ms": duration_ms,
        "environment": environment,
        "organization": {
            "organization_id": org_log.get("organization_id"),
            "processed_count": org_log.get("processed_count", 0),
            "failed_count": org_log.get("failed_count", 0),
            "skipped_count": org_log.get("skipped_count", 0),
            "remaining_unprocessed_count": org_log.get("remaining_unprocessed_count", 0),
            "document_type_ids": org_log.get("document_type_ids") or [],
            "errors": org_log.get("errors") or None,
            "skipped": org_log.get("skipped") or None,
        },
    }

    url = f"{base_url}{LOG_FUNCTION_PATH}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if not response.ok:
            logger.error(
                "Failed document-processing-log env=%s org=%s: %s %s",
                environment,
                org_log.get("organization_id"),
                response.status_code,
                response.text[:300],
            )
    except requests.RequestException as exc:
        logger.error(
            "Failed document-processing-log env=%s org=%s: %s",
            environment,
            org_log.get("organization_id"),
            exc,
        )
