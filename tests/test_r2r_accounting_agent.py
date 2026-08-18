"""Tests for R2R accounting agent enqueue route and Python worker."""
import json
from unittest.mock import MagicMock, patch

from conftest import auth_headers


class TestR2rAccountingAgentEnqueue:
    def test_invalid_jobs_type(self, client):
        response = client.post(
            "/r2r/accounting-agent/enqueue",
            headers=auth_headers(),
            json={"environment": "prod", "jobs": "not-an-array"},
        )
        assert response.status_code == 400
        assert "jobs must be an array" in json.loads(response.data)["error"]

    def test_invalid_event_type(self, client):
        response = client.post(
            "/r2r/accounting-agent/enqueue",
            headers=auth_headers(),
            json={
                "environment": "prod",
                "jobs": [{
                    "organization_id": "org-1",
                    "event_type": "invalid",
                    "occurred_at": "2026-07-31T12:00:00.000Z",
                }],
            },
        )
        assert response.status_code == 400
        assert "event_type" in json.loads(response.data)["error"]

    def test_empty_jobs_returns_no_task(self, client):
        response = client.post(
            "/r2r/accounting-agent/enqueue",
            headers=auth_headers(),
            json={"environment": "prod", "jobs": []},
        )
        data = json.loads(response.data)
        assert response.status_code == 202
        assert data["task_id"] == "no_jobs"
        assert data["job_count"] == 0

    @patch("tasks.process_accounting_agent_job")
    def test_enqueue_success(self, mock_task, client):
        mock_async = MagicMock()
        mock_async.id = "celery-task-123"
        mock_task.delay.return_value = mock_async

        response = client.post(
            "/r2r/accounting-agent/enqueue",
            headers=auth_headers(),
            json={
                "request_id": "req-1",
                "environment": "prod",
                "jobs": [{
                    "organization_id": "org-1",
                    "event_type": "month_end",
                    "occurred_at": "2026-07-31T12:00:00.000Z",
                    "dry_run": True,
                    "business_event_type": "month_end_org_close",
                }],
            },
        )

        data = json.loads(response.data)
        assert response.status_code == 202
        assert data["success"] is True
        assert data["task_id"] == "celery-task-123"
        assert data["task_ids"] == ["celery-task-123"]
        assert data["job_count"] == 1
        mock_task.delay.assert_called_once()

    @patch("tasks.process_accounting_agent_job")
    def test_enqueue_one_task_per_org(self, mock_task, client):
        mock_task.delay.side_effect = [
            MagicMock(id="task-a"),
            MagicMock(id="task-b"),
        ]
        response = client.post(
            "/r2r/accounting-agent/enqueue",
            headers=auth_headers(),
            json={
                "environment": "prod",
                "jobs": [
                    {
                        "organization_id": "org-1",
                        "event_type": "month_end",
                        "occurred_at": "2026-07-31T12:00:00.000Z",
                    },
                    {
                        "organization_id": "org-2",
                        "event_type": "month_end",
                        "occurred_at": "2026-07-31T12:00:00.000Z",
                    },
                ],
            },
        )
        data = json.loads(response.data)
        assert response.status_code == 202
        assert data["task_ids"] == ["task-a", "task-b"]
        assert data["job_count"] == 2
        assert mock_task.delay.call_count == 2

    @patch("r2r.processing.execute_accounting_agent_run")
    def test_worker_runs_python_agent(self, mock_run):
        from r2r.processing import run_accounting_agent_job

        mock_run.return_value = {"success": True, "skipped": True}

        summary = run_accounting_agent_job({
            "request_id": "req-1",
            "environment": "prod",
            "job": {
                "organization_id": "org-1",
                "event_type": "month_end",
                "occurred_at": "2026-07-31T12:00:00.000Z",
                "dry_run": True,
                "business_event_type": "month_end_org_close",
            },
        })

        assert summary["success"] is True
        mock_run.assert_called_once()
        event, options = mock_run.call_args.args
        assert event["organization_id"] == "org-1"
        assert event["event_type"] == "month_end"
        assert options["dry_run"] is True
