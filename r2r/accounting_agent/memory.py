from __future__ import annotations

import json
from typing import Any

from r2r import supabase_rest


AGENT_NAME = "r2r.accounting-agent"


def store_org_close_memory(
    *,
    event: dict[str, Any],
    results: list[dict[str, Any]],
    accounting_period: dict[str, Any] | None = None,
) -> None:
    """One agent_memory row per org close. Nested JSON is the schema; columns stay as-is."""
    org_id = event.get("organization_id")
    if not org_id:
        return

    notifications: list[dict[str, Any]] = []
    for result in results:
        notifications.extend(result.get("finance_controller_notifications") or [])
        notifications.extend((result.get("execution") or {}).get("finance_controller_notifications") or [])

    suppliers = [_supplier_row(result) for result in results]
    period = accounting_period or {}
    period_key = f"{period.get('year')}-{int(period.get('period') or 0):02d}" if period.get("year") else None
    review_rejected = [
        row["provider_supplier_id"]
        for row in suppliers
        if row.get("llm_review") and row["llm_review"].get("approved") is False
    ]
    failed_ids = [row["provider_supplier_id"] for row in suppliers if not row.get("success")]
    decision_types = []
    for row in suppliers:
        dtype = row.get("decision_type")
        if dtype and dtype not in decision_types:
            decision_types.append(dtype)

    supabase_rest.insert(
        "agent_memory",
        {
            "agent_name": AGENT_NAME,
            "organization_id": org_id,
            "user_id": event.get("user_id"),
            "event_type": event.get("event_type"),
            "decision_type": "org_close",
            "confidence": _mean_confidence(results),
            "context_snapshot": {
                "event": {
                    "event_type": event.get("event_type"),
                    "occurred_at": event.get("occurred_at"),
                    "organization_id": org_id,
                    "business_event_type": (event.get("payload") or {}).get("business_event_type"),
                },
                "period_key": period_key,
                "accounting_period": period,
                "supplier_ids": [row["provider_supplier_id"] for row in suppliers],
                "supplier_count": len(suppliers),
            },
            "execution_plan": {
                "supplier_count": len(suppliers),
                "decision_types": decision_types,
                "posted_entry_ids": [
                    (row.get("posting") or {}).get("provider_entry_id")
                    for row in suppliers
                    if (row.get("posting") or {}).get("provider_entry_id")
                ],
            },
            "execution_result": {
                "success": not failed_ids,
                "suppliers": suppliers,
            },
            "verification_result": {
                "success": not failed_ids,
                "failed_supplier_ids": failed_ids,
                "review_rejected_supplier_ids": review_rejected,
            },
            "explanation": _org_explanation(suppliers, notifications),
            "finance_controller_notifications": notifications,
        },
    )


def _supplier_row(result: dict[str, Any]) -> dict[str, Any]:
    decision = result.get("decision") or {}
    execution = result.get("execution") or {}
    posting = _posting(execution)
    prepaid_status = _prepaid_status(execution)
    return {
        "provider_supplier_id": result.get("provider_supplier_id"),
        "supplier_name": result.get("supplier_name"),
        "success": result.get("success"),
        "decision_type": decision.get("decision_type"),
        "confidence": decision.get("confidence"),
        "requires_human_approval": decision.get("requires_human_approval"),
        "reason": decision.get("reason") or [],
        "evidence": decision.get("evidence") or [],
        "error": result.get("error"),
        "posting": posting,
        "prepaid_status": prepaid_status,
        "execution": _slim_execution(execution),
        "verification": result.get("verification") or None,
        "llm_review": result.get("llm_review"),
        "llm_info": result.get("llm_info"),
    }


def _slim_execution(execution: dict[str, Any]) -> dict[str, Any] | None:
    if not execution:
        return None
    slim: dict[str, Any] = {
        "success": execution.get("success"),
        "error": execution.get("error"),
        "period_key": execution.get("period_key"),
        "tool_timeline": _slim_timeline(execution.get("tool_timeline") or []),
    }
    return {key: value for key, value in slim.items() if value not in (None, [], {})}


