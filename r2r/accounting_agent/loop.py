"""AI-only agent loop. No deterministic fallback."""
from __future__ import annotations

import json
from typing import Any, Callable

from r2r.accounting_agent.constants import MAX_AGENT_ITERATIONS
from r2r.accounting_agent.executor import build_execution_result_from_state
from r2r.accounting_agent.prompts import build_context_prompt, build_system_prompt
from r2r.accounting_agent.tools import AGENT_TOOLS, create_initial_state, execute_agent_tool


def _execution_from_state(context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return build_execution_result_from_state({
        "context": context,
        "toolTimeline": state.get("toolTimeline") or [],
        "actionLog": state.get("actionLog") or [],
        "lastProposal": state.get("lastProposal"),
        "providerEntryId": state.get("providerEntryId"),
        "entryNumber": state.get("entryNumber"),
        "financeControllerNotifications": state.get("financeControllerNotifications") or [],
    })


def _plan_from_state(decision_type: str, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_type": decision_type,
        "steps": [
            {
                "step": idx + 1,
                "action": step["action"],
                "tool": step["tool"],
                "status": "completed",
            }
            for idx, step in enumerate(state.get("toolSequence") or [])
        ],
    }


def _infer_decision_type(state: dict[str, Any]) -> str:
    tools = [s["tool"] for s in state.get("toolSequence") or []]
    if "CreatePrepaidJournal" in tools:
        return "create_prepaid_asset"
    if "ReverseJournalEntry" in tools:
        return "release_existing_accrual"
    if "CreateJournalEntry" in tools:
        return "create_cost_accrual"
    if "RequestApproval" in tools:
        return "request_human_approval"
    if "NotifyFinanceController" in tools:
        return "escalate_to_finance_controller"
    return "no_action"


def _safe_parse(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def run_accounting_agent(
    context: dict[str, Any],
    tools: dict[str, Callable],
    chat: Callable,
) -> dict[str, Any]:
    state = create_initial_state()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(context)},
        {"role": "user", "content": build_context_prompt(context)},
    ]
    final_decision = None

    try:
        for _ in range(MAX_AGENT_ITERATIONS):
            if final_decision:
                break
            response = chat(messages, AGENT_TOOLS)
            messages.append({
                "role": "assistant",
                "content": response.get("content"),
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in response.get("toolCalls") or []
                ],
            })
            if not response.get("toolCalls"):
                break
            for call in response["toolCalls"]:
                outcome = execute_agent_tool(
                    call["name"],
                    _safe_parse(call.get("arguments") or "{}"),
                    context,
                    tools,
                    state,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": outcome["content"],
                })
                if outcome.get("finalDecision"):
                    final_decision = outcome["finalDecision"]
    except Exception as error:
        llm_error = str(error)
        if state.get("toolSequence"):
            decision_type = _infer_decision_type(state)
            return {
                "decision": {
                    "decision_type": decision_type,
                    "confidence": 0.6,
                    "requires_human_approval": True,
                    "reason": [
                        f"LLM error after acting ({llm_error}); decision inferred from executed tools."
                    ],
                    "evidence": [],
                    "preferred_tools": [s["tool"] for s in state["toolSequence"]],
                },
                "plan": _plan_from_state(decision_type, state),
                "execution": _execution_from_state(context, state),
                "source": "ai_unfinalized",
                "llm_error": llm_error,
            }
        raise

    if final_decision:
        return {
            "decision": final_decision,
            "plan": _plan_from_state(final_decision["decision_type"], state),
            "execution": _execution_from_state(context, state),
            "source": "ai",
        }

    if state.get("toolSequence"):
        decision_type = _infer_decision_type(state)
        amount = context["derived_metrics"]["amount"]
        return {
            "decision": {
                "decision_type": decision_type,
                "confidence": 0.6,
                "requires_human_approval": amount >= context["organization_policy"]["requires_approval_above"],
                "reason": [
                    "AI agent acted but did not call finalize; decision inferred from executed tools."
                ],
                "evidence": [],
                "preferred_tools": [s["tool"] for s in state["toolSequence"]],
            },
            "plan": _plan_from_state(decision_type, state),
            "execution": _execution_from_state(context, state),
            "source": "ai_unfinalized",
        }

    raise RuntimeError(
        "AI agent did not finalize or take action. Retry or check LLM provider availability."
    )
