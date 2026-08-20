"""Environment configuration for R2R accounting agent jobs."""
import os

from r2r.runtime import get_environment
from shared.supabase import resolve_supabase_functions_url

ORG_JOB_GAP_SECONDS = 1.0
SUPPLIER_RUN_GAP_SECONDS = 0.75
VALID_EVENT_TYPES = frozenset({"month_start", "month_end"})

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_MODEL_COMPLEX =os.environ.get("OPENAI_MODEL_COMPLEX", "gpt-5.4") 
OPENAI_MODEL_MEDIUM = os.environ.get("OPENAI_MODEL_MEDIUM", "gpt-5-mini")
CLAUDE_MODEL_COMPLEX = "claude-opus-4-8"
CLAUDE_MODEL_MEDIUM = "claude-sonnet-4-6"
ACCOUNTING_AGENT_TASK_TIME_LIMIT = 7200
ACCOUNTING_AGENT_TASK_SOFT_TIME_LIMIT = 6900

ACCOUNTING_AGENT_NAME = "r2r.accounting-agent"
DEFAULT_ACCOUNTING_MIN_THRESHOLD = 50
DEFAULT_ACCOUNTING_MAX_THRESHOLD = 50000
DEFAULT_MONTH_START_RUN_DAYS = [1, 2, 3]
DEFAULT_MONTH_END_OFFSET_DAYS = [0]
DEFAULT_GL_ACCOUNTS = {
    "cost_gl_account_code": "6000",
    "accrued_cost_gl_account_code": "2100",
    "prepaid_gl_account_code": "1600",
}


def resolve_supabase_url(environment: str | None = None) -> str:
    return resolve_supabase_functions_url(environment or get_environment())


def resolve_supabase_service_role_key(environment: str | None = None) -> str:
    env = (environment or get_environment()).strip().lower()
    if env == "dev":
        return (
            os.environ.get("DEV_SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ).strip()
    return (
        os.environ.get("PROD_SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    ).strip()


__all__ = [
    "ACCOUNTING_AGENT_NAME",
    "ACCOUNTING_AGENT_TASK_SOFT_TIME_LIMIT",
    "ACCOUNTING_AGENT_TASK_TIME_LIMIT",
    "ANTHROPIC_API_KEY",
    "CLAUDE_MODEL_COMPLEX",
    "CLAUDE_MODEL_MEDIUM",
    "DEFAULT_ACCOUNTING_MAX_THRESHOLD",
    "DEFAULT_ACCOUNTING_MIN_THRESHOLD",
    "DEFAULT_GL_ACCOUNTS",
    "DEFAULT_MONTH_END_OFFSET_DAYS",
    "DEFAULT_MONTH_START_RUN_DAYS",
    "OPENAI_API_KEY",
    "OPENAI_MODEL_COMPLEX",
    "OPENAI_MODEL_MEDIUM",
    "ORG_JOB_GAP_SECONDS",
    "SUPPLIER_RUN_GAP_SECONDS",
    "VALID_EVENT_TYPES",
    "resolve_supabase_functions_url",
    "resolve_supabase_service_role_key",
    "resolve_supabase_url",
]
