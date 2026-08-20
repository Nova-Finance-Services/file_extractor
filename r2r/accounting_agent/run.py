"""Org / supplier / document orchestration for the accounting agent."""
from __future__ import annotations

import time
from calendar import monthrange
from datetime import datetime, timezone
from typing import Any, Optional

from r2r.accounting_agent.discovery import (
    build_context,
    build_supplier_close_context,
    event_has_document_payload,
    event_has_supplier_payload,
    list_supplier_close_batches,
)
from r2r.jobs import resolve_forced_supplier_ids
from r2r.accounting_agent.executor import create_default_business_tools
from r2r.accounting_agent.llm_chat import agent_chat_with_failover, get_last_agent_llm_info, run_llm_review
from r2r.accounting_agent.loaders import get_accounting_period_context, get_organization_context
from r2r.accounting_agent.loop import run_accounting_agent
from r2r.accounting_agent.memory import store_run_memory
from r2r.accounting_agent.period_window import build_close_period_window
from r2r.accounting_agent.prompts import build_context_prompt, build_system_prompt, build_verifier_prompt
from r2r.accounting_agent.review import generate_explanation, verify_execution
from r2r.config import SUPPLIER_RUN_GAP_SECONDS


def is_event_within_configured_window(event: dict[str, Any], policy: dict[str, Any]) -> bool:
    occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    day_of_month = occurred.day
    last_day = monthrange(occurred.year, occurred.month)[1]
    if event["event_type"] == "month_start":
        return day_of_month in (policy.get("month_start_run_days") or [])
    offset = last_day - day_of_month
    return offset in (policy.get("month_end_offset_days") or [])


