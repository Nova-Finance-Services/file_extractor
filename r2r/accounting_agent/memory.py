"""Persist accounting-agent runs to public.agent_memory."""
from __future__ import annotations

from typing import Any

from r2r import supabase_rest
from r2r.accounting_agent.constants import ACCOUNTING_AGENT_NAME


def _slim_execution(execution: dict[str, Any] | None) -> dict[str, Any] | None:
    if not execution:
        return None
    stored = dict(execution)
    stored.pop("finance_controller_notifications", None)
    stored.pop("context_po_id", None)
    stored.pop("context_supplier_id", None)
    stored.pop("action_log", None)
    return stored


def _supplier_entry(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_supplier_id": result.get("provider_supplier_id"),
        "supplier_name": result.get("supplier_name"),
        "success": result.get("success") is not False,
        "error": result.get("error"),
        "decision": result.get("decision"),
        "execution": _slim_execution(result.get("execution")),
        "verification": result.get("verification"),
        "llm_review": result.get("llm_review"),
        "llm_info": result.get("llm_info"),
        "explanation": result.get("explanation"),
    }


def store_org_close_memory(
    *,
    event: dict[str, Any],
    results: list[dict[str, Any]],
    accounting_period: dict[str, Any] | None = None,
) -> None:
    """One agent_memory row per organization close (all suppliers nested)."""
    suppliers = [_supplier_entry(result) for result in results]
    notifications: list[dict[str, Any]] = []
    for result in results:
        notifications.extend(result.get("finance_controller_notifications") or [])

    confidences = [
        float(entry["decision"]["confidence"])
        for entry in suppliers
        if isinstance((entry.get("decision") or {}).get("confidence"), (int, float))
    ]
    decision_types = [
        entry["decision"]["decision_type"]
        for entry in suppliers
        if (entry.get("decision") or {}).get("decision_type")
    ]
    failed_ids = [
        entry["provider_supplier_id"]
        for entry in suppliers
        if not entry.get("success")
    ]
    supplier_ids = [entry["provider_supplier_id"] for entry in suppliers if entry.get("provider_supplier_id")]

    supabase_rest.insert(
        "agent_memory",
        {
            "agent_name": ACCOUNTING_AGENT_NAME,
            "organization_id": event["organization_id"],
            "user_id": None,
            "event_type": event["event_type"],
            "decision_type": "org_close",
            "confidence": (sum(confidences) / len(confidences)) if confidences else 0,
            "context_snapshot": {
                "event": {
                    "event_type": event.get("event_type"),
                    "organization_id": event.get("organization_id"),
                    "occurred_at": event.get("occurred_at"),
                    "business_event_type": event.get("business_event_type"),
                },
                "accounting_period": accounting_period,
                "supplier_ids": supplier_ids,
                "supplier_count": len(suppliers),
            },
            "execution_plan": {
                "supplier_count": len(suppliers),
                "decision_types": list(dict.fromkeys(decision_types)),
            },
            "execution_result": {
                "success": len(failed_ids) == 0,
                "suppliers": suppliers,
            },
            "verification_result": {
                "success": len(failed_ids) == 0,
                "failed_supplier_ids": failed_ids,
            },
            "explanation": {
                "decision": "org_close",
                "reason": [
                    f"{len(suppliers)} supplier run(s)",
                    f"{len(notifications)} finance-controller notification(s)",
                ],
                "evidence": decision_types,
                "confidence": (sum(confidences) / len(confidences) * 100) if confidences else 0,
            },
            "finance_controller_notifications": notifications,
        },
    )
