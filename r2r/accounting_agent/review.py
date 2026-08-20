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
        "release_prepaid_asset",
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
    proposal = execution.get("journal_proposal") or {}
    debit = proposal.get("debit_account")
    credit = proposal.get("credit_account")
    if required and debit and credit:
        balanced = debit != credit
        checks.append({
            "check": "Debit and credit accounts differ",
            "passed": balanced,
            "details": (
                f"Posted {debit} / {credit}."
                if balanced
                else f"Both legs posted to {debit}; prepaid/accrual release must hit expense and balance-sheet GLs."
            ),
        })
    return {"success": all(c["passed"] for c in checks), "checks": checks}


def generate_explanation(
    decision: dict[str, Any],
    execution: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    failed = [c["check"] for c in verification.get("checks") or [] if not c.get("passed")]
    proposal = execution.get("journal_proposal") or {}
    posting = None
    if execution.get("provider_entry_id") or proposal:
        posting = {
            "provider_entry_id": execution.get("provider_entry_id"),
            "entry_number": execution.get("entry_number"),
            "amount": proposal.get("amount"),
            "debit_account": proposal.get("debit_account"),
            "credit_account": proposal.get("credit_account"),
            "posting_date": proposal.get("posting_date"),
        }
    return {
        "decision": decision.get("decision_type"),
        "confidence": round(float(decision.get("confidence") or 0), 4),
        "execution_summary": (
            f"Posted {proposal.get('amount')} {proposal.get('currency') or ''} "
            f"{proposal.get('debit_account')}/{proposal.get('credit_account')} "
            f"entry {execution.get('provider_entry_id')}."
            if execution.get("success") and execution.get("provider_entry_id")
            else (
                "Execution completed with no ERP posting."
                if execution.get("success")
                else f"Execution failed: {execution.get('error') or 'unknown error'}."
            )
        ),
        "verification_summary": (
            "All verification checks passed."
            if verification.get("success")
            else f"Failed: {', '.join(failed) or 'unknown'}."
        ),
        "posting": posting,
    }