def _persist_and_package(
    event: dict[str, Any],
    context: dict[str, Any],
    dry_run: bool,
    extras: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    extras = extras or {}
    tools = create_default_business_tools(context, dry_run)
    run = run_accounting_agent(context, tools, agent_chat_with_failover)
    llm_info = get_last_agent_llm_info()
    verification = verify_execution(context, run["decision"], run["execution"])
    explanation = generate_explanation(run["decision"], run["execution"], verification)
    llm_review = run_llm_review(
        build_verifier_prompt(context, run["decision"], run["execution"], verification)
    )

    payload = event.get("payload") or {}
    result = {
        "success": True,
        "dry_run": dry_run,
        "decision_source": run["source"],
        "llm_error": run.get("llm_error"),
        "llm_info": llm_info,
        "decision": run["decision"],
        "plan": run["plan"],
        "execution": run["execution"],
        "verification": verification,
        "llm_review": llm_review,
        "explanation": explanation,
        "event_type": event["event_type"],
        "provider_supplier_id": (context.get("supplier_context") or {}).get("provider_supplier_id"),
        "supplier_name": (context.get("supplier_context") or {}).get("supplier_name"),
        "finance_controller_notifications": run["execution"].get("finance_controller_notifications") or [],
        "purchase_order_id": str(payload["purchase_order_id"]) if payload.get("purchase_order_id") else None,
        "purchase_invoice_id": str(payload["purchase_invoice_id"]) if payload.get("purchase_invoice_id") else None,
        "provider_purchase_order_id": str(payload["provider_purchase_order_id"]) if payload.get("provider_purchase_order_id") else None,
        "provider_purchase_invoice_id": str(payload["provider_purchase_invoice_id"]) if payload.get("provider_purchase_invoice_id") else None,
        "prompts": {
            "system": build_system_prompt(context),
            "context": build_context_prompt(context),
            "verifier": build_verifier_prompt(context, run["decision"], run["execution"], verification),
        },
        **extras,
    }
    return result


def _write_run_memory(
    event: dict[str, Any],
    options: dict[str, Any],
    *,
    started_at: datetime,
    results: Optional[list[dict[str, Any]]] = None,
    accounting_period: dict[str, Any] | None = None,
    skip_reason: str | None = None,
) -> None:
    if options.get("dry_run"):
        return
    store_run_memory(
        event=event,
        results=results or [],
        accounting_period=accounting_period,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        request_id=options.get("request_id"),
        task_id=options.get("task_id"),
        dry_run=False,
        skip_reason=skip_reason,
        trigger_source=str(options.get("trigger_source") or "cron"),
    )


def execute_accounting_agent_run(event: dict[str, Any], options: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    options = options or {}
    dry_run = bool(options.get("dry_run"))
    payload = event.get("payload") or {}
    started_at = datetime.now(timezone.utc)

    if event_has_document_payload(payload) and not event_has_supplier_payload(payload):
        context = build_context(event)
        if not is_event_within_configured_window(event, context["organization_policy"]):
            message = "Event received outside configured month_start/month_end run window."
            _write_run_memory(
                event,
                options,
                started_at=started_at,
                accounting_period=context.get("accounting_period"),
                skip_reason=message,
            )
            return {
                "success": True,
                "dry_run": dry_run,
                "skipped": True,
                "message": message,
                "event_type": event["event_type"],
            }
        result = _persist_and_package(event, context, dry_run)
        _write_run_memory(
            event,
            options,
            started_at=started_at,
            results=[result],
            accounting_period=context.get("accounting_period"),
        )
        return result

    organization_policy = get_organization_context(event["organization_id"])
    if not is_event_within_configured_window(event, organization_policy):
        message = "Event received outside configured month_start/month_end run window."
        _write_run_memory(event, options, started_at=started_at, skip_reason=message)
        return {
            "success": True,
            "dry_run": dry_run,
            "skipped": True,
            "org_close_run": True,
            "event_type": event["event_type"],
            "message": message,
        }

    accounting_period = get_accounting_period_context(event["organization_id"], event["occurred_at"])
    period_window = build_close_period_window({
        "year": accounting_period["year"],
        "period": accounting_period["period"],
    })
    batches = list_supplier_close_batches(
        event["organization_id"],
        event["event_type"],
        {"start_date": period_window["start_date"], "end_date": period_window["end_date"]},
    )
    forced_ids = resolve_forced_supplier_ids(payload)
    if forced_ids:
        by_id = {batch["provider_supplier_id"]: batch for batch in batches}
        selected = []
        for supplier_id in forced_ids:
            if supplier_id in by_id:
                selected.append(by_id[supplier_id])
            else:
                selected.append({
                    "provider_supplier_id": supplier_id,
                    "supplier_name": str(payload["supplier_name"]) if payload.get("supplier_name") else None,
                    "purchase_orders": [],
                    "purchase_invoices": [],
                })
    else:
        selected = batches
    if not selected:
        message = (
            "No suppliers with POs/PINVs or cost/accrued/prepaid journal activity "
            "in the current period and previous two periods."
        )
        _write_run_memory(
            event,
            options,
            started_at=started_at,
            accounting_period=accounting_period,
            skip_reason=message,
        )
        return {
            "success": True,
            "dry_run": dry_run,
            "skipped": True,
            "org_close_run": True,
            "event_type": event["event_type"],
            "supplier_count": 0,
            "candidate_count": 0,
            "message": message,
        }

    results = []
    for index, batch in enumerate(selected):
        try:
            context = build_supplier_close_context(event, batch, period_window)
            results.append(_persist_and_package(event, context, dry_run, {
                "provider_supplier_id": batch["provider_supplier_id"],
                "supplier_name": batch.get("supplier_name"),
            }))
        except Exception as exc:
            results.append({
                "success": False,
                "dry_run": dry_run,
                "event_type": event["event_type"],
                "provider_supplier_id": batch["provider_supplier_id"],
                "supplier_name": batch.get("supplier_name"),
                "error": str(exc),
            })
        if index < len(selected) - 1 and SUPPLIER_RUN_GAP_SECONDS > 0:
            time.sleep(SUPPLIER_RUN_GAP_SECONDS)

    _write_run_memory(
        event,
        options,
        started_at=started_at,
        results=results,
        accounting_period=accounting_period,
    )

    return {
        "success": all(r.get("success") is not False for r in results),
        "dry_run": dry_run,
        "org_close_run": True,
        "event_type": event["event_type"],
        "supplier_count": len(selected),
        "candidate_count": len(selected),
        "results": results,
    }
