"""Run R2R accounting agent jobs in the Celery worker."""
from __future__ import annotations

import logging
from typing import Any

from r2r.accounting_agent.run import execute_accounting_agent_run
from r2r.config import VALID_EVENT_TYPES
from r2r.jobs import normalize_accounting_agent_job
from r2r.runtime import set_environment

logger = logging.getLogger(__name__)


def _validate_job(job: Any, index: int | None = None) -> str | None:
    prefix = f"jobs[{index}]" if index is not None else "job"
    if not isinstance(job, dict):
        return f"{prefix} must be an object"
    if not str(job.get("organization_id") or "").strip():
        return f"{prefix}.organization_id is required"
    event_type = str(job.get("event_type") or "").strip()
    if event_type not in VALID_EVENT_TYPES:
        return f"{prefix}.event_type must be one of: {', '.join(sorted(VALID_EVENT_TYPES))}"
    if not str(job.get("occurred_at") or "").strip():
        return f"{prefix}.occurred_at is required"
    return None


def _run_one_job(job: dict[str, Any]) -> dict[str, Any]:
    job = normalize_accounting_agent_job(job)
    event: dict[str, Any] = {
        "event_type": str(job["event_type"]).strip(),
        "organization_id": str(job["organization_id"]).strip(),
        "occurred_at": str(job["occurred_at"]).strip(),
    }
    if job.get("business_event_type"):
        event["business_event_type"] = job["business_event_type"]
    if isinstance(job.get("payload"), dict) and job["payload"]:
        event["payload"] = job["payload"]

    result = execute_accounting_agent_run(event, {"dry_run": bool(job.get("dry_run"))})
    return {
        "organization_id": event["organization_id"],
        "event_type": event["event_type"],
        "success": bool(result.get("success", True)),
        "body": result,
    }


def run_accounting_agent_job(payload: dict[str, Any]) -> dict[str, Any]:
    """
    One organization close job.

    Payload: { request_id, environment, job: {...} }
    """
    request_id = payload.get("request_id") or "unknown"
    environment = (payload.get("environment") or "prod").strip().lower()
    job = payload.get("job")
    set_environment(environment)

    validation_error = _validate_job(job)
    if validation_error:
        raise ValueError(validation_error)

    logger.info(
        "run_accounting_agent_job request_id=%s environment=%s org=%s event_type=%s",
        request_id,
        environment,
        job.get("organization_id"),
        job.get("event_type"),
    )
    result = _run_one_job(job)
    logger.info(
        "accounting agent done request_id=%s org=%s event_type=%s success=%s",
        request_id,
        result.get("organization_id"),
        result.get("event_type"),
        result.get("success"),
    )
    return {
        "request_id": request_id,
        "environment": environment,
        **result,
    }


def run_accounting_agent_jobs(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Legacy sequential runner for a jobs array (old Celery messages).
    Failures are recorded; remaining orgs still run.
    """
    request_id = payload.get("request_id") or "unknown"
    environment = (payload.get("environment") or "prod").strip().lower()
    jobs = payload.get("jobs") or []
    if not isinstance(jobs, list):
        raise ValueError("payload.jobs must be an array")

    set_environment(environment)

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    logger.info(
        "run_accounting_agent_jobs request_id=%s environment=%s job_count=%s",
        request_id,
        environment,
        len(jobs),
    )

    for index, job in enumerate(jobs):
        validation_error = _validate_job(job, index)
        if validation_error:
            errors.append(validation_error)
            results.append({"index": index, "success": False, "error": validation_error})
            continue
        try:
            result = _run_one_job(job)
            results.append(result)
        except Exception as exc:
            error_message = str(exc)
            errors.append(error_message)
            results.append({
                "organization_id": job.get("organization_id"),
                "event_type": job.get("event_type"),
                "success": False,
                "error": error_message,
            })
            logger.error(
                "accounting agent failed request_id=%s org=%s event_type=%s: %s",
                request_id,
                job.get("organization_id"),
                job.get("event_type"),
                exc,
            )

    return {
        "request_id": request_id,
        "environment": environment,
        "job_count": len(jobs),
        "success_count": sum(1 for row in results if row.get("success")),
        "error_count": len(errors),
        "results": results,
    }
