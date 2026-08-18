"""Exact Documents API (attachments + body updates) used by chatbot processing."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Optional
from urllib.parse import unquote

import requests

from fileExtraction.mime import content_type_from_filename
from provider.exact.const import (
    DOCUMENT_PROCESSING_API_DELAY_MS,
    EXACT_API_MAX_RETRIES,
    EXACT_DOCUMENT_API_MIN_INTERVAL_MS,
)
from provider.exact.odata import exact_v1, odata_results

logger = logging.getLogger(__name__)

_RATE_LIMIT_STATUSES = {429, 503}
_pace_lock = threading.Lock()
_last_request_completed_at = 0.0


def _with_download_flag(url: str) -> str:
    if not url:
        return url
    if re.search(r"[?&]Download=1(?:&|$)", url, re.I):
        return url
    return f"{url}{'&' if '?' in url else '?'}Download=1"


def _filename_from_content_disposition(disposition: str) -> Optional[str]:
    utf_match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
    if utf_match:
        try:
            return unquote(utf_match.group(1))
        except Exception:
            return utf_match.group(1)
    simple_match = re.search(r'filename="?([^";]+)"?', disposition, re.I)
    return simple_match.group(1) if simple_match else None


def _retry_after_ms(response: requests.Response) -> Optional[int]:
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw.isdigit():
        return None
    return min(int(raw) * 1000, 120_000)


def _pace_before_request() -> None:
    global _last_request_completed_at
    min_gap_ms = EXACT_DOCUMENT_API_MIN_INTERVAL_MS
    with _pace_lock:
        elapsed_ms = (time.monotonic() - _last_request_completed_at) * 1000
        if _last_request_completed_at > 0 and elapsed_ms < min_gap_ms:
            time.sleep((min_gap_ms - elapsed_ms) / 1000)


def _mark_request_completed() -> None:
    global _last_request_completed_at
    with _pace_lock:
        _last_request_completed_at = time.monotonic()


class ExactClient:
    """Authenticated Exact client for document attachment download and body updates."""

    def __init__(self, access_token: str, division: int):
        self.access_token = access_token
        self.division = division
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    def _documents_endpoint(self) -> str:
        return exact_v1("documents/Documents", self.division)

    def _attachments_bulk_endpoint(self) -> str:
        return exact_v1("bulk/Documents/DocumentAttachments", self.division)

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        label: str,
        expect_json: bool = True,
        **kwargs,
    ) -> requests.Response:
        max_retries = EXACT_API_MAX_RETRIES
        default_retry_ms = 10_000
        timeout = kwargs.pop("timeout", 60)

        for attempt in range(max_retries + 1):
            _pace_before_request()
            try:
                response = requests.request(method, url, timeout=timeout, **kwargs)
            finally:
                _mark_request_completed()

            if response.ok or response.status_code not in _RATE_LIMIT_STATUSES:
                if not response.ok and expect_json:
                    logger.warning(
                        "Exact API %s %s %s: %s",
                        label,
                        method,
                        response.status_code,
                        response.text[:200],
                    )
                return response

            if attempt >= max_retries:
                return response

            wait_ms = _retry_after_ms(response) or min(default_retry_ms * (attempt + 1), 60_000)
            logger.warning(
                "Exact API %s rate limited %s — wait %sms (retry %s/%s)",
                label,
                response.status_code,
                wait_ms,
                attempt + 1,
                max_retries,
            )
            time.sleep(wait_ms / 1000)

        return response

    def download_attachment(self, url: str) -> tuple[bytes, Optional[str], Optional[str]]:
        response = self._request_with_retry(
            "GET",
            _with_download_flag(url),
            label="Attachment download",
            expect_json=False,
            headers={**self._headers, "Accept": "*/*"},
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip() or None
        file_name = _filename_from_content_disposition(
            response.headers.get("Content-Disposition", "")
        )
        return response.content, content_type, file_name

    def fetch_attachments_for_document(self, document_id: str) -> list[dict[str, Any]]:
        params = {
            "$select": "Url,FileName",
            "$filter": f"Document eq guid'{document_id}'",
            "$top": "1000",
        }
        response = self._request_with_retry(
            "GET",
            exact_v1("documents/DocumentAttachments", self.division),
            label="DocumentAttachments",
            headers=self._headers,
            params=params,
        )
        response.raise_for_status()
        return self._normalize_attachment_rows(odata_results(response.json()))

    def fetch_attachments_bulk(self, document_ids: list[str], chunk_size: int = 12) -> dict[str, list[dict]]:
        by_doc: dict[str, list[dict]] = {doc_id: [] for doc_id in document_ids}
        unique_ids = list(dict.fromkeys(doc_id.strip() for doc_id in document_ids if doc_id.strip()))
        if not unique_ids:
            return by_doc

        for index in range(0, len(unique_ids), chunk_size):
            chunk = unique_ids[index : index + chunk_size]
            filter_expr = " or ".join(f"Document eq guid'{doc_id}'" for doc_id in chunk)
            params = {"$select": "Document,Url,FileName", "$filter": filter_expr, "$top": "1000"}
            response = self._request_with_retry(
                "GET",
                self._attachments_bulk_endpoint(),
                label="DocumentAttachments bulk",
                headers=self._headers,
                params=params,
            )
            response.raise_for_status()
            for row in odata_results(response.json()):
                doc_id = str(row.get("Document") or "").strip()
                if not doc_id:
                    continue
                by_doc.setdefault(doc_id, []).extend(self._normalize_attachment_rows([row]))
            if DOCUMENT_PROCESSING_API_DELAY_MS > 0:
                time.sleep(DOCUMENT_PROCESSING_API_DELAY_MS / 1000)

        return by_doc

    def count_unprocessed_documents(self, type_ids: list[int]) -> int:
        if not type_ids:
            return 0
        type_filter = "(" + " or ".join(f"Type eq {type_id}" for type_id in type_ids) + ")"
        filter_expr = f"{type_filter} and (Body eq null or Body eq '')"
        params = {
            "$select": "ID",
            "$inlinecount": "allpages",
            "$top": "1",
            "$filter": filter_expr,
        }
        response = self._request_with_retry(
            "GET",
            self._documents_endpoint(),
            label="Documents count",
            headers=self._headers,
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        payload = data.get("d")
        if isinstance(payload, dict):
            count = payload.get("__count", 0)
            try:
                return int(count)
            except (TypeError, ValueError):
                return 0
        return 0

    def update_document_body(self, document_id: str, body_json: dict) -> None:
        url = f"{self._documents_endpoint()}(guid'{document_id}')"
        payload = {"ID": document_id, "Body": json.dumps(body_json)}
        response = self._request_with_retry(
            "PUT",
            url,
            label="Documents body PUT",
            headers={**self._headers, "Content-Type": "application/json"},
            json=payload,
        )
        if not response.ok:
            raise RuntimeError(
                f"Failed to update document body: {response.status_code} {response.text[:300]}"
            )

    def _normalize_attachment_rows(self, rows: list[dict]) -> list[dict]:
        normalized = []
        seen_urls = set()
        for row in rows:
            raw_url = (row.get("UrlDownload") or row.get("Url") or "").strip()
            url = _with_download_flag(raw_url) if raw_url else ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            file_name = row.get("FileName")
            normalized.append({
                "url": url,
                "file_name": file_name,
                "content_type": content_type_from_filename(
                    file_name if isinstance(file_name, str) else None
                ),
            })
        return normalized
