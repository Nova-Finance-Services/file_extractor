"""Download remote files to a temporary local path."""
import logging
import os
import tempfile
from pathlib import Path

import requests

from fileExtraction.config import CONFIG
from fileExtraction.detection import detect_file_extension
from fileExtraction.mime import extension_from_content_type, resolve_file_extension
from fileExtraction.paths import ensure_file_extension_path

logger = logging.getLogger(__name__)


def download_file(
    url: str,
    filename: str | None = None,
    content_type_hint: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """
    Download file from URL to a temporary location with size limits.

    Returns:
        (file_path, file_extension, error_message)
    """
    try:
        response = requests.get(
            url,
            timeout=CONFIG["REQUEST_TIMEOUT"],
            stream=True,
            allow_redirects=True,
        )
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                size = int(content_length)
                if size > CONFIG["MAX_FILE_SIZE"]:
                    max_mb = CONFIG["MAX_FILE_SIZE"] / (1024 * 1024)
                    return None, None, f"File too large. Maximum size: {max_mb:.1f}MB"
            except ValueError:
                pass

        response_content_type = response.headers.get("Content-Type", "")
        file_extension = resolve_file_extension(filename, content_type_hint)

        if not file_extension:
            url_path = Path(url.split("?")[0])
            if url_path.suffix:
                file_extension = url_path.suffix.lower()

        if not file_extension:
            file_extension = extension_from_content_type(response_content_type)

        suffix = file_extension or ".tmp"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)

        downloaded = 0
        try:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    downloaded += len(chunk)
                    if downloaded > CONFIG["MAX_FILE_SIZE"]:
                        temp_file.close()
                        os.unlink(temp_file.name)
                        max_mb = CONFIG["MAX_FILE_SIZE"] / (1024 * 1024)
                        return None, None, f"File too large. Maximum size: {max_mb:.1f}MB"
                    temp_file.write(chunk)
        finally:
            temp_file.close()

        if not file_extension:
            file_extension = detect_file_extension(temp_file.name)

        final_path = ensure_file_extension_path(temp_file.name, file_extension)
        logger.info("Downloaded file: %s bytes, extension: %s", downloaded, file_extension)
        return final_path, file_extension, None

    except requests.Timeout:
        return None, None, f"Request timeout (>{CONFIG['REQUEST_TIMEOUT']}s)"
    except requests.RequestException as exc:
        logger.error("Download error: %s", exc)
        return None, None, f"Failed to download file: {exc}"
    except Exception as exc:
        logger.error("Unexpected download error: %s", exc)
        return None, None, f"Unexpected error: {exc}"
