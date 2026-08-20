from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from r2r import supabase_rest
from r2r.accounting_agent.constants import ACCOUNTING_AGENT_NAME
from r2r.supabase_rest import SupabaseRestError


logger = logging.getLogger(__name__)

_POSTING_TOOLS = {
    "create_cost_accrual",
    "release_existing_accrual",
    "create_prepaid_asset",
    "release_prepaid_asset",
}


def store_run_memory(
    *,
    event: dict[str, Any],
    results: Optional[list[dict[str, Any]]] = None,
    accounting_period: dict[str, Any] | None = None,
    status: str | None = None,
    started_at: datetime | str | None = None,
    finished_at: datetime | str | None = None,
    request_id: str | None = None,
    task_id: str | None = None,
    dry_run: bool = False,
    skip_reason: str | None = None,
    trigger_source: str = "cron",
) -> None:
    """One agent_memory row per run. Typed columns for the feed; items[] for the drawer."""
    org_id = event.get("organization_id")
    if not org_id:
        return

    started = _as_datetime(started_at) or datetime.now(timezone.utc)
    finished = _as_datetime(finished_at) or datetime.now(timezone.utc)
    period_key, period_year, period_month = _period_fields(event, accounting_period)
    items = [_item(result) for result in (results or [])]
    notifications = _collect_notifications(results or [])

    decision_types: list[str] = []
    for item in items:
        dtype = item.get("decision_type")
        if dtype and dtype not in decision_types:
            decision_types.append(dtype)

    actions = [action for item in items for action in (item.get("actions") or [])]
    posted_amounts = [a["amount"] for a in actions if isinstance(a.get("amount"), (int, float))]
    currencies = [a.get("currency") for a in actions if a.get("currency")]
    attention_count = sum(1 for item in items if _needs_attention(item))
    failed = [item for item in items if item.get("status") != "success"]
    confidences = [
        float(item["confidence"])
        for item in items
        if item.get("confidence") is not None
    ]

    if skip_reason:
        run_status = "skipped"
    elif status:
        run_status = status
    elif not items:
        run_status = "failed"
    elif failed and len(failed) == len(items):
        run_status = "failed"
    elif failed:
        run_status = "partial"
    else:
        run_status = "completed"

    event_label = _event_label(event.get("event_type"))
    if run_status == "skipped":
        title = f"{event_label} skipped"
        summary = skip_reason
    else:
        title = f"{event_label} — {len(items)} supplier{'s' if len(items) != 1 else ''}"
        summary = _run_summary(items, notifications, attention_count)

    duration_ms = max(0, int((finished - started).total_seconds() * 1000))
    row = {
        "agent_name": ACCOUNTING_AGENT_NAME,
        "organization_id": org_id,
        "user_id": event.get("user_id"),
        "trigger_source": trigger_source,
        "request_id": request_id,
        "task_id": task_id,
        "event_type": event.get("event_type"),
        "occurred_at": event.get("occurred_at") or started.isoformat(),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_ms": duration_ms,
        "period_key": period_key,
        "period_year": period_year,
        "period_month": period_month,
        "dry_run": bool(dry_run),
        "status": run_status,
        "title": title,
        "summary": summary,
        "decision_types": decision_types,
        "item_count": len(items),
        "action_count": len(actions),
        "notify_count": len(notifications),
        "attention_count": attention_count,
        "posted_amount": round(sum(posted_amounts), 2) if posted_amounts else None,
        "currency": currencies[0] if currencies else (accounting_period or {}).get("currency"),
        "confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
        "error": skip_reason if run_status == "skipped" else _first_error(items),
        "input": {
            "event": {
                "event_type": event.get("event_type"),
                "occurred_at": event.get("occurred_at"),
                "organization_id": org_id,
                "business_event_type": (event.get("payload") or {}).get("business_event_type")
                or event.get("business_event_type"),
            },
            "period_key": period_key,
            "accounting_period": accounting_period or {},
            "subject_ids": [item.get("subject_id") for item in items if item.get("subject_id")],
            "subject_count": len(items),
        },
        "items": items,
        "notifications": notifications,
        "metrics": {},
    }

    try:
        supabase_rest.insert("agent_memory", row)
    except SupabaseRestError as exc:
        if exc.status in {409, 23505} or (exc.body and "idx_agent_memory_agent_org_task" in exc.body):
            logger.warning("agent_memory already stored for task_id=%s", task_id)
            return
        raise


def _item(result: dict[str, Any]) -> dict[str, Any]:
    decision = result.get("decision") or {}
    execution = result.get("execution") or {}
    verification = result.get("verification") or {}
    review = _review(result.get("llm_review"))
    llm = _llm(result.get("llm_info"))
    actions = _actions(execution)
    success = result.get("success") is not False and execution.get("success") is not False
    item: dict[str, Any] = {
        "subject_type": "supplier",
        "subject_id": result.get("provider_supplier_id"),
        "subject_label": result.get("supplier_name"),
        "decision_type": decision.get("decision_type"),
        "status": "success" if success else "failed",
        "confidence": decision.get("confidence"),
        "reason": decision.get("reason") or [],
        "evidence": decision.get("evidence") or [],
        "error": result.get("error") or execution.get("error"),
        "actions": actions,
        "checks": {
            "passed": verification.get("success") if verification else None,
            "items": verification.get("checks") or [],
        },
        "review": review,
        "llm": llm,
        "timeline": _timeline(execution.get("tool_timeline") or []),
    }
    return {key: value for key, value in item.items() if value not in (None, [], {})}


