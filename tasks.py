"""
Celery tasks for background work.
"""
import logging

from celery_app import celery
from chatbot.config import CHATBOT_TASK_SOFT_TIME_LIMIT, CHATBOT_TASK_TIME_LIMIT
from r2r.config import (
    ACCOUNTING_AGENT_TASK_SOFT_TIME_LIMIT,
    ACCOUNTING_AGENT_TASK_TIME_LIMIT,
)

logger = logging.getLogger(__name__)


@celery.task(bind=True, name="tasks.process_item")
def process_item(self, item_id):
    """Example task (kept for worker smoke tests)."""
    print(f"[process_item] task_id={self.request.id} item_id={item_id}")
    logger.info("process_item task_id=%s item_id=%s", self.request.id, item_id)
    return {"status": "ok", "task_id": self.request.id, "item_id": item_id}


@celery.task(
    bind=True,
    name="tasks.process_chatbot_documents",
    time_limit=CHATBOT_TASK_TIME_LIMIT,
    soft_time_limit=CHATBOT_TASK_SOFT_TIME_LIMIT,
)
def process_chatbot_documents(self, payload: dict):
    """
    Process a batch of Exact documents: attachments → extract → summarize → update body.
    """
    from chatbot.processing import process_organization_batch

    request_id = payload.get("request_id")
    organization_id = (payload.get("organization") or {}).get("organization_id")
    logger.info(
        "process_chatbot_documents task_id=%s request_id=%s organization_id=%s documents=%s",
        self.request.id,
        request_id,
        organization_id,
        len(payload.get("documents") or []),
    )
    org_log = process_organization_batch(payload)
    return {
        "status": "ok",
        "task_id": self.request.id,
        "request_id": request_id,
        "organization_log": org_log,
    }


@celery.task(
    bind=True,
    name="tasks.process_accounting_agent_job",
    time_limit=ACCOUNTING_AGENT_TASK_TIME_LIMIT,
    soft_time_limit=ACCOUNTING_AGENT_TASK_SOFT_TIME_LIMIT,
)
def process_accounting_agent_job(self, payload: dict):
    """Run one org close job (one Celery task per organization)."""
    from r2r.processing import run_accounting_agent_job

    request_id = payload.get("request_id")
    job = payload.get("job") or {}
    logger.info(
        "process_accounting_agent_job task_id=%s request_id=%s org=%s event_type=%s",
        self.request.id,
        request_id,
        job.get("organization_id"),
        job.get("event_type"),
    )
    result = run_accounting_agent_job(payload)
    return {
        "status": "ok",
        "task_id": self.request.id,
        "request_id": request_id,
        **result,
    }


@celery.task(
    bind=True,
    name="tasks.process_accounting_agent_jobs",
    time_limit=ACCOUNTING_AGENT_TASK_TIME_LIMIT,
    soft_time_limit=ACCOUNTING_AGENT_TASK_SOFT_TIME_LIMIT,
)
def process_accounting_agent_jobs(self, payload: dict):
    """
    Legacy batch task. Prefer process_accounting_agent_job (one org per task).
    Kept so in-flight Redis messages from the old enqueue path still run.
    """
    from r2r.processing import run_accounting_agent_jobs

    request_id = payload.get("request_id")
    jobs = payload.get("jobs") or []
    logger.info(
        "process_accounting_agent_jobs (legacy batch) task_id=%s request_id=%s jobs=%s",
        self.request.id,
        request_id,
        len(jobs),
    )
    summary = run_accounting_agent_jobs(payload)
    return {
        "status": "ok",
        "task_id": self.request.id,
        **summary,
    }
