"""URL validation for safe remote file downloads."""
import logging
from urllib.parse import urlparse

from fileExtraction.config import CONFIG

logger = logging.getLogger(__name__)


def validate_url(url: str) -> tuple[bool, str | None]:
    """Validate URL to prevent SSRF attacks."""
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string"

    if len(url) > 2048:
        return False, "URL too long (max 2048 characters)"

    try:
        parsed = urlparse(url)

        if parsed.scheme not in CONFIG["ALLOWED_SCHEMES"]:
            return False, f"Only {', '.join(CONFIG['ALLOWED_SCHEMES'])} URLs are allowed"

        host = parsed.hostname
        if not host:
            return False, "Invalid URL: missing hostname"

        if host.lower() in CONFIG["BLOCKED_HOSTS"]:
            return False, "Internal URLs are not allowed"

        host_lower = host.lower()
        private_prefixes = (
            "10.",
            "192.168.",
            "172.16.",
            "172.17.",
            "172.18.",
            "172.19.",
            "172.20.",
            "172.21.",
            "172.22.",
            "172.23.",
            "172.24.",
            "172.25.",
            "172.26.",
            "172.27.",
            "172.28.",
            "172.29.",
            "172.30.",
            "172.31.",
        )
        if any(host_lower.startswith(prefix) for prefix in private_prefixes):
            return False, "Private IP addresses are not allowed"

        return True, None
    except Exception as exc:
        logger.error("URL validation error: %s", exc)
        return False, f"Invalid URL format: {exc}"