def _slim_timeline(timeline: list[Any]) -> list[dict[str, Any]]:
    slim: list[dict[str, Any]] = []
    for step in timeline:
        if not isinstance(step, dict):
            continue
        tool = step.get("tool")
        entry: dict[str, Any] = {"at": step.get("at"), "tool": tool}
        if tool == "finalize":
            entry["result"] = step.get("result")
        else:
            args = step.get("args")
            if isinstance(args, dict):
                entry["args"] = {k: v for k, v in args.items() if k not in {"reason", "evidence"}}
                if "reason" in args and tool in {"record_no_action"}:
                    entry["args"]["reason"] = args.get("reason")
            result = step.get("result")
            if isinstance(result, str) and result.startswith("{") and tool == "get_prepaid_status":
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    pass
            entry["result"] = result
        slim.append({k: v for k, v in entry.items() if v is not None})
    return slim


def _posting(execution: dict[str, Any]) -> dict[str, Any] | None:
    proposal = execution.get("journal_proposal") or {}
    if not execution.get("provider_entry_id") and not proposal:
        return None
    same_gl = (
        proposal.get("debit_account")
        and proposal.get("debit_account") == proposal.get("credit_account")
    )
    posting = {
        "entry_number": execution.get("entry_number"),
        "provider_entry_id": execution.get("provider_entry_id"),
        "amount": proposal.get("amount"),
        "currency": proposal.get("currency"),
        "debit_account": proposal.get("debit_account"),
        "credit_account": proposal.get("credit_account"),
        "posting_date": proposal.get("posting_date"),
        "description": proposal.get("description"),
        "same_gl_both_legs": same_gl or None,
    }
    return {k: v for k, v in posting.items() if v not in (None, False)}


def _prepaid_status(execution: dict[str, Any]) -> dict[str, Any] | None:
    for step in execution.get("tool_timeline") or []:
        if not isinstance(step, dict) or step.get("tool") != "get_prepaid_status":
            continue
        result = step.get("result")
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def _org_explanation(suppliers: list[dict[str, Any]], notifications: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in suppliers:
        key = row.get("decision_type") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    review_rejected = sum(1 for row in suppliers if (row.get("llm_review") or {}).get("approved") is False)
    same_gl = sum(1 for row in suppliers if (row.get("posting") or {}).get("same_gl_both_legs"))
    parts = [f"{len(suppliers)} supplier run(s)"]
    parts.extend(f"{n} {name}" for name, n in sorted(counts.items()))
    parts.append(f"{len(notifications)} finance-controller notification(s)")
    if review_rejected:
        parts.append(f"{review_rejected} llm_review rejected")
    if same_gl:
        parts.append(f"{same_gl} posting(s) with same debit and credit GL")
    return {
        "decision": "org_close",
        "summary": "; ".join(parts),
        "by_supplier": [
            {
                "provider_supplier_id": row.get("provider_supplier_id"),
                "supplier_name": row.get("supplier_name"),
                "decision_type": row.get("decision_type"),
                "success": row.get("success"),
                "entry_number": (row.get("posting") or {}).get("entry_number"),
                "provider_entry_id": (row.get("posting") or {}).get("provider_entry_id"),
                "llm_review_approved": (row.get("llm_review") or {}).get("approved"),
            }
            for row in suppliers
        ],
        "confidence": _mean_confidence_from_rows(suppliers),
    }


def _mean_confidence(results: list[dict[str, Any]]) -> float:
    values = [
        float((result.get("decision") or {}).get("confidence") or 0)
        for result in results
        if (result.get("decision") or {}).get("confidence") is not None
    ]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _mean_confidence_from_rows(suppliers: list[dict[str, Any]]) -> float:
    values = [float(row["confidence"]) for row in suppliers if row.get("confidence") is not None]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)
