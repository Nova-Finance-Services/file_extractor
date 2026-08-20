"""Thin operating prompts. Business logic lives in policies."""
from __future__ import annotations

import json
from typing import Any


def render_notify_index(rules: list[dict[str, Any]]) -> str:
    active = [r for r in rules if r.get("is_active")]
    notify = [r for r in active if r.get("notify_finance_controller")]
    lines = [
        "## Finance controller notify (from default policies)",
        "Call `notify_finance_controller` or `escalate_to_finance_controller` ONLY when an",
        "active policy listed under NOTIFY applies to this document. If the matching policy",
        "has notify_finance_controller=false, or you are skipping a post, use `record_no_action`.",
        "Never notify just because an amount is large if you are not posting.",
        "",
        "NOTIFY:",
    ]
    if notify:
        lines.extend(f"- {r['id']} — {r['name']}" for r in notify)
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def render_policies(rules: list[dict[str, Any]]) -> str:
    active = sorted(
        [r for r in rules if r.get("is_active")],
        key=lambda r: r.get("priority", 0),
        reverse=True,
    )
    standing = []
    decisions = []
    for rule in active:
        notify = "yes" if rule.get("notify_finance_controller") else "no"
        if rule.get("standing_constraint"):
            standing.append(
                f"- [STANDING] [notify={notify}] {rule['name']}\n"
                f"    {' '.join(rule.get('reason_templates') or [])}"
            )
            continue
        conditions = rule.get("conditions") or []
        if conditions:
            conds = " AND ".join(
                f"{c.get('path')} {c.get('operator')} {json.dumps(c.get('value', ''))}"
                for c in conditions
            )
        else:
            conds = "(always applies as fallback)"
        tools = rule.get("preferred_tools") or []
        tools_part = f" | preferred tools: {', '.join(tools)}" if tools else ""
        decisions.append(
            f"- [priority {rule.get('priority')}] [notify={notify}] {rule['name']} "
            f"→ decision \"{rule['decision_type']}\"\n"
            f"    when: {conds}\n"
            f"    rationale: {' '.join(rule.get('reason_templates') or [])}{tools_part}"
        )
    return "\n".join(standing + decisions)


def build_system_prompt(context: dict[str, Any]) -> str:
    policy = context["organization_policy"]
    supplier = context.get("supplier_context")
    window = context.get("period_window")
    lines = [
        "You are an AI R2R (Record-to-Report) accounting agent for P2P cost accruals",
        "and prepaid expenses at month-end / month-start close.",
        "",
        "Operating loop (always):",
        "1. Read the close context for ONE supplier.",
        "2. Follow the policy knowledge base below (highest priority wins;",
        "   STANDING constraints always apply when relevant).",
        "3. TAKE ACTION with tools. Prefer several independent tool calls in the SAME round",
        "   (one create/release per PO or PINV), then call `finalize` exactly once.",
        "Every tool call is saved as an activity step the user can review.",
        "Call tools to do the work; never describe actions you did not perform via tools.",
        "",
        "## Policy knowledge base (source of business logic)",
        render_notify_index(context["policy_knowledge"]["rules"]),
        "",
        render_policies(context["policy_knowledge"]["rules"]),
        "",
        "## Organization configuration",
        f"- Min threshold (materiality): {policy['materiality_threshold']} {context['accounting_period']['currency']}",
        f"- Max threshold: {policy['requires_approval_above']} {context['accounting_period']['currency']}. "
        "At/above this amount, do NOT post a NEW accrual or prepaid (see standing_over_threshold_notify_finance). "
        "Do not notify if you are skipping that post.",
        (
            f"- GL accounts → cost: {policy['gl_accounts']['cost_gl_account_code']}, "
            f"accrued cost: {policy['gl_accounts']['accrued_cost_gl_account_code']}, "
            f"prepaid: {policy['gl_accounts']['prepaid_gl_account_code']}"
        ),
    ]
    if window:
        lines.append(
            f"- Close window: {window['start_date']} → {window['end_date']} (current + previous two periods)"
        )
    if supplier:
        name = supplier.get("supplier_name") or supplier.get("provider_supplier_id")
        po_count = len(supplier.get("purchase_orders") or [])
        pinv_count = len(supplier.get("purchase_invoices") or [])
        lines.append(f"- Supplier in scope: {name} ({po_count} POs, {pinv_count} PINVs)")
        if po_count or pinv_count:
            lines.append(
                "- Walk every document in supplier_context. po_context and "
                "purchase_invoice_context are empty on supplier close. "
                "derived_metrics has no amount — pass THIS document's amount and id on every tool call."
            )
    return "\n".join(lines)


def build_context_prompt(context: dict[str, Any]) -> str:
    rest = {k: v for k, v in context.items() if k != "policy_knowledge"}
    return "\n".join([
        "Here is the accounting close context for this run. Decide and act using the policy knowledge base.",
        "",
        "```json",
        json.dumps(rest, indent=2, default=str),
        "```",
    ])


def build_verifier_prompt(
    context: dict[str, Any],
    decision: dict[str, Any],
    execution: dict[str, Any],
    deterministic_checks: dict[str, Any],
) -> str:
    failed = [
        c["check"]
        for c in deterministic_checks.get("checks") or []
        if not c.get("passed")
    ]
    return "\n".join([
        "You are a senior accounting reviewer. Independently assess whether the agent's",
        "decision and postings are correct for this month-end close.",
        "",
        "Check: correct decision vs. context, amount accuracy (cost accruals must be",
        "VAT-exclusive / net of VAT), correct debit/credit GL accounts, no duplicate",
        "accrual or prepaid setup vs `existing_journals`, and that nothing was posted",
        "into a closed period. If journals already show prepaid setup for a PINV,",
        "prefer release_prepaid_asset for the monthly slice — never recreate prepaid.",
        "",
        'Respond as strict JSON: {"approved": boolean, "summary": string, "concerns": string[]}.',
        "",
        f"Decision: {decision.get('decision_type')} (confidence {decision.get('confidence')})",
        f"Requires human approval: {decision.get('requires_human_approval')} (workflow disabled; use finance-controller notifications)",
        f"Period open: {context['accounting_period']['is_open']}",
        f"Existing journals in window: {len(context.get('existing_journals') or [])}",
        f"Execution success: {execution.get('success')}",
        f"Journal id: {execution.get('provider_entry_id') or 'none'}",
        f"Journal proposal: {json.dumps(execution.get('journal_proposal'), default=str)}",
        f"Deterministic checks passed: {deterministic_checks.get('success')}",
        f"Failed checks: {', '.join(failed) or 'none'}",
    ])
