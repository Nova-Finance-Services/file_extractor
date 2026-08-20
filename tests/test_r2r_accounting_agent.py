"""Tests for R2R accounting agent enqueue API and job params."""
import json
from unittest.mock import MagicMock, patch

from conftest import auth_headers

# Same knobs as a manual POST /r2r/accounting-agent/enqueue dry-run.
TEST_ORG_ID = "5c06415f-4c8c-4972-b23c-5c66b85845c4"
TEST_SUPPLIER_IDS = ["c6aec698-d5bf-4d21-b9ad-47882ca68443","c08bb7e9-1201-4a69-bc1e-df294204589f","fee53397-bbb7-4d22-9b71-73473dcb078a"]
TEST_DRY_RUN = False
TEST_OCCURRED_AT = "2026-09-03T12:00:00.000Z"
TEST_EVENT_TYPE = "month_start"
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
    from r2r.accounting_agent.memory import store_run_memory

    store_run_memory(
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
                "decision": {
                    "decision_type": "create_cost_accrual",
                    "confidence": 0.9,
                    "reason": ["PO delivered, not invoiced."],
                    "evidence": ["PO 12"],
                },
                "execution": {
                    "success": True,
                    "tool_timeline": [{"tool": "create_cost_accrual", "args": {"reason": "accrue PO"}}],
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
        accounting_period={"year": 2026, "period": 7, "currency": "EUR"},
        request_id="req-1",
        task_id="task-1",
    )

    mock_insert.assert_called_once()
    table, row = mock_insert.call_args.args[0], mock_insert.call_args.args[1]
    assert table == "agent_memory"
    assert row["organization_id"] == TEST_ORG_ID
    assert row["status"] == "completed"
    assert row["period_key"] == "2026-07"
    assert row["decision_types"] == ["create_cost_accrual", "no_action"]
    assert row["item_count"] == 2
    assert row["notify_count"] == 1
    assert row["confidence"] == 0.8
    assert "decision_type" not in row
    assert "execution_plan" not in row
    assert "execution_result" not in row
    items = row["items"]
    assert items[0]["subject_id"] == TEST_SUPPLIER_IDS[0]
    assert items[0]["decision_type"] == "create_cost_accrual"
    assert items[0]["reason"] == ["PO delivered, not invoiced."]
    assert items[0]["timeline"][0]["reason"] == "accrue PO"
    assert "action_log" not in items[0]
    assert "explanation" not in items[0]
    assert len(row["notifications"]) == 1
    assert "2 supplier run(s)" in row["summary"]
    assert row["attention_count"] == 0


@patch("r2r.accounting_agent.memory.supabase_rest.insert")
def test_org_close_memory_extracts_posting_and_prepaid_status(mock_insert):
    from r2r.accounting_agent.memory import store_run_memory

    store_run_memory(
        event={
            "organization_id": TEST_ORG_ID,
            "event_type": TEST_EVENT_TYPE,
            "occurred_at": TEST_OCCURRED_AT,
        },
        results=[
            {
                "provider_supplier_id": TEST_SUPPLIER_IDS[0],
                "supplier_name": "Lumen Advisory B.V.",
                "success": True,
                "decision": {
                    "decision_type": "release_prepaid_asset",
                    "confidence": 0.99,
                    "reason": ["September slice can be released."],
                    "evidence": ["setup 7260, remaining 4840"],
                },
                "execution": {
                    "success": True,
                    "period_key": "2026-09",
                    "entry_number": 26900069,
                    "provider_entry_id": "4b178970-041f-454a-9ae1-e8d2151f11b7",
                    "journal_proposal": {
                        "amount": 2420.0,
                        "currency": "EUR",
                        "debit_account": "2302",
                        "credit_account": "2302",
                        "posting_date": "2026-09-03",
                    },
                    "tool_timeline": [
                        {
                            "at": "2026-08-20T08:59:52Z",
                            "tool": "get_prepaid_status",
                            "args": {"reason": "check remaining", "provider_purchase_invoice_id": "pinv-1"},
                            "result": '{"setup_amount": 7260.0, "remaining": 4840.0, "suggested_release": 2420.0}',
                        },
                        {
                            "tool": "finalize",
                            "args": {"reason": ["September slice can be released."], "evidence": ["setup 7260"]},
                            "result": "release_prepaid_asset",
                        },
                    ],
                },
                "verification": {
                    "success": False,
                    "checks": [
                        {"check": "Debit and credit accounts differ", "passed": False, "details": "Both 2302"},
                    ],
                },
                "llm_review": {
                    "approved": False,
                    "summary": "Same GL both legs.",
                    "concerns": ["Debit and credit are both GL 2302."],
                },
                "explanation": {"reason": ["duplicate of decision"], "decision": "release_prepaid_asset"},
            }
        ],
        accounting_period={"year": 2026, "period": 9},
    )

    row = mock_insert.call_args.args[1]
    item = row["items"][0]
    assert item["actions"][0]["same_gl_both_legs"] is True
    assert item["actions"][0]["debit_account"] == "2302"
    assert item["facts"]["prepaid_status"]["remaining"] == 4840.0
    assert item["reason"] == ["September slice can be released."]
    assert item["review"]["approved"] is False
    assert item["review"]["concerns"] == ["Debit and credit are both GL 2302."]
    assert item["checks"]["passed"] is False
    assert "explanation" not in item
    prepaid_step = item["timeline"][0]
    assert prepaid_step["reason"] == "check remaining"
    assert "reason" not in prepaid_step["args"]
    finalize = item["timeline"][1]
    assert finalize["tool"] == "finalize"
    assert "args" not in finalize
    assert finalize["reason"] == "September slice can be released."
    assert "need attention" in row["summary"]
    assert "needs_attention" not in row
    assert row["posted_amount"] == 2420.0


@patch("r2r.accounting_agent.memory.supabase_rest.insert")
def test_skipped_run_writes_memory_row(mock_insert):
    from r2r.accounting_agent.memory import store_run_memory

    store_run_memory(
        event={
            "organization_id": TEST_ORG_ID,
            "event_type": TEST_EVENT_TYPE,
            "occurred_at": TEST_OCCURRED_AT,
        },
        results=[],
        skip_reason="Event received outside configured month_start/month_end run window.",
        request_id="req-skip",
        task_id="task-skip",
    )

    row = mock_insert.call_args.args[1]
    assert row["status"] == "skipped"
    assert row["item_count"] == 0
    assert row["title"] == "Month start close skipped"
    assert "outside configured" in row["summary"]
    assert row["period_key"] == "2026-09"
