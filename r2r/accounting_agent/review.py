"""Deterministic verifier + human-readable explanation."""
from __future__ import annotations

from typing import Any


def verify_execution(context: dict[str, Any], decision: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    checks = [
        {
            "check": "Execution success",
            "passed": bool(execution.get("success")),
            "details": (
                "Execution finished without runtime errors."
                if execution.get("success")
                else f"Execution failed: {execution.get('error') or 'unknown error'}"
            ),
        },
        {
            "check": "Accounting period open",
            "passed": bool(context["accounting_period"]["is_open"]),
            "details": (
                "Posting period is open."
                if context["accounting_period"]["is_open"]
                else "Posting period is closed."
            ),
        },
    ]
    posting_decisions = {
        "create_cost_accrual",
        "release_existing_accrual",
        "create_prepaid_asset",
    }
    required = decision.get("decision_type") in posting_decisions
    has_entry = bool(execution.get("provider_entry_id")) if required else True
    checks.append({
        "check": "ERP entry reference",
        "passed": has_entry,
        "details": (
            "Exact entry id present for posting decisions."
            if has_entry
            else "Exact entry id missing for a posting decision."
        ),
    })
    return {"success": all(c["passed"] for c in checks), "checks": checks}


def generate_explanation(
    decision: dict[str, Any],
    execution: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    failed = [c for c in verification.get("checks") or [] if not c.get("passed")]
    return {
        "decision": decision.get("decision_type"),
        "reason": decision.get("reason") or [],
        "evidence": decision.get("evidence") or [],
        "confidence": float(f"{float(decision.get('confidence') or 0) * 100:.2f}"),
        "execution_summary": (
            f"Execution completed. Exact entry: {execution.get('provider_entry_id') or 'n/a'}."
            if execution.get("success")
            else f"Execution failed: {execution.get('error') or 'unknown error'}."
        ),
        "verification_summary": (
            "All verification checks passed."
            if verification.get("success")
            else f"{len(failed)} verification checks failed."
        ),
    }
