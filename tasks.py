"""
Celery tasks for background work.

Enqueue example:
  from tasks import process_item

  task = process_item.delay("abc-123")
  print(task.id)
"""
import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(bind=True, name="tasks.process_item")
def process_item(self, item_id):
    """
    Example task: receive an id and log it.

    Replace this with your real background logic later.
    """
    print(f"[process_item] task_id={self.request.id} item_id={item_id}")
    logger.info("process_item task_id=%s item_id=%s", self.request.id, item_id)

    return {
        "status": "ok",
        "task_id": self.request.id,
        "item_id": item_id,
    }
