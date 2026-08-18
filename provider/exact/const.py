"""Exact Online connection constants (mirrors Backend provider/exact/const.ts)."""
import os

EXACT_API_BASE_URL = os.environ.get(
    "EXACT_API_BASE_URL",
    "https://start.exactonline.nl/api",
).rstrip("/")
EXACT_TOKEN_URL = os.environ.get(
    "EXACT_TOKEN_URL",
    f"{EXACT_API_BASE_URL}/oauth2/token",
)
EXACT_CLIENT_ID = os.environ.get("EXACT_CLIENT_ID", "")
EXACT_CLIENT_SECRET = os.environ.get("EXACT_CLIENT_SECRET", "")
EXACT_API_MAX_RETRIES = 3
EXACT_DOCUMENT_API_MIN_INTERVAL_MS = 900
DOCUMENT_PROCESSING_API_DELAY_MS = 800