def _timeline(timeline: list[Any]) -> list[dict[str, Any]]:
    slim: list[dict[str, Any]] = []
    for step in timeline:
        if not isinstance(step, dict):
            continue
        tool = step.get("tool")
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        reason = args.get("reason")
        if isinstance(reason, list):
            reason = next((part for part in reason if part), None)
        result = step.get("result")
        entry: dict[str, Any] = {"at": step.get("at"), "tool": tool}
        if reason:
            entry["reason"] = reason
        if tool != "finalize":
            slim_args = {k: v for k, v in args.items() if k not in {"reason", "evidence"}}
            if slim_args:
                entry["args"] = slim_args
        if result is not None:
            entry["result"] = result
        slim.append({k: v for k, v in entry.items() if v is not None})
    return slim


def _actions(execution: dict[str, Any]) -> list[dict[str, Any]]:
    posted = [row for row in (execution.get("posted_journals") or []) if isinstance(row, dict)]
    if not posted and (execution.get("provider_entry_id") or execution.get("journal_proposal")):
        posted = [{
            "provider_entry_id": execution.get("provider_entry_id"),
            "entry_number": execution.get("entry_number"),
            "journal_proposal": execution.get("journal_proposal") or {},
        }]
    if not posted:
        extra = []
        for step in execution.get("tool_timeline") or []:
            if isinstance(step, dict) and step.get("tool") in _POSTING_TOOLS and step.get("result"):
                extra.append({
                    "kind": "journal",
                    "tool": step.get("tool"),
                    "result": step.get("result"),
                })
        return extra

    actions: list[dict[str, Any]] = []
    for item in posted:
        proposal = item.get("journal_proposal") or {}
        same_gl = bool(
            proposal.get("debit_account")
            and proposal.get("debit_account") == proposal.get("credit_account")
        )
        action = {
            "kind": "journal",
            "provider_entry_id": item.get("provider_entry_id"),
            "entry_number": item.get("entry_number"),
            "amount": proposal.get("amount"),
            "currency": proposal.get("currency"),
            "debit_account": proposal.get("debit_account"),
            "credit_account": proposal.get("credit_account"),
            "posting_date": proposal.get("posting_date"),
            "description": proposal.get("description"),
            "same_gl_both_legs": same_gl,
        }
        actions.append({k: v for k, v in action.items() if v not in (None, False)})
    return actions


def _review(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "approved": raw.get("approved"),
        "summary": raw.get("summary"),
        "concerns": raw.get("concerns") or [],
    }


def _llm(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "provider": raw.get("provider_used") or raw.get("primary_provider") or raw.get("provider"),
        "model": raw.get("model"),
        "fallback_used": bool(raw.get("fallback_used")),
    }


def _needs_attention(item: dict[str, Any]) -> bool:
    if item.get("status") != "success":
        return True
    review = item.get("review") or {}
    if review.get("approved") is False:
        return True
    if review.get("concerns"):
        return True
    checks = item.get("checks") or {}
    if checks.get("passed") is False:
        return True
    return any(action.get("same_gl_both_legs") for action in (item.get("actions") or []))


def _collect_notifications(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    notifications: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for result in results:
        raw = result.get("finance_controller_notifications")
        if not raw:
            raw = (result.get("execution") or {}).get("finance_controller_notifications") or []
        for item in raw:
            key = (
                item.get("kind"),
                item.get("message"),
                item.get("provider_supplier_id"),
                item.get("provider_purchase_invoice_id"),
            )
            if key in seen:
                continue
            seen.add(key)
            notifications.append(item)
    return notifications


def _run_summary(
    items: list[dict[str, Any]],
    notifications: list[dict[str, Any]],
    attention_count: int,
) -> str:
    counts: dict[str, int] = {}
    for item in items:
        key = item.get("decision_type") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    parts = [f"{len(items)} supplier run(s)"]
    parts.extend(f"{n} {name}" for name, n in sorted(counts.items()))
    parts.append(f"{len(notifications)} notification(s)")
    if attention_count:
        parts.append(f"{attention_count} need attention")
    return "; ".join(parts)


def _event_label(event_type: Any) -> str:
    mapping = {
        "month_start": "Month start close",
        "month_end": "Month end close",
    }
    return mapping.get(str(event_type or ""), str(event_type or "Agent run").replace("_", " ").title())


def _period_fields(
    event: dict[str, Any],
    accounting_period: dict[str, Any] | None,
) -> tuple[str | None, int | None, int | None]:
    year = (accounting_period or {}).get("year")
    month = (accounting_period or {}).get("period")
    if year is None:
        occurred = event.get("occurred_at") or ""
        try:
            parsed = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
            year, month = parsed.year, parsed.month
        except ValueError:
            return None, None, None
    try:
        year_n = int(year)
        month_n = int(month or 0)
    except (TypeError, ValueError):
        return None, None, None
    if month_n < 1:
        return None, year_n, None
    return f"{year_n}-{month_n:02d}", year_n, month_n


def _as_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _first_error(items: list[dict[str, Any]]) -> str | None:
    for item in items:
        if item.get("error"):
            return str(item["error"])
    return None
