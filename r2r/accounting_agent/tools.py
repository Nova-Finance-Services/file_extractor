"""Agent tool schemas and execution."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from r2r.accounting_agent.executor import (
    build_journal_proposal,
    document_cost_gl_for_decision,
    resolve_effective_cost_gl_account,
)
from r2r.accounting_agent.prepaid_status import get_prepaid_status

# Human-approval workflow is off. Over-threshold accruals/prepaids notify the
# finance controller (agent_memory.finance_controller_notifications) instead.
HUMAN_APPROVAL_ENABLED = False
_OVER_THRESHOLD_POSTING = {"create_cost_accrual", "create_prepaid_asset"}

_REASON = {
    "type": "string",
    "description": "Short human-readable justification tied to the policy/context.",
}
_COST_GL = {
    "type": "string",
    "description": (
        "Optional expense GL from available_gl_accounts. Document GL is preferred first "
        "(Nova glaccount_code on PO; Exact line GL on PINV). Use this only when the document "
        "has no GL and evidence points to another catalog code. Accrued-cost and prepaid GLs "
        "always stay on org defaults."
    ),
}

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_cost_accrual",
            "description": (
                "Post a cost accrual journal (debit cost, credit accrued cost) for a "
                "delivered-but-not-invoiced PO. Amount must be VAT-exclusive (net of VAT). "
                "When supplier_context has multiple POs, pass provider_purchase_order_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Accrual amount VAT-exclusive (excl. VAT). Omit to use the document net amount.",
                    },
                    "description": {"type": "string"},
                    "provider_purchase_order_id": {
                        "type": "string",
                        "description": "Exact PO id from supplier_context.purchase_orders.",
                    },
                    "cost_gl_account_code": _COST_GL,
                    "reason": _REASON,
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "release_existing_accrual",
            "description": (
                "Reverse/release a previously booked accrual because the invoice has now been received. "
                "Pass provider_purchase_order_id when multiple POs are in context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "provider_purchase_order_id": {"type": "string"},
                    "cost_gl_account_code": _COST_GL,
                    "reason": _REASON,
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_prepaid_status",
            "description": (
                "Read-only: compute prepaid balance for one PINV from existing_journals "
                "(setup, released_to_date, remaining, service dates, suggested_release). "
                "Call this BEFORE release_prepaid_asset. If service dates are unclear or "
                "can_release is false, notify finance controller instead of releasing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_purchase_invoice_id": {
                        "type": "string",
                        "description": "Exact PINV id (from supplier_context or pinv:{id} in journal descriptions).",
                    },
                    "reason": _REASON,
                },
                "required": ["provider_purchase_invoice_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_prepaid_asset",
            "description": (
                "Book a prepaid expense asset ONCE (debit prepaid, credit cost) when an invoice covers "
                "multiple future periods and existing_journals do not already show a prepaid setup for "
                "that PINV. Pass provider_purchase_invoice_id from supplier_context. Always set description "
                "to include inv number and service window, e.g. `inv 12345 | service 2026-08-01 to 2026-12-31`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Full prepaid amount (VAT-excl); omit to use the invoice amount.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Must include inv number and service start/end, e.g. `inv 12345 | service 2026-08-01 to 2026-12-31`.",
                    },
                    "provider_purchase_invoice_id": {"type": "string"},
                    "cost_gl_account_code": _COST_GL,
                    "reason": _REASON,
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "release_prepaid_asset",
            "description": (
                "Amortize prepaid into cost for the CURRENT period only (debit cost, credit prepaid). "
                "ALWAYS call get_prepaid_status first and use its suggested_release as amount. "
                "Pass provider_purchase_invoice_id. Set description with inv # + service window from the "
                "status result. If can_release is false or service dates unclear, do not post — "
                "notify_finance_controller instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Period slice to release; must be get_prepaid_status.suggested_release.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Must include inv number and service start/end, e.g. `inv 12345 | service 2026-08-01 to 2026-12-31`.",
                    },
                    "provider_purchase_invoice_id": {"type": "string"},
                    "cost_gl_account_code": _COST_GL,
                    "reason": _REASON,
                },
                "required": ["reason"],
            },
        },
    },
    # request_human_approval is kept in the catalog but omitted from get_agent_tools()
    # while HUMAN_APPROVAL_ENABLED is False.
    {
        "type": "function",
        "function": {
            "name": "request_human_approval",
            "description": "Request human approval instead of auto-posting (incomplete context or amount above threshold).",
            "parameters": {
                "type": "object",
                "properties": {"reason": _REASON},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_finance_controller",
            "description": "Escalate to the finance controller and stop automated posting (e.g. closed accounting period).",
            "parameters": {
                "type": "object",
                "properties": {"reason": _REASON},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_finance_controller",
            "description": (
                "Record a message for the finance controller inbox (stored on "
                "agent_memory.finance_controller_notifications). Use when prepaid metadata is "
                "missing/unclear, or any case needing human attention without posting. No ERP posting."
            ),
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_no_action",
            "description": "Record that no accounting action is required for this supplier/event.",
            "parameters": {
                "type": "object",
                "properties": {"reason": _REASON},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize",
            "description": (
                "Record the final decision for this supplier run. Call exactly once after actions. "
                "You may post multiple journals first (accrual/prepaid create/release) then finalize "
                "with the primary decision_type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "decision_type": {
                        "type": "string",
                        "enum": [
                            "create_cost_accrual",
                            "release_existing_accrual",
                            "create_prepaid_asset",
                            "release_prepaid_asset",
                            "no_action",
                            "request_human_approval",
                            "escalate_to_finance_controller",
                        ],
                    },
                    "confidence": {"type": "number", "description": "0..1 confidence in the decision."},
                    "requires_human_approval": {"type": "boolean"},
                    "reason": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["decision_type", "confidence", "requires_human_approval", "reason"],
            },
        },
    },
]


def get_agent_tools() -> list[dict[str, Any]]:
    if HUMAN_APPROVAL_ENABLED:
        return AGENT_TOOLS
    return [
        tool for tool in AGENT_TOOLS
        if tool["function"]["name"] != "request_human_approval"
    ]


def create_initial_state() -> dict[str, Any]:
    return {
        "actionLog": [],
        "toolSequence": [],
        "toolTimeline": [],
        "financeControllerNotifications": [],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _period_guard(context: dict[str, Any]) -> Optional[str]:
    if not context["accounting_period"]["is_open"]:
        return "REJECTED: accounting period is closed; posting is not allowed. Escalate to the finance controller instead."
    return None


def _threshold_guard(context: dict[str, Any], decision_type: str, args: dict[str, Any]) -> Optional[str]:
    if HUMAN_APPROVAL_ENABLED or decision_type not in _OVER_THRESHOLD_POSTING:
        return None
    amount = args.get("amount") if isinstance(args.get("amount"), (int, float)) else context["derived_metrics"]["amount"]
    limit = context["organization_policy"]["requires_approval_above"]
    try:
        amount_n = float(amount or 0)
        limit_n = float(limit)
    except (TypeError, ValueError):
        return None
    if amount_n < limit_n:
        return None
    return (
        f"REJECTED: amount {amount_n} is at/above finance-controller threshold {limit_n}. "
        "Do not post this accrual/prepaid. Call notify_finance_controller with amount, "
        "document id, and the booking you would have made so the finance controller can do it."
    )


def _record_timeline(state: dict[str, Any], entry: dict[str, Any]) -> None:
    state["toolTimeline"].append({"at": _now(), **entry})


def _push_finance_notification(
    state: dict[str, Any],
    context: dict[str, Any],
    kind: str,
    message: str,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    extra = extra or {}
    trimmed = (message or "").strip()
    if not trimmed:
        return
    state["financeControllerNotifications"].append({
        "at": _now(),
        "message": trimmed,
        "kind": kind,
        "provider_supplier_id": (context.get("supplier_context") or {}).get("provider_supplier_id"),
        "provider_purchase_order_id": extra.get("provider_purchase_order_id")
        or context["po_context"].get("provider_purchase_order_id"),
        "provider_purchase_invoice_id": extra.get("provider_purchase_invoice_id")
        or context["purchase_invoice_context"].get("provider_purchase_invoice_id"),
    })


def _post(
    context: dict[str, Any],
    tools: dict[str, Callable],
    state: dict[str, Any],
    tool_name: str,
    decision_type: str,
    runner: Callable,
    args: dict[str, Any],
    verb: str,
) -> dict[str, Any]:
    blocked = _period_guard(context) or _threshold_guard(context, decision_type, args)
    if blocked:
        if "at/above finance-controller threshold" in blocked:
            _push_finance_notification(state, context, "notify", blocked, {
                "provider_purchase_order_id": args.get("provider_purchase_order_id")
                if isinstance(args.get("provider_purchase_order_id"), str)
                else None,
                "provider_purchase_invoice_id": args.get("provider_purchase_invoice_id")
                if isinstance(args.get("provider_purchase_invoice_id"), str)
                else None,
            })
            tools["notifyFinanceController"](blocked, {
                "provider_supplier_id": (context.get("supplier_context") or {}).get("provider_supplier_id"),
            })
        _record_timeline(state, {"tool": tool_name, "result": blocked})
        return {"content": blocked}

    cost_override = args.get("cost_gl_account_code") if isinstance(args.get("cost_gl_account_code"), str) else None
    resolved = resolve_effective_cost_gl_account(
        context,
        {
            "cost_gl_account_code": cost_override,
            "document_gl_account_code": document_cost_gl_for_decision(
                context,
                decision_type,
                {
                    "provider_purchase_order_id": args.get("provider_purchase_order_id")
                    if isinstance(args.get("provider_purchase_order_id"), str)
                    else None,
                    "provider_purchase_invoice_id": args.get("provider_purchase_invoice_id")
                    if isinstance(args.get("provider_purchase_invoice_id"), str)
                    else None,
                },
            ),
        },
    )
    rejected = resolved.get("rejectedOverride")
    if rejected:
        message = (
            f"Ignored invalid cost_gl_account_code {rejected}; used document or org default cost GL instead."
        )
        _push_finance_notification(
            state,
            context,
            "notify",
            message,
            {
                "provider_purchase_order_id": args.get("provider_purchase_order_id")
                if isinstance(args.get("provider_purchase_order_id"), str)
                else None,
                "provider_purchase_invoice_id": args.get("provider_purchase_invoice_id")
                if isinstance(args.get("provider_purchase_invoice_id"), str)
                else None,
            },
        )
        tools["notifyFinanceController"](message, {
            "cost_gl_account_code": rejected,
            "provider_purchase_order_id": args.get("provider_purchase_order_id"),
            "provider_purchase_invoice_id": args.get("provider_purchase_invoice_id"),
            "provider_supplier_id": (context.get("supplier_context") or {}).get("provider_supplier_id"),
        })

    proposal = build_journal_proposal(
        context,
        decision_type,
        {
            "amount": args.get("amount") if isinstance(args.get("amount"), (int, float)) else None,
            "description": args.get("description") if isinstance(args.get("description"), str) else None,
            "provider_purchase_order_id": args.get("provider_purchase_order_id")
            if isinstance(args.get("provider_purchase_order_id"), str)
            else None,
            "provider_purchase_invoice_id": args.get("provider_purchase_invoice_id")
            if isinstance(args.get("provider_purchase_invoice_id"), str)
            else None,
            "cost_gl_account_code": cost_override,
        },
    )
    try:
        result = runner(proposal)
        state["providerEntryId"] = result["provider_entry_id"]
        state["entryNumber"] = result.get("entry_number")
        state["lastProposal"] = result["journal_proposal"]
        line = (
            f"{verb} in Exact entry {result['provider_entry_id']} for {proposal['amount']} "
            f"{proposal['currency']} (DR {proposal['debit_account']} / CR {proposal['credit_account']})"
        )
        state["actionLog"].append(line)
        _record_timeline(state, {"tool": tool_name, "args": args, "result": line})
        return {"content": f"OK: {line}"}
    except Exception as exc:
        message = str(exc)
        _record_timeline(state, {"tool": tool_name, "args": args, "result": f"ERROR: {message}"})
        return {"content": f"ERROR: {message}"}


def execute_agent_tool(
    name: str,
    args: dict[str, Any],
    context: dict[str, Any],
    tools: dict[str, Callable],
    state: dict[str, Any],
) -> dict[str, Any]:
    if name == "create_cost_accrual":
        state["toolSequence"].append({"tool": "CreateJournalEntry", "action": "Post cost accrual"})
        return _post(context, tools, state, name, "create_cost_accrual", tools["createJournalEntry"], args, "Posted cost accrual")
    if name == "release_existing_accrual":
        state["toolSequence"].append({"tool": "ReverseJournalEntry", "action": "Release existing accrual"})
        return _post(context, tools, state, name, "release_existing_accrual", tools["reverseJournalEntry"], args, "Released accrual via reversal")
    if name == "create_prepaid_asset":
        state["toolSequence"].append({"tool": "CreatePrepaidJournal", "action": "Book prepaid asset"})
        return _post(context, tools, state, name, "create_prepaid_asset", tools["createPrepaidJournal"], args, "Booked prepaid asset")
    if name == "get_prepaid_status":
        state["toolSequence"].append({"tool": "GetPrepaidStatus", "action": "Compute prepaid balance"})
        pinv_id = str(args.get("provider_purchase_invoice_id") or "").strip()
        if not pinv_id:
            msg = "ERROR: provider_purchase_invoice_id is required"
            _record_timeline(state, {"tool": name, "args": args, "result": msg})
            return {"content": msg}
        status = get_prepaid_status(context, pinv_id)
        line = (
            f"Prepaid status for {pinv_id}: remaining={status['remaining']}, "
            f"suggested_release={status['suggested_release']}, can_release={status['can_release']}"
        )
        state["actionLog"].append(line)
        _record_timeline(state, {"tool": name, "args": args, "result": json.dumps(status)})
        return {"content": json.dumps(status)}
    if name == "release_prepaid_asset":
        state["toolSequence"].append({"tool": "ReversePrepaidJournal", "action": "Release prepaid asset"})
        return _post(context, tools, state, name, "release_prepaid_asset", tools["createJournalEntry"], args, "Released prepaid into cost")
    if name == "request_human_approval":
        # Disabled: same path as notify_finance_controller.
        state["toolSequence"].append({"tool": "NotifyFinanceController", "action": "Notify"})
        reason = str(args.get("reason") or "needs finance-controller attention")
        message = f"Needs finance controller: {reason}"
        _push_finance_notification(state, context, "notify", message, {
            "provider_purchase_order_id": context["po_context"].get("provider_purchase_order_id"),
        })
        tools["notifyFinanceController"](message, {
            "provider_purchase_order_id": context["po_context"].get("provider_purchase_order_id"),
            "provider_supplier_id": (context.get("supplier_context") or {}).get("provider_supplier_id"),
        })
        line = f"Notified finance controller: {reason}"
        state["actionLog"].append(line)
        _record_timeline(state, {"tool": name, "args": args, "result": line})
        return {"content": f"OK: {line}"}
    if name == "escalate_to_finance_controller":
        state["toolSequence"].append({"tool": "NotifyFinanceController", "action": "Escalate"})
        reason = str(args.get("reason") or "escalation")
        message = f"Escalation: {reason}"
        _push_finance_notification(state, context, "escalate", message, {
            "provider_purchase_order_id": context["po_context"].get("provider_purchase_order_id"),
        })
        tools["notifyFinanceController"](message, {
            "provider_purchase_order_id": context["po_context"].get("provider_purchase_order_id"),
            "provider_supplier_id": (context.get("supplier_context") or {}).get("provider_supplier_id"),
        })
        line = f"Escalated to finance controller: {reason}"
        state["actionLog"].append(line)
        _record_timeline(state, {"tool": name, "args": args, "result": line})
        return {"content": f"OK: {line}"}
    if name == "notify_finance_controller":
        state["toolSequence"].append({"tool": "NotifyFinanceController", "action": "Notify"})
        message = str(args.get("message") or "")
        _push_finance_notification(state, context, "notify", message)
        tools["notifyFinanceController"](message, {
            "provider_supplier_id": (context.get("supplier_context") or {}).get("provider_supplier_id"),
        })
        line = f"Notified finance controller: {message.strip()}" if message.strip() else "Notified finance controller"
        state["actionLog"].append(line)
        _record_timeline(state, {"tool": name, "args": args, "result": line})
        return {"content": f"OK: {line}"}
    if name == "record_no_action":
        state["toolSequence"].append({"tool": "RecordNoAction", "action": "No action"})
        reason = str(args.get("reason") or "no action required")
        state["actionLog"].append(f"No action: {reason}")
        _record_timeline(state, {"tool": name, "args": args, "result": reason})
        return {"content": f"OK: recorded no action ({reason})"}
    if name == "finalize":
        amount = context["derived_metrics"]["amount"]
        over_threshold = amount >= context["organization_policy"]["requires_approval_above"]
        reason = args.get("reason")
        decision_type = args.get("decision_type") or "no_action"
        if not HUMAN_APPROVAL_ENABLED and decision_type == "request_human_approval":
            decision_type = "escalate_to_finance_controller"
        decision = {
            "decision_type": decision_type,
            "confidence": args["confidence"] if isinstance(args.get("confidence"), (int, float)) else 0.5,
            "requires_human_approval": (
                bool(args.get("requires_human_approval")) or over_threshold
                if HUMAN_APPROVAL_ENABLED
                else False
            ),
            "reason": reason if isinstance(reason, list) and reason else ["Decision recorded by AI agent."],
            "evidence": args.get("evidence") if isinstance(args.get("evidence"), list) else [],
            "preferred_tools": [s["tool"] for s in state["toolSequence"]],
        }
        _record_timeline(state, {"tool": name, "args": args, "result": decision["decision_type"]})
        return {"content": "Decision recorded.", "finalDecision": decision}

    _record_timeline(state, {"tool": name, "args": args, "result": "Unknown tool"})
    return {"content": f"Unknown tool: {name}"}
