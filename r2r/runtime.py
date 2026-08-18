"""Per-task environment (dev/prod) for Supabase URL + service-role key."""
from contextvars import ContextVar

_current_environment: ContextVar[str] = ContextVar("r2r_environment", default="prod")


def set_environment(environment: str) -> None:
    env = (environment or "prod").strip().lower()
    if env not in ("dev", "prod"):
        raise ValueError(f"environment must be 'dev' or 'prod', got: {environment!r}")
    _current_environment.set(env)


def get_environment() -> str:
    return _current_environment.get()
