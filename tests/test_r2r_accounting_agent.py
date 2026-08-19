"""Tests for R2R accounting agent enqueue API and job params."""
import json
from unittest.mock import MagicMock, patch

from conftest import auth_headers

# Same knobs as a manual POST /r2r/accounting-agent/enqueue dry-run.
TEST_ORG_ID = "5c06415f-4c8c-4972-b23c-5c66b85845c4"
TEST_SUPPLIER_IDS = ["c08bb7e9-1201-4a69-bc1e-df294204589f","fee53397-bbb7-4d22-9b71-73473dcb078a"]
TEST_DRY_RUN = False
TEST_OCCURRED_AT = "2026-07-31T12:00:00.000Z"
TEST_EVENT_TYPE = "month_end"
TEST_ENVIRONMENT = "dev"
TEST_BUSINESS_EVENT_TYPE = "month_end_org_close"
ENQUEUE_PATH = "/r2r/accounting-agent/enqueue"


def _job(**overrides):
    job = {
        "organization_id": TEST_ORG_ID,
        "event_type": TEST_EVENT_TYPE,
        "occurred_at": TEST_OCCURRED_AT,
        "dry_run": TEST_DRY_RUN,
        "business_event_type": TEST_BUSINESS_EVENT_TYPE,
        "supplier_ids": list(TEST_SUPPLIER_IDS),
    }
    job.update(overrides)
    return job


def _enqueue(client, *, jobs, environment=TEST_ENVIRONMENT, request_id="req-1"):
    return client.post(
        ENQUEUE_PATH,
        headers=auth_headers(),
        json={
            "request_id": request_id,
            "environment": environment,
            "jobs": jobs,
        },
    )


class TestR2rAccountingAgentEnqueue:
    def test_invalid_jobs_type(self, client):
        response = _enqueue(client, jobs="not-an-array")
        assert response.status_code == 400
        assert "jobs must be an array" in json.loads(response.data)["error"]

    def test_invalid_event_type(self, client):
        response = _enqueue(client, jobs=[_job(event_type="invalid")])
        assert response.status_code == 400
        assert "event_type" in json.loads(response.data)["error"]

    def test_empty_jobs_returns_no_task(self, client):
        response = _enqueue(client, jobs=[])
        data = json.loads(response.data)
        assert response.status_code == 202
        assert data["task_id"] == "no_jobs"
        assert data["job_count"] == 0

    @patch("tasks.process_accounting_agent_job")
    def test_enqueue_posts_org_suppliers_dry_run_occurred_at(self, mock_task, client):
        mock_async = MagicMock()
        mock_async.id = "celery-task-123"
        mock_task.delay.return_value = mock_async

        response = _enqueue(client, jobs=[_job()], request_id="manual-flask-test")
        data = json.loads(response.data)

        assert response.status_code == 202
        assert data["success"] is True
        assert data["task_id"] == "celery-task-123"
        assert data["task_ids"] == ["celery-task-123"]
        assert data["job_count"] == 1
        assert data["environment"] == TEST_ENVIRONMENT

        mock_task.delay.assert_called_once()
        queued = mock_task.delay.call_args.args[0]
        assert queued["request_id"] == "manual-flask-test"
        assert queued["environment"] == TEST_ENVIRONMENT
        job = queued["job"]
        assert job["organization_id"] == TEST_ORG_ID
        assert job["event_type"] == TEST_EVENT_TYPE
        assert job["occurred_at"] == TEST_OCCURRED_AT
        assert job["dry_run"] is TEST_DRY_RUN
        assert job["business_event_type"] == TEST_BUSINESS_EVENT_TYPE
        assert job["payload"]["provider_supplier_ids"] == TEST_SUPPLIER_IDS
        assert job["payload"]["provider_supplier_id"] == TEST_SUPPLIER_IDS[0]

    @patch("tasks.process_accounting_agent_job")
    def test_enqueue_one_task_per_org(self, mock_task, client):
        mock_task.delay.side_effect = [
            MagicMock(id="task-a"),
            MagicMock(id="task-b"),
        ]
        response = _enqueue(client, jobs=[
            _job(),
            _job(organization_id="11111111-1111-1111-1111-111111111111"),
        ])
        data = json.loads(response.data)
        assert response.status_code == 202
        assert data["task_ids"] == ["task-a", "task-b"]
        assert data["job_count"] == 2
        assert mock_task.delay.call_count == 2
        first_job = mock_task.delay.call_args_list[0].args[0]["job"]
        second_job = mock_task.delay.call_args_list[1].args[0]["job"]
        assert first_job["organization_id"] == TEST_ORG_ID
        assert second_job["organization_id"] == "11111111-1111-1111-1111-111111111111"
        assert first_job["payload"]["provider_supplier_ids"] == TEST_SUPPLIER_IDS
        assert first_job["dry_run"] is TEST_DRY_RUN
        assert first_job["occurred_at"] == TEST_OCCURRED_AT

    @patch("r2r.processing.execute_accounting_agent_run")
    def test_worker_uses_api_params(self, mock_run):
        from r2r.processing import run_accounting_agent_job

        mock_run.return_value = {"success": True, "skipped": True}

        summary = run_accounting_agent_job({
            "request_id": "req-1",
            "environment": TEST_ENVIRONMENT,
            "job": _job(),
        })

        assert summary["success"] is True
        mock_run.assert_called_once()
        event, options = mock_run.call_args.args
        assert event["organization_id"] == TEST_ORG_ID
        assert event["event_type"] == TEST_EVENT_TYPE
        assert event["occurred_at"] == TEST_OCCURRED_AT
        assert event["payload"]["provider_supplier_ids"] == TEST_SUPPLIER_IDS
        assert event["payload"]["provider_supplier_id"] == TEST_SUPPLIER_IDS[0]
        assert options["dry_run"] is TEST_DRY_RUN


