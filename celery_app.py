"""
Celery application for background file extraction on Render.

Start worker locally:
  celery -A celery_app worker --loglevel=info

Start worker on Render (background worker service):
  celery -A celery_app worker --loglevel=info --concurrency=2
"""
import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Render Redis add-on exposes REDIS_URL; CELERY_BROKER_URL overrides if set.
BROKER_URL = os.environ.get("CELERY_BROKER_URL") or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", BROKER_URL)

celery = Celery(
    "CELERY_BROKER_URL",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["tasks"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=int(os.environ.get("CELERY_TASK_TIME_LIMIT", 300)),
    task_soft_time_limit=int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", 270)),
    worker_prefetch_multiplier=int(os.environ.get("CELERY_WORKER_PREFETCH", 1)),
    broker_connection_retry_on_startup=True,
)
