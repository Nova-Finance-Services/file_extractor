"""R2R accounting-agent enqueue route."""
import logging

from flask import Blueprint, jsonify, request

from r2r import config as r2r_config
from routes.auth import require_api_key
from routes.limiter import limiter

logger = logging.getLogger(__name__)

r2r_bp = Blueprint("r2r", __name__)


@r2r_bp.route("/r2r/accounting-agent/enqueue", methods=["POST"])
@limiter.limit("10 per minute")
@require_api_key
def r2r_accounting_agent_enqueue():
    """
    Queue R2R accounting agent jobs (Supabase cron → Celery Python worker).
    """
    data = request.get_json() or {}
    jobs = data.get("jobs") or []

    if not isinstance(jobs, list):
        return jsonify({"error": "jobs must be an array"}), 400

    environment = (data.get("environment") or "prod").strip().lower()
    if environment not in ("dev", "prod"):
        return jsonify({"error": "environment must be 'dev' or 'prod'"}), 400

    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            return jsonify({"error": f"jobs[{index}] must be an object"}), 400
        if not str(job.get("organization_id") or "").strip():
            return jsonify({"error": f"jobs[{index}].organization_id is required"}), 400
        event_type = str(job.get("event_type") or "").strip()
        if event_type not in r2r_config.VALID_EVENT_TYPES:
            return jsonify({
                "error": f"jobs[{index}].event_type must be one of: {', '.join(sorted(r2r_config.VALID_EVENT_TYPES))}",
            }), 400
        if not str(job.get("occurred_at") or "").strip():
            return jsonify({"error": f"jobs[{index}].occurred_at is required"}), 400

    request_id = data.get("request_id")

    if len(jobs) == 0:
        return jsonify({
            "success": True,
            "message": "No accounting agent jobs to enqueue",
            "task_id": "no_jobs",
            "request_id": request_id,
            "environment": environment,
            "job_count": 0,
        }), 202

    payload_base = {
        "request_id": request_id,
        "environment": environment,
    }

    try:
        from tasks import process_accounting_agent_job

        task_ids: list[str] = []
        for job in jobs:
            async_result = process_accounting_agent_job.delay({
                **payload_base,
                "job": job,
            })
            task_ids.append(async_result.id)
    except Exception as exc:
        logger.error("Failed to enqueue accounting agent jobs: %s", exc, exc_info=True)
        return jsonify({
            "error": "Failed to enqueue task. Check CELERY_BROKER_URL / REDIS_URL and worker.",
            "details": str(exc),
        }), 503

    logger.info(
        "Enqueued accounting agent jobs task_ids=%s request_id=%s env=%s jobs=%s",
        task_ids,
        request_id,
        environment,
        len(jobs),
    )
    return jsonify({
        "success": True,
        "message": "R2R accounting agent jobs queued",
        "task_id": task_ids[0],
        "task_ids": task_ids,
        "request_id": request_id,
        "environment": environment,
        "job_count": len(jobs),
    }), 202