@patch("r2r.accounting_agent.memory.supabase_rest.insert")
def test_org_close_writes_one_memory_row(mock_insert):
    from r2r.accounting_agent.memory import store_org_close_memory

    store_org_close_memory(
        event={
            "organization_id": TEST_ORG_ID,
            "event_type": TEST_EVENT_TYPE,
            "occurred_at": TEST_OCCURRED_AT,
        },
        results=[
            {
                "provider_supplier_id": TEST_SUPPLIER_IDS[0],
                "supplier_name": "Acme",
                "success": True,
                "decision": {"decision_type": "create_cost_accrual", "confidence": 0.9},
                "execution": {
                    "success": True,
                    "tool_timeline": [{"tool": "create_cost_accrual"}],
                    "finance_controller_notifications": [],
                    "action_log": ["posted"],
                },
                "llm_review": {"approved": True, "summary": "ok", "concerns": []},
                "finance_controller_notifications": [
                    {"kind": "notify", "message": "check accrual", "provider_supplier_id": TEST_SUPPLIER_IDS[0]},
                ],
            },
            {
                "provider_supplier_id": "22222222-2222-2222-2222-222222222222",
                "success": True,
                "decision": {"decision_type": "no_action", "confidence": 0.7},
                "execution": {"success": True, "tool_timeline": []},
                "finance_controller_notifications": [],
            },
        ],
        accounting_period={"year": 2026, "period": 7},
    )

    mock_insert.assert_called_once()
    table, row = mock_insert.call_args.args[0], mock_insert.call_args.args[1]
    assert table == "agent_memory"
    assert row["organization_id"] == TEST_ORG_ID
    assert row["decision_type"] == "org_close"
    assert row["context_snapshot"]["supplier_count"] == 2
    assert len(row["execution_result"]["suppliers"]) == 2
    assert row["execution_result"]["suppliers"][0]["provider_supplier_id"] == TEST_SUPPLIER_IDS[0]
    assert "action_log" not in (row["execution_result"]["suppliers"][0]["execution"] or {})
    assert len(row["finance_controller_notifications"]) == 1
    assert mock_insert.call_count == 1
