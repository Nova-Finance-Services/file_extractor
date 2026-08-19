"""Default accounting policies (business logic for the LLM, not a prompt dump)."""
from __future__ import annotations

from typing import Any

ACCOUNTING_AGENT_POLICY_KEY = "r2r.accounting-agent"

# Easy control: finance-controller inbox.
# Add/remove a policy id here (and keep that rule is_active) to allow notify.
# Anything not in this set must use record_no_action or post — never notify.
# Turn a case off by removing its id, or set that rule's is_active to False.
NOTIFY_FINANCE_CONTROLLER_POLICY_IDS = {
    "standing_over_threshold_notify_finance",
    "escalate_closed_period",
    "request_approval_missing_context",
    "escalate_uncertain_subscription_continuation",
    "standing_prepaid_lifecycle",
    "release_prepaid_asset_current_period",
}

DEFAULT_POLICY_RULES: list[dict[str, Any]] = [
    {
        "id": "standing_accrual_exclude_vat",
        "name": "Exclude VAT from cost accrual amounts",
        "decision_type": "create_cost_accrual",
        "priority": 100,
        "confidence": 1,
        "requires_human_approval": False,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "When creating a cost accrual, always post the VAT-exclusive (net) amount only. Never include VAT in the journal amount — VAT is recoverable input tax, not a period cost. Prefer Exact AmountDC/AmountFC (excl. VAT). If only a VAT-inclusive/gross figure is available, subtract VAT before calling create_cost_accrual.",
        ],
        "evidence_paths": [
            "derived_metrics.amount",
            "po_context.amount",
            "purchase_invoice_context.amount",
        ],
        "preferred_tools": ["CreateJournalEntry"],
        "is_active": True,
    },
    {
        "id": "standing_amounts_from_documents",
        "name": "Do not invent amounts — use document or tool values",
        "decision_type": "no_action",
        "priority": 100,
        "confidence": 1,
        "requires_human_approval": False,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "Never invent amounts. Use the PO/PINV net amount you act on, or get_prepaid_status.suggested_release for prepaid releases. On supplier batches do not use derived_metrics as a primary amount when multiple documents exist.",
        ],
        "evidence_paths": [
            "supplier_context.purchase_orders",
            "supplier_context.purchase_invoices",
            "derived_metrics.amount",
        ],
        "preferred_tools": [],
        "is_active": True,
    },
    {
        "id": "standing_materiality_min_threshold",
        "name": "Respect org min threshold (materiality floor)",
        "decision_type": "no_action",
        "priority": 100,
        "confidence": 1,
        "requires_human_approval": False,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "Do not auto-post accruals or prepaid journals when the amount acted on is below organization_policy.materiality_threshold (from p2p_settings.accounting_min_threshold). Call record_no_action instead for immaterial amounts. Do not notify the finance controller.",
        ],
        "evidence_paths": [
            "organization_policy.materiality_threshold",
            "derived_metrics.amount",
        ],
        "preferred_tools": ["RecordNoAction"],
        "is_active": True,
    },
    {
        # Human approval is disabled. Over-threshold bookings go to the finance controller.
        "id": "standing_approval_threshold",
        "name": "Flag human approval when amount is at/above org max threshold",
        "decision_type": "request_human_approval",
        "priority": 100,
        "confidence": 1,
        "requires_human_approval": True,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "If the amount acted on is at/above organization_policy.requires_approval_above (from p2p_settings.accounting_max_threshold), set requires_human_approval: true when finalizing (still record the proposal / postings already taken).",
        ],
        "evidence_paths": [
            "organization_policy.requires_approval_above",
            "derived_metrics.amount",
        ],
        "preferred_tools": ["RequestApproval"],
        "is_active": False,
    },
    {
        "id": "standing_over_threshold_notify_finance",
        "name": "Notify finance controller instead of posting accrual/prepaid at/above max threshold",
        "decision_type": "escalate_to_finance_controller",
        "priority": 100,
        "confidence": 1,
        "requires_human_approval": False,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "Applies ONLY when you would otherwise POST a NEW cost accrual or prepaid setup AND that amount is at/above organization_policy.requires_approval_above. Then do NOT post: call notify_finance_controller with amount, PO/PINV id, and the journal you would have booked, then finalize escalate_to_finance_controller. Does NOT apply if you are skipping the post (accrual/prepaid already in existing_journals, below materiality, prepaid fully released). Releases of already-booked accruals/prepaids may still post even over the threshold.",
        ],
        "evidence_paths": [
            "organization_policy.requires_approval_above",
            "derived_metrics.amount",
        ],
        "preferred_tools": ["NotifyFinanceController"],
        "is_active": True,
    },
    {
        "id": "standing_multi_document_walk",
        "name": "Walk every PO and PINV independently on supplier batches",
        "decision_type": "no_action",
        "priority": 99,
        "confidence": 1,
        "requires_human_approval": False,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "MULTI-DOCUMENT RUN: walk EVERY PO and EVERY PINV in supplier_context. Decide each document independently from its own fields + matching existing_journals (po:{id} / pinv:{id}). Call several create/release tools in one run if needed, then finalize once. On supplier batches, purchase_invoice_context and prepaid fields on derived_metrics are intentionally empty/neutral — do NOT pick a primary invoice. Use only supplier_context.purchase_invoices[*] (amount, service_period_*, invoice_months_covered, prepaid_monthly_release_amount) per id.",
        ],
        "evidence_paths": [
            "supplier_context.purchase_orders",
            "supplier_context.purchase_invoices",
            "existing_journals",
        ],
        "preferred_tools": [],
        "is_active": True,
    },
    {
        "id": "standing_read_existing_journals",
        "name": "Use existing_journals to avoid duplicate creates and drive releases",
        "decision_type": "no_action",
        "priority": 98,
        "confidence": 1,
        "requires_human_approval": False,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "Read existing_journals (close window = current + previous two periods). Lines are tagged with role cost / accrued_cost / prepaid and po:{id} / pinv:{id} in description/notes. From that, decide whether an accrual or prepaid was already created or released — do not duplicate creates; prefer the matching release when appropriate. If you skip a duplicate create, call record_no_action and do NOT notify_finance_controller.",
        ],
        "evidence_paths": ["existing_journals", "period_window"],
        "preferred_tools": [],
        "is_active": True,
    },
    {
        "id": "standing_cost_gl_account_override",
        "name": "Prefer org default cost GL; override only from catalog with evidence",
        "decision_type": "no_action",
        "priority": 98,
        "confidence": 1,
        "requires_human_approval": False,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "Cost GL priority for the expense leg: (1) document GL when present and in available_gl_accounts — Nova purchase_orders.glaccount_code for PO accruals/releases, Exact PurchaseEntryLine GLAccountCode for PINV prepaid create/release; (2) else optional cost_gl_account_code on the tool when evidence clearly supports another catalog code; (3) else organization_policy.gl_accounts.cost_gl_account_code. Never invent GL codes. Accrued-cost and prepaid balance-sheet accounts always stay on org defaults — do not try to override them.",
        ],
        "evidence_paths": [
            "organization_policy.gl_accounts",
            "available_gl_accounts",
            "po_context.gl_account_code",
            "purchase_invoice_context.gl_account_code",
            "existing_journals",
            "po_context.description",
            "purchase_invoice_context.description",
            "supplier_context.purchase_orders",
            "supplier_context.purchase_invoices",
        ],
        "preferred_tools": [],
        "is_active": True,
    },
    {
        "id": "standing_prepaid_lifecycle",
        "name": "Prepaid lifecycle procedure (create once, release via status tool)",
        "decision_type": "release_prepaid_asset",
        "priority": 97,
        "confidence": 1,
        "requires_human_approval": False,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "Prepaid lifecycle — apply PER PINV. Example: 3000 invoice for Aug–Oct → create prepaid 3000 once, then release 1000 in Aug/Sep/Oct. Example: 12000 annual Jan–Dec → create 12000 once if no setup in journals; if setup exists, release the current-month slice only.",
            "Create prepaid ONCE only when journals do NOT already show a prepaid setup for THAT PINV. Different PINVs need separate tool calls — never release PINV A using PINV B's id or amount.",
            "Before ANY release_prepaid_asset: call get_prepaid_status with that provider_purchase_invoice_id and use suggested_release as the amount. If can_release is false, or flags include service_dates_missing_or_unclear / no_prepaid_setup_found (e.g. prepaid booked outside Nova with no inv/service/pinv metadata): do NOT release — call notify_finance_controller with a clear message (stored for the finance controller inbox). If remaining is 0 / fully_released: record_no_action. On last_service_month_true_up, release the full remaining.",
            "Always pass description on create/release prepaid with inv number and full service window, e.g. `inv 12345 | service 2026-08-01 to 2026-12-31` (copy from get_prepaid_status when the PINV is outside the close window).",
        ],
        "evidence_paths": [
            "existing_journals",
            "supplier_context.purchase_invoices",
            "derived_metrics.current_period_key",
        ],
        "preferred_tools": [
            "GetPrepaidStatus",
            "CreatePrepaidJournal",
            "CreateJournalEntry",
            "NotifyFinanceController",
        ],
        "is_active": True,
    },
    {
        "id": "standing_prefer_no_action",
        "name": "Prefer no_action when no policy requires posting",
        "decision_type": "no_action",
        "priority": 96,
        "confidence": 1,
        "requires_human_approval": False,
        "standing_constraint": True,
        "conditions": [],
        "reason_templates": [
            "Prefer record_no_action when no active decision policy requires a posting for the documents in scope. Do not notify the finance controller.",
        ],
        "evidence_paths": ["event.event_type"],
        "preferred_tools": ["RecordNoAction"],
        "is_active": True,
    },
    {
        "id": "escalate_closed_period",
        "name": "Escalate if accounting period is closed",
        "decision_type": "escalate_to_finance_controller",
        "priority": 100,
        "confidence": 0.99,
        "requires_human_approval": True,
        "conditions": [
            {"path": "accounting_period.is_open", "operator": "eq", "value": False},
        ],
        "reason_templates": [
            "Accounting period is closed; automation cannot post journals safely. Call escalate_to_finance_controller then finalize with that decision_type.",
        ],
        "evidence_paths": ["derived_metrics.current_period_key"],
        "preferred_tools": ["NotifyFinanceController"],
        "is_active": True,
    },
    {
        "id": "request_approval_missing_context",
        "name": "Notify finance controller for incomplete context",
        "decision_type": "escalate_to_finance_controller",
        "priority": 90,
        "confidence": 0.75,
        "requires_human_approval": False,
        "conditions": [{"path": "data_quality.is_complete", "operator": "eq", "value": False}],
        "reason_templates": [
            "Context is incomplete and posting requirements are not met. Do not post. Call notify_finance_controller with the missing fields, then finalize with escalate_to_finance_controller.",
        ],
        "evidence_paths": ["data_quality.missing_fields"],
        "preferred_tools": ["NotifyFinanceController"],
        "is_active": True,
    },
    {
        "id": "release_existing_accrual_when_invoiced",
        "name": "Release existing accrual when invoice is received",
        "decision_type": "release_existing_accrual",
        "priority": 80,
        "confidence": 0.94,
        "requires_human_approval": False,
        "conditions": [
            {"path": "po_context.invoice_received", "operator": "eq", "value": True},
        ],
        "reason_templates": [
            "If existing_journals already show a cost accrual for this PO (and not yet released), release it because the invoice has now been received. Post the release in the same accounting period as the invoice. Pass provider_purchase_order_id when multiple POs are in scope.",
        ],
        "evidence_paths": [
            "po_context.provider_purchase_order_id",
            "existing_journals",
            "purchase_invoice_context.provider_purchase_invoice_id",
        ],
        "preferred_tools": ["ReverseJournalEntry", "CreateJournalEntry"],
        "is_active": True,
    },
    {
        "id": "release_prepaid_asset_current_period",
        "name": "Release prepaid into cost for the current close period",
        "decision_type": "release_prepaid_asset",
        "priority": 75,
        "confidence": 0.95,
        "requires_human_approval": False,
        "conditions": [
            {"path": "event.event_type", "operator": "in", "value": ["month_start", "month_end"]},
        ],
        "reason_templates": [
            "When journals (or supplier_context PINVs) indicate an open prepaid for a PINV whose service covers the current period: call get_prepaid_status, then release_prepaid_asset with suggested_release. Do not recreate the prepaid asset. If can_release is false or metadata is missing, notify_finance_controller instead. On supplier batches evaluate per PINV from supplier_context + journals, not derived_metrics.",
        ],
        "evidence_paths": [
            "existing_journals",
            "supplier_context.purchase_invoices",
            "purchase_invoice_context.provider_purchase_invoice_id",
            "derived_metrics.current_period_key",
        ],
        "preferred_tools": [
            "GetPrepaidStatus",
            "CreateJournalEntry",
            "NotifyFinanceController",
        ],
        "is_active": True,
    },
    {
        "id": "create_prepaid_asset_multi_period_invoice",
        "name": "Create prepaid when invoice spans multiple periods",
        "decision_type": "create_prepaid_asset",
        "priority": 70,
        "confidence": 0.97,
        "requires_human_approval": False,
        "conditions": [
            {"path": "event.event_type", "operator": "in", "value": ["month_start", "month_end"]},
        ],
        "reason_templates": [
            "When a PINV spans multiple accounting periods (invoice_months_covered > 1 on that PINV) and existing_journals do not already contain a prepaid setup for that pinv:{id}: create_prepaid_asset once for the full VAT-exclusive amount. Always set description with `inv <number> | service YYYY-MM-DD to YYYY-MM-DD`. On supplier batches use supplier_context.purchase_invoices[*] per id — do not rely on purchase_invoice_context / derived_metrics when multiple PINVs exist.",
        ],
        "evidence_paths": [
            "supplier_context.purchase_invoices",
            "purchase_invoice_context.provider_purchase_invoice_id",
            "purchase_invoice_context.service_period_start",
            "purchase_invoice_context.service_period_end",
            "existing_journals",
        ],
        "preferred_tools": [
            "CreatePrepaidJournal",
            "CreateJournalEntry",
        ],
        "is_active": True,
    },
    {
        "id": "create_cost_accrual_po_delivered_not_invoiced",
        "name": "Create cost accrual for delivered PO without invoice",
        "decision_type": "create_cost_accrual",
        "priority": 60,
        "confidence": 0.95,
        "requires_human_approval": False,
        "conditions": [
            {"path": "po_context.is_delivered", "operator": "eq", "value": True},
            {"path": "po_context.invoice_received", "operator": "eq", "value": False},
            {"path": "derived_metrics.amount", "operator": "gte", "value": 1},
        ],
        "reason_templates": [
            "PO is delivered and not invoiced, so the period requires cost accrual recognition (VAT-exclusive amount) unless existing_journals already show that accrual for this PO — then record_no_action and do not notify. On supplier batches apply per PO in supplier_context.purchase_orders using that PO's amount and po:{id} journal matches. Skip when amount is below organization_policy.materiality_threshold.",
        ],
        "evidence_paths": [
            "po_context.purchase_order_id",
            "po_context.delivery_date",
            "supplier_context.purchase_orders",
            "derived_metrics.amount",
            "existing_journals",
        ],
        "preferred_tools": ["CreateJournalEntry"],
        "is_active": True,
    },
    {
        "id": "create_cost_accrual_recurring_subscription_pattern",
        "name": "Accrue recurring subscription when prior pattern is clear and current period invoice is missing",
        "decision_type": "create_cost_accrual",
        "priority": 58,
        "confidence": 0.88,
        "requires_human_approval": False,
        "conditions": [
            {"path": "supplier_context.purchase_invoices", "operator": "exists"},
        ],
        "reason_templates": [
            "Look at supplier_context.purchase_invoices across the close window for a repeating pattern: same/similar description (subscription, license, SaaS, abonnement, …), similar amounts, cadence ~1 month (monthly) or ~3 months (quarterly). If the pattern is clear AND the current period is missing the expected invoice → create_cost_accrual for the expected VAT-exclusive amount unless existing_journals already show that accrual.",
        ],
        "evidence_paths": [
            "supplier_context.purchase_invoices",
            "existing_journals",
            "derived_metrics.current_period_key",
        ],
        "preferred_tools": ["CreateJournalEntry"],
        "is_active": True,
    },
    {
        "id": "escalate_uncertain_subscription_continuation",
        "name": "Escalate when subscription may have ended (pattern incomplete or ambiguous)",
        "decision_type": "escalate_to_finance_controller",
        "priority": 57,
        "confidence": 0.8,
        "requires_human_approval": True,
        "conditions": [
            {"path": "supplier_context.purchase_invoices", "operator": "exists"},
        ],
        "reason_templates": [
            "Possible recurring subscription, but it is unclear whether it continues into the current period (gap in history, amount changed a lot, one-off vs recurring, or end-date hints in description/YourRef). Do NOT accrue. Call notify_finance_controller explaining the uncertainty, then finalize with escalate_to_finance_controller.",
        ],
        "evidence_paths": [
            "supplier_context.purchase_invoices",
            "derived_metrics.current_period_key",
        ],
        "preferred_tools": ["NotifyFinanceController"],
        "is_active": True,
    },
    {
        "id": "create_cost_accrual_non_po_prior_period_service",
        "name": "Create non-PO accrual for prior-period service invoice",
        "decision_type": "create_cost_accrual",
        "priority": 55,
        "confidence": 0.92,
        "requires_human_approval": False,
        "conditions": [
            {"path": "po_context.purchase_order_id", "operator": "eq", "value": None},
            {"path": "purchase_invoice_context.invoice_id", "operator": "exists"},
            {
                "path": "purchase_invoice_context.service_period_start",
                "operator": "not_starts_with",
                "value": "{{derived_metrics.current_period_key}}",
            },
            {"path": "derived_metrics.amount", "operator": "gte", "value": 1},
        ],
        "reason_templates": [
            "Service invoice points to a prior period and needs a non-PO cost accrual (VAT-exclusive amount), unless existing_journals already cover it. Skip when amount is below organization_policy.materiality_threshold.",
        ],
        "evidence_paths": [
            "purchase_invoice_context.invoice_id",
            "purchase_invoice_context.service_period_start",
            "derived_metrics.current_period_key",
            "existing_journals",
        ],
        "preferred_tools": ["CreateJournalEntry"],
        "is_active": True,
    },
    {
        "id": "no_action_default",
        "name": "No action fallback",
        "decision_type": "no_action",
        "priority": 0,
        "confidence": 0.9,
        "requires_human_approval": False,
        "conditions": [],
        "reason_templates": [
            "No matching accounting policy rule required posting actions. Call record_no_action then finalize with no_action. Do not notify the finance controller.",
        ],
        "evidence_paths": ["event.event_type"],
        "preferred_tools": ["RecordNoAction"],
        "is_active": True,
    },
]


def apply_notify_flags(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach notify_finance_controller from NOTIFY_FINANCE_CONTROLLER_POLICY_IDS."""
    tagged: list[dict[str, Any]] = []
    for rule in rules:
        item = dict(rule)
        item["notify_finance_controller"] = item.get("id") in NOTIFY_FINANCE_CONTROLLER_POLICY_IDS
        tagged.append(item)
    return tagged


def get_policy_knowledge_context() -> dict[str, Any]:
    return {"source": "code", "rules": apply_notify_flags(DEFAULT_POLICY_RULES)}
