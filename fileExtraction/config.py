"""Shared configuration for file extraction."""
import os
from functools import lru_cache


@lru_cache()
def get_config():
    """Load configuration from environment variables."""
    return {
        "MAX_FILE_SIZE": 50 * 1024 * 1024,
        "REQUEST_TIMEOUT": 30,
        "ALLOWED_SCHEMES": ["http", "https"],
        "BLOCKED_HOSTS": [
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "::1",
            "169.254.169.254",
        ],
        "FILE_EXTRACTOR_KEY": os.environ.get("FILE_EXTRACTOR_KEY", ""),
    }


CONFIG = get_config()
