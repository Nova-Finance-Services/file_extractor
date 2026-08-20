"""Journal proposal builder and ERP tool wrappers."""
from __future__ import annotations

from typing import Any, Callable, Optional

from r2r.accounting_agent.gl_codes import is_allowed_cost_gl_account_code
from r2r.accounting_agent.post_journal import post_journal_proposal_to_erp


def resolve_effective_cost_gl_account(
    context: dict[str, Any],
    opts: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    opts = opts or {}
    default_cost = context["organization_policy"]["gl_accounts"]["cost_gl_account_code"]
    available = context.get("available_gl_accounts")
    document_code = (opts.get("document_gl_account_code") or "").strip()
    if document_code and is_allowed_cost_gl_account_code(document_code, available, default_cost):
        return {"costCode": document_code, "source": "document"}
    tool_code = (opts.get("cost_gl_account_code") or "").strip()
    if not tool_code:
        return {"costCode": default_cost, "source": "default"}
    if is_allowed_cost_gl_account_code(tool_code, available, default_cost):
        return {"costCode": tool_code, "source": "tool"}
    return {"costCode": default_cost, "rejectedOverride": tool_code, "source": "default"}


def _supplier_docs(context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supplier = context.get("supplier_context") or {}
    orders = [row for row in (supplier.get("purchase_orders") or []) if isinstance(row, dict)]
    invoices = [row for row in (supplier.get("purchase_invoices") or []) if isinstance(row, dict)]
    return orders, invoices


def _find_po(context: dict[str, Any], po_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not po_id:
        return None
    orders, _ = _supplier_docs(context)
    found = next((row for row in orders if row.get("provider_purchase_order_id") == po_id), None)
    if found:
        return found
    po = context.get("po_context") or {}
    if po.get("provider_purchase_order_id") == po_id:
        return po
    return None


def _find_pinv(context: dict[str, Any], pinv_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not pinv_id:
        return None
    _, invoices = _supplier_docs(context)
    found = next((row for row in invoices if row.get("provider_purchase_invoice_id") == pinv_id), None)
    if found:
        return found
    pinv = context.get("purchase_invoice_context") or {}
    if pinv.get("provider_purchase_invoice_id") == pinv_id:
        return pinv
    return None


def _abs_amount(value: Any) -> float:
    try:
        return abs(float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def resolve_posting_amount(
    context: dict[str, Any],
    decision_type: str,
    opts: Optional[dict[str, Any]] = None,
) -> float:
    """Amount for THIS posting only. Never a supplier-batch total."""
    opts = opts or {}
    explicit = opts.get("amount")
    if isinstance(explicit, (int, float)):
        return abs(float(explicit))

    if decision_type == "release_prepaid_asset":
        return 0.0

    po = _find_po(context, opts.get("provider_purchase_order_id") if isinstance(opts.get("provider_purchase_order_id"), str) else None)
    pinv = _find_pinv(
        context,
        opts.get("provider_purchase_invoice_id") if isinstance(opts.get("provider_purchase_invoice_id"), str) else None,
    )
    if decision_type in {"create_cost_accrual", "release_existing_accrual"} and po:
        return _abs_amount(po.get("amount"))
    if decision_type == "create_prepaid_asset" and pinv:
        return _abs_amount(pinv.get("amount"))
    if po:
        return _abs_amount(po.get("amount"))
    if pinv:
        return _abs_amount(pinv.get("amount"))

    orders, invoices = _supplier_docs(context)
    if len(orders) + len(invoices) > 1:
        return 0.0

    if decision_type in {"create_cost_accrual", "release_existing_accrual"}:
        if len(orders) == 1:
            return _abs_amount(orders[0].get("amount"))
        return _abs_amount((context.get("po_context") or {}).get("amount"))
    if decision_type == "create_prepaid_asset":
        if len(invoices) == 1:
            return _abs_amount(invoices[0].get("amount"))
        return _abs_amount((context.get("purchase_invoice_context") or {}).get("amount"))
    return _abs_amount(
        (context.get("po_context") or {}).get("amount")
        or (context.get("purchase_invoice_context") or {}).get("amount")
    )


def document_cost_gl_for_decision(
    context: dict[str, Any],
    decision_type: str,
    opts: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    opts = opts or {}
    supplier = context.get("supplier_context")
    is_po = decision_type in {"create_cost_accrual", "release_existing_accrual"}
    is_pinv = decision_type in {"create_prepaid_asset", "release_prepaid_asset"}
    if is_po:
        po_id = opts.get("provider_purchase_order_id") or context["po_context"].get("provider_purchase_order_id")
        if po_id and supplier:
            po = next(
                (p for p in supplier.get("purchase_orders") or [] if p.get("provider_purchase_order_id") == po_id),
                None,
            )
            if po and (po.get("gl_account_code") or "").strip():
                return po["gl_account_code"].strip()
        code = (context["po_context"].get("gl_account_code") or "").strip()
        return code or None
    if is_pinv:
        pinv_id = opts.get("provider_purchase_invoice_id") or context["purchase_invoice_context"].get(
            "provider_purchase_invoice_id"
        )
        if pinv_id and supplier:
            pinv = next(
                (
                    p
                    for p in supplier.get("purchase_invoices") or []
                    if p.get("provider_purchase_invoice_id") == pinv_id
                ),
                None,
            )
            if pinv and (pinv.get("gl_account_code") or "").strip():
                return pinv["gl_account_code"].strip()
        code = (context["purchase_invoice_context"].get("gl_account_code") or "").strip()
        return code or None
    return None


def build_journal_proposal(
    context: dict[str, Any],
    decision_type: str,
    opts: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    opts = opts or {}
    supplier = context.get("supplier_context")
    po_from_supplier = None
    if opts.get("provider_purchase_order_id") and supplier:
        po_from_supplier = next(
            (
                p
                for p in supplier.get("purchase_orders") or []
                if p.get("provider_purchase_order_id") == opts["provider_purchase_order_id"]
            ),
            None,
        )
    pinv_from_supplier = None
    if opts.get("provider_purchase_invoice_id") and supplier:
        pinv_from_supplier = next(
            (
                p
                for p in supplier.get("purchase_invoices") or []
                if p.get("provider_purchase_invoice_id") == opts["provider_purchase_invoice_id"]
            ),
            None,
        )

    amount = resolve_posting_amount(context, decision_type, opts)

    period = context["derived_metrics"]["current_period_key"]
    gl = context["organization_policy"]["gl_accounts"]
    cost_code = resolve_effective_cost_gl_account(
        context,
        {
            "cost_gl_account_code": opts.get("cost_gl_account_code"),
            "document_gl_account_code": document_cost_gl_for_decision(context, decision_type, opts),
        },
    )["costCode"]

    account_map = {
        "create_cost_accrual": {
            "debit_account": cost_code,
            "credit_account": gl["accrued_cost_gl_account_code"],
            "description": f"Cost accrual {period}",
        },
        "release_existing_accrual": {
            "debit_account": gl["accrued_cost_gl_account_code"],
            "credit_account": cost_code,
            "description": f"Accrual release {period}",
        },
        "create_prepaid_asset": {
            "debit_account": gl["prepaid_gl_account_code"],
            "credit_account": cost_code,
            "description": f"Prepaid setup {period}",
        },
        "release_prepaid_asset": {
            "debit_account": cost_code,
            "credit_account": gl["prepaid_gl_account_code"],
            "description": f"Prepaid release {period}",
        },
    }
    selected = account_map.get(decision_type) or {
        "debit_account": cost_code,
        "credit_account": gl["accrued_cost_gl_account_code"],
        "description": f"Accounting entry {period}",
    }

    provider_po_id = opts.get("provider_purchase_order_id") or context["po_context"].get("provider_purchase_order_id")
    provider_pinv_id = opts.get("provider_purchase_invoice_id") or context["purchase_invoice_context"].get(
        "provider_purchase_invoice_id"
    )

    po_label = None
    if po_from_supplier:
        bits = []
        if po_from_supplier.get("order_number") is not None:
            bits.append(f"PO {po_from_supplier['order_number']}")
        else:
            bits.append("PO")
        if (po_from_supplier.get("description") or "").strip():
            bits.append(po_from_supplier["description"].strip())
        po_label = " ".join(bits)
    elif provider_po_id and context["po_context"].get("provider_purchase_order_id") == provider_po_id:
        po_label = f"PO {context['po_context']['order_number']}" if context["po_context"].get("order_number") is not None else "PO"
    elif provider_po_id:
        po_label = f"PO {provider_po_id}"

    pinv_label = None
    if pinv_from_supplier:
        bits = []
        if pinv_from_supplier.get("entry_number") is not None:
            bits.append(f"PINV {pinv_from_supplier['entry_number']}")
        else:
            bits.append("PINV")
        if (pinv_from_supplier.get("description") or "").strip():
            bits.append(pinv_from_supplier["description"].strip())
        pinv_label = " ".join(bits)
    elif provider_pinv_id and context["purchase_invoice_context"].get("provider_purchase_invoice_id") == provider_pinv_id:
        desc = (context["purchase_invoice_context"].get("description") or "").strip()
        pinv_label = " ".join([p for p in ["PINV", desc] if p])
    elif provider_pinv_id:
        pinv_label = f"PINV {provider_pinv_id}"

    user_desc = (opts.get("description") or "").strip()
    action_desc = selected["description"]
    if user_desc:
        if action_desc.lower() not in user_desc.lower():
            user_desc = f"{action_desc} | {user_desc}"
    else:
        user_desc = action_desc
    linked = " | ".join(
        p
        for p in [
            user_desc,
            po_label,
            f"po:{provider_po_id}" if provider_po_id else None,
            pinv_label,
            f"pinv:{provider_pinv_id}" if provider_pinv_id else None,
        ]
        if p
    )[:240]

    return {
        "description": linked,
        "amount": amount,
        "currency": (pinv_from_supplier or {}).get("currency")
        or (po_from_supplier or {}).get("currency")
        or context["purchase_invoice_context"].get("currency")
        or context["accounting_period"].get("currency")
        or "EUR",
        "debit_account": selected["debit_account"],
        "credit_account": selected["credit_account"],
        "posting_date": context["event"]["occurred_at"][:10],
        "metadata": {
            "event_type": context["event"]["event_type"],
            "provider_supplier_id": (context.get("supplier_context") or {}).get("provider_supplier_id"),
            "supplier_name": (context.get("supplier_context") or {}).get("supplier_name"),
            "purchase_order_id": context["po_context"].get("purchase_order_id"),
            "provider_purchase_order_id": provider_po_id,
            "purchase_invoice_id": context["purchase_invoice_context"].get("invoice_id"),
            "provider_purchase_invoice_id": provider_pinv_id,
            "period_key": context["derived_metrics"]["current_period_key"],
        },
    }


def _post_proposal(context: dict[str, Any], proposal: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {
            "provider_entry_id": "dry-run-entry",
            "entry_number": None,
            "journal_proposal": proposal,
        }
    posted = post_journal_proposal_to_erp(context, proposal)
    return {
        "provider_entry_id": posted["provider_entry_id"],
        "entry_number": posted["entry_number"],
        "journal_proposal": proposal,
    }


def create_default_business_tools(context: dict[str, Any], dry_run: bool) -> dict[str, Callable]:
    def post(proposal: dict[str, Any]) -> dict[str, Any]:
        return _post_proposal(context, proposal, dry_run)

    return {
        "createJournalEntry": post,
        "reverseJournalEntry": post,
        "createPrepaidJournal": post,
        "notifyFinanceController": lambda _message, _extra: None,
    }


def build_execution_result_from_state(args: dict[str, Any]) -> dict[str, Any]:
    context = args["context"]
    action_log = args.get("actionLog") or []
    posted = [row for row in (args.get("postedJournals") or []) if isinstance(row, dict)]
    last = posted[-1] if posted else None
    last_proposal = (last or {}).get("journal_proposal") or args.get("lastProposal")
    return {
        "success": args.get("success") if args.get("success") is not None else not args.get("error"),
        "provider_entry_id": (last or {}).get("provider_entry_id") or args.get("providerEntryId"),
        "entry_number": (last or {}).get("entry_number") if last else args.get("entryNumber"),
        "journal_proposal": last_proposal,
        "journal_proposals": [row.get("journal_proposal") for row in posted if row.get("journal_proposal")],
        "posted_journals": posted,
        "tool_timeline": args.get("toolTimeline") or [],
        "action_log": action_log if action_log else ["No tool actions were taken."],
        "finance_controller_notifications": args.get("financeControllerNotifications") or [],
        "period_key": context["derived_metrics"]["current_period_key"],
        "context_po_id": context["po_context"].get("provider_purchase_order_id"),
        "context_supplier_id": (context.get("supplier_context") or {}).get("provider_supplier_id"),
        "error": args.get("error"),
    }
