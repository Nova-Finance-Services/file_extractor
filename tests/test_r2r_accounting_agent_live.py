"""
Live POST to the deployed Flask enqueue API (no mocks).

This does not run in the normal suite. Opt in:

  ACCOUNTING_AGENT_LIVE=1
  FILE_EXTRACTOR_URL=https://your-flask.onrender.com
  FILE_EXTRACTOR_KEY=same-as-flask

  pytest tests/test_r2r_accounting_agent_live.py

Uses environment=dev so the Render worker talks to the dev Supabase project.
dry_run=true so Exact journals / agent_memory are not written.
"""
import os
import time
import uuid

import pytest
import requests
from dotenv import load_dotenv

from tests.test_r2r_accounting_agent import (
    ENQUEUE_PATH,
    TEST_BUSINESS_EVENT_TYPE,
    TEST_DRY_RUN,
    TEST_ENVIRONMENT,
    TEST_EVENT_TYPE,
    TEST_OCCURRED_AT,
    TEST_ORG_ID,
    TEST_SUPPLIER_IDS,
    _job,
)

load_dotenv()

pytestmark = pytest.mark.live


def _live_base_url() -> str:
    return (
        os.environ.get("FILE_EXTRACTOR_URL")
        or os.environ.get("ACCOUNTING_AGENT_FLASK_URL")
        or ""
    ).rstrip("/")


def _live_api_key() -> str:
    return (
        os.environ.get("FILE_EXTRACTOR_KEY")
        or os.environ.get("FILE_EXTRACTOR_API_KEY")
        or os.environ.get("ACCOUNTING_AGENT_FLASK_API_KEY")
        or ""
    ).strip()


@pytest.fixture
def live_api():
    if os.environ.get("ACCOUNTING_AGENT_LIVE", "").strip() != "1":
        pytest.skip("Set ACCOUNTING_AGENT_LIVE=1 to hit the real Flask API")
    base_url = _live_base_url()
    api_key = _live_api_key()
    if not base_url:
        pytest.skip("Set FILE_EXTRACTOR_URL to the deployed Flask origin")
    if not api_key:
        pytest.skip("Set FILE_EXTRACTOR_KEY (same value as the Flask service)")
    return {
        "url": f"{base_url}{ENQUEUE_PATH}",
        "headers": {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    }


def test_enqueue_dev_api_dry_run(live_api):
    request_id = f"pytest-live-{uuid.uuid4()}"
    response = requests.post(
        live_api["url"],
        headers=live_api["headers"],
        json={
            "request_id": request_id,
            "environment": TEST_ENVIRONMENT,
            "jobs": [_job()],
        },
        timeout=30,
    )
    data = response.json()
    assert response.status_code == 202, data
    assert data.get("success") is True
    assert data.get("environment") == TEST_ENVIRONMENT
    assert data.get("job_count") == 1
    assert data.get("request_id") == request_id
    assert data.get("task_id")
    assert data.get("task_ids") == [data["task_id"]]
    print(
        f"\nQueued on {live_api['url']}\n"
        f"  task_id={data['task_id']}\n"
        f"  org={TEST_ORG_ID}\n"
        f"  suppliers={TEST_SUPPLIER_IDS}\n"
        f"  occurred_at={TEST_OCCURRED_AT}\n"
        f"  dry_run={TEST_DRY_RUN} event={TEST_EVENT_TYPE} business={TEST_BUSINESS_EVENT_TYPE}\n"
        f"  Watch the Celery worker logs for request_id={request_id}"
    )
    # Give the worker a moment so a follow-up log check is more likely to see the task.
    time.sleep(1)
