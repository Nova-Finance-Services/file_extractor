"""Persist accounting-agent runs to public.agent_memory."""
from __future__ import annotations

from typing import Any

from r2r import supabase_rest
from r2r.accounting_agent.constants import ACCOUNTING_AGENT_NAME


def store_memory(record: dict[str, Any]) -> None:
    context = record["context_snapshot"]
    supplier = context.get("supplier_context") or {}
    timeline = (record.get("execution_result") or {}).get("tool_timeline") or []
    supabase_rest.insert(
        "agent_memory",
        {
            "agent_name": ACCOUNTING_AGENT_NAME,
            "organization_id": record["organization_id"],
            "user_id": None,
            "event_type": record["event_type"],
            "decision_type": record["decision_type"],
            "confidence": record["confidence"],
            "context_snapshot": context,
            "execution_plan": {
                "decision_source": record.get("decision_source"),
                "llm_info": record.get("llm_info"),
                "provider_supplier_id": supplier.get("provider_supplier_id"),
                "supplier_name": supplier.get("supplier_name"),
                "tool_timeline": timeline,
                "steps": [
                    {
                        "step": idx + 1,
                        "tool": item.get("tool"),
                        "action": item.get("action"),
                        "at": item.get("at"),
                        "args": item.get("args"),
                        "result": item.get("result"),
                    }
                    for idx, item in enumerate(timeline)
                ],
            },
            "execution_result": record["execution_result"],
            "verification_result": record["verification_result"],
            "explanation": record["explanation"],
            "finance_controller_notifications": record.get("finance_controller_notifications")
            or (record.get("execution_result") or {}).get("finance_controller_notifications")
            or [],
        },
    )
