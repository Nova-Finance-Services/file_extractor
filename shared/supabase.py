"""Supabase project URL resolution (dev vs prod)."""
import os

DEV_SUPABASE_FUNCTIONS_URL = os.environ.get("DEV_SUPABASE_FUNCTIONS_URL", "")
PROD_SUPABASE_FUNCTIONS_URL = os.environ.get("PROD_SUPABASE_FUNCTIONS_URL", "")
VALID_ENVIRONMENTS = frozenset({"dev", "prod"})


def resolve_supabase_functions_url(environment: str) -> str:
    """Return Supabase project base URL for dev or prod (no trailing slash)."""
    env = (environment or "").strip().lower()
    if env == "dev":
        return DEV_SUPABASE_FUNCTIONS_URL.rstrip("/")
    if env == "prod":
        return PROD_SUPABASE_FUNCTIONS_URL.rstrip("/")
    raise ValueError(f"environment must be 'dev' or 'prod', got: {environment!r}")
