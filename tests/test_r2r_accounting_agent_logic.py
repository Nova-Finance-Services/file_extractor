"""Unit tests for prepaid status and journal proposal helpers."""
from r2r.accounting_agent.executor import build_journal_proposal, resolve_effective_cost_gl_account
from r2r.accounting_agent.policies import (
    DEFAULT_POLICY_RULES,
    NOTIFY_FINANCE_CONTROLLER_POLICY_IDS,
    apply_notify_flags,
)
from r2r.accounting_agent.llm_chat import messages_to_responses_input, parse_responses_output
from r2r.accounting_agent.prompts import render_notify_index, render_policies
from r2r.accounting_agent.run import is_event_within_configured_window
from r2r.accounting_agent.tools import get_agent_tools


def _base_context(**overrides):
    ctx = {
        "event": {
            "event_type": "month_end",
            "organization_id": "org-1",
            "occurred_at": "2026-09-30T12:00:00.000Z",
        },
        "accounting_period": {
            "year": 2026,
            "period": 9,
            "is_open": True,
            "currency": "EUR",
            "previous_period": {"year": 2026, "period": 8},
        },
        "organization_policy": {
            "materiality_threshold": 50,
            "requires_approval_above": 50000,
            "close_calendar_name": "standard_month_end",
            "working_day_rule": "calendar_days",
            "month_start_run_days": [1, 2, 3],
            "month_end_offset_days": [0],
            "memorial_journal_code": "90",
            "gl_accounts": {
                "cost_gl_account_code": "6000",
                "accrued_cost_gl_account_code": "2100",
                "prepaid_gl_account_code": "1600",
            },
        },
        "available_gl_accounts": [
            {"code": "6000", "description": "General expenses"},
            {"code": "6100", "description": "Software licenses"},
            {"code": "7100", "description": "Purchasing costs"},
            {"code": "2100", "description": "Accrued costs"},
            {"code": "1600", "description": "Prepaid expenses"},
        ],
        "po_context": {
            "is_delivered": False,
            "is_closed": False,
            "erp_synced": False,
            "invoice_received": False,
        },
        "purchase_invoice_context": {},
        "history": {"similar_decisions_count": 0},
        "data_quality": {"missing_fields": [], "is_complete": True},
        "derived_metrics": {
            "amount": 0,
            "invoice_months_covered": 0,
            "prepaid_monthly_release_amount": 0,
            "service_covers_current_period": False,
            "current_period_key": "2026-09",
        },
        "policy_knowledge": {"source": "code", "rules": []},
        "existing_journals": [],
    }
    ctx.update(overrides)
    return ctx


def test_map_purchase_invoice_keeps_description_text():
    from provider.exact.close import map_purchase_invoice

    mapped = map_purchase_invoice({
        "EntryID": "527836fb-7f90-4554-80d2-ed9045b1806f",
        "EntryDate": "2026-08-03T00:00:00",
        "Description": "Consulting retainer 2026-08-01 to 2026-10-31",
        "YourRef": "inv 26600033",
        "AmountFC": 7260,
        "Currency": "EUR",
    })
    assert mapped["description"] == "Consulting retainer 2026-08-01 to 2026-10-31"
    assert mapped["your_ref"] == "inv 26600033"
    assert mapped["amount"] == 7260
    assert mapped["provider_purchase_invoice_id"] == "527836fb-7f90-4554-80d2-ed9045b1806f"
    assert "service_period_start" not in mapped
    assert "service_period_end" not in mapped


def test_agent_tools_omit_prepaid_status():
    names = [t['function']['name'] for t in get_agent_tools()]
    assert 'get_prepaid_status' not in names
    assert 'release_prepaid_asset' in names
    release = next(t for t in get_agent_tools() if t['function']['name'] == 'release_prepaid_asset')
    assert 'get_prepaid_status' not in release['function']['description']


def test_notify_extracts_pinv_id_from_message():
    from r2r.accounting_agent.tools import create_initial_state, execute_agent_tool

    pinv_id = "527836fb-7f90-4554-80d2-ed9045b1806f"
    ctx = _base_context(
        supplier_context={"provider_supplier_id": "c6aec698-d5bf-4d21-b9ad-47882ca68443"},
        purchase_invoice_context={},
    )
    state = create_initial_state()
    execute_agent_tool(
        "notify_finance_controller",
        {
            "message": (
                f"Blocked October prepaid review for PINV {pinv_id} (invoice 26600033): "
                "no prepaid setup was found."
            ),
        },
        ctx,
        {"notifyFinanceController": lambda *_args, **_kwargs: None},
        state,
    )
    note = state["financeControllerNotifications"][0]
    assert note["provider_purchase_invoice_id"] == pinv_id
    assert note["kind"] == "notify"


def test_journal_proposal_default_and_override():
    ctx = _base_context(
        event={
            "event_type": "month_end",
            "organization_id": "org-1",
            "occurred_at": "2026-07-31T12:00:00.000Z",
            "payload": {"provider_purchase_order_id": "erp-po-1"},
        },
        po_context={
            "provider_purchase_order_id": "erp-po-1",
            "is_delivered": True,
            "is_closed": False,
            "erp_synced": True,
            "invoice_received": False,
            "amount": 2000,
        },
        derived_metrics={
            "amount": 2000,
            "invoice_months_covered": 0,
            "prepaid_monthly_release_amount": 0,
            "service_covers_current_period": False,
            "current_period_key": "2026-07",
        },
    )
    proposal = build_journal_proposal(ctx, "create_cost_accrual")
    assert proposal["debit_account"] == "6000"
    assert proposal["credit_account"] == "2100"

    accrual = build_journal_proposal(ctx, "create_cost_accrual", {"cost_gl_account_code": "6100"})
    assert accrual["debit_account"] == "6100"
    assert accrual["credit_account"] == "2100"

    invalid = build_journal_proposal(ctx, "create_cost_accrual", {"cost_gl_account_code": "9999"})
    assert invalid["debit_account"] == "6000"
    resolved = resolve_effective_cost_gl_account(ctx, {"cost_gl_account_code": "9999"})
    assert resolved["costCode"] == "6000"
    assert resolved["rejectedOverride"] == "9999"


def test_journal_proposal_prefers_document_gl():
    ctx = _base_context(
        event={
            "event_type": "month_end",
            "organization_id": "org-1",
            "occurred_at": "2026-07-31T12:00:00.000Z",
        },
        po_context={
            "provider_purchase_order_id": "erp-po-1",
            "is_delivered": True,
            "is_closed": False,
            "erp_synced": True,
            "invoice_received": False,
            "amount": 2000,
            "gl_account_code": "7100",
        },
        derived_metrics={
            "amount": 2000,
            "invoice_months_covered": 0,
            "prepaid_monthly_release_amount": 0,
            "service_covers_current_period": False,
            "current_period_key": "2026-07",
        },
    )
    proposal = build_journal_proposal(ctx, "create_cost_accrual", {"cost_gl_account_code": "6100"})
    assert proposal["debit_account"] == "7100"


def test_pick_pinv_gl_from_entry_lines():
    from provider.exact.close import pick_pinv_gl_account_code

    code = pick_pinv_gl_account_code({
        "PurchaseEntryLines": {
            "results": [
                {"GLAccountCode": "5520", "AmountFC": 100},
                {"GLAccountCode": "7100", "AmountFC": 900},
            ],
        },
    })
    assert code == "7100"


def test_run_window():
    policy = {"month_start_run_days": [1, 2, 3], "month_end_offset_days": [0]}
    assert is_event_within_configured_window(
        {"event_type": "month_end", "occurred_at": "2026-07-31T12:00:00.000Z"},
        policy,
    )
    assert not is_event_within_configured_window(
        {"event_type": "month_end", "occurred_at": "2026-07-30T12:00:00.000Z"},
        policy,
    )
    assert is_event_within_configured_window(
        {"event_type": "month_start", "occurred_at": "2026-08-01T12:00:00.000Z"},
        policy,
    )


def test_notify_finance_controller_policy_ids():
    ids = {rule["id"] for rule in DEFAULT_POLICY_RULES}
    assert NOTIFY_FINANCE_CONTROLLER_POLICY_IDS <= ids

    tagged = apply_notify_flags(DEFAULT_POLICY_RULES)
    by_id = {rule["id"]: rule for rule in tagged}
    assert by_id["standing_over_threshold_notify_finance"]["notify_finance_controller"] is True
    assert by_id["standing_read_existing_journals"]["notify_finance_controller"] is False
    assert by_id["create_cost_accrual_po_delivered_not_invoiced"]["notify_finance_controller"] is False
    assert by_id["standing_prefer_no_action"]["notify_finance_controller"] is False

    index = render_notify_index(tagged)
    assert "standing_over_threshold_notify_finance" in index
    assert "standing_read_existing_journals" not in index
    assert "NOTIFY:" in index

    rendered = render_policies(tagged)
    assert "[notify=yes]" in rendered
    assert "[notify=no]" in rendered
    assert "get_prepaid_status" not in rendered
    assert "That history is the source of truth" in rendered
    assert "Do not notify because a parsed date field is missing" in rendered


def test_messages_to_responses_input_roundtrip():
    instructions, items = messages_to_responses_input([
        {"role": "system", "content": "You are the agent."},
        {"role": "user", "content": "Close this supplier."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "release_prepaid_asset", "arguments": "{\"reason\":\"release September\"}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "OK: released"},
    ])
    assert instructions == "You are the agent."
    assert items[0] == {"role": "user", "content": "Close this supplier."}
    assert items[1]["type"] == "function_call"
    assert items[1]["call_id"] == "call_1"
    assert items[1]["name"] == "release_prepaid_asset"
    assert items[2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "OK: released",
    }


def test_parse_responses_output_function_call():
    parsed = parse_responses_output({
        "output_text": "",
        "output": [
            {
                "type": "function_call",
                "call_id": "call_abc",
                "name": "finalize",
                "arguments": {"decision_type": "no_action", "confidence": 0.9},
            }
        ],
    })
    assert parsed["toolCalls"] == [{
        "id": "call_abc",
        "name": "finalize",
        "arguments": '{"decision_type": "no_action", "confidence": 0.9}',
    }]
    assert parsed["content"] is None


def test_verify_execution_rejects_same_gl_prepaid_release():
    from r2r.accounting_agent.review import verify_execution

    context = {
        "accounting_period": {"is_open": True},
    }
    execution = {
        "success": True,
        "provider_entry_id": "entry-1",
        "journal_proposal": {
            "debit_account": "2302",
            "credit_account": "2302",
            "amount": 2420,
        },
    }
    result = verify_execution(context, {"decision_type": "release_prepaid_asset"}, execution)
    assert result["success"] is False
    assert any(c["check"] == "Debit and credit accounts differ" and not c["passed"] for c in result["checks"])


def test_verify_execution_accepts_expense_vs_prepaid_gl():
    from r2r.accounting_agent.review import verify_execution

    result = verify_execution(
        {"accounting_period": {"is_open": True}},
        {"decision_type": "release_prepaid_asset"},
        {
            "success": True,
            "provider_entry_id": "entry-1",
            "journal_proposal": {"debit_account": "7000", "credit_account": "2302"},
        },
    )
    assert result["success"] is True


def _batch_context():
    return _base_context(
        derived_metrics={"current_period_key": "2026-10", "po_count": 2, "pinv_count": 2},
        supplier_context={
            "provider_supplier_id": "sup-1",
            "supplier_name": "Acme",
            "purchase_orders": [
                {
                    "provider_purchase_order_id": "po-1",
                    "amount": 4000,
                    "is_delivered": True,
                    "invoice_received": False,
                },
                {
                    "provider_purchase_order_id": "po-2",
                    "amount": 6000,
                    "is_delivered": True,
                    "invoice_received": False,
                },
            ],
            "purchase_invoices": [
                {
                    "provider_purchase_invoice_id": "pinv-1",
                    "amount": 1000,
                    "currency": "EUR",
                    "description": "Aug retainer",
                },
                {
                    "provider_purchase_invoice_id": "pinv-2",
                    "amount": 3000,
                    "currency": "EUR",
                    "description": "Sep retainer",
                },
            ],
        },
    )


def test_batch_amount_is_document_specific():
    from r2r.accounting_agent.executor import resolve_posting_amount

    ctx = _batch_context()
    assert "amount" not in ctx["derived_metrics"]
    assert resolve_posting_amount(ctx, "create_prepaid_asset", {
        "provider_purchase_invoice_id": "pinv-2",
    }) == 3000
    assert resolve_posting_amount(ctx, "create_cost_accrual", {
        "provider_purchase_order_id": "po-2",
    }) == 6000
    assert resolve_posting_amount(ctx, "release_prepaid_asset", {
        "provider_purchase_invoice_id": "pinv-2",
    }) == 0
    assert resolve_posting_amount(ctx, "create_prepaid_asset", {}) == 0

    proposal = build_journal_proposal(ctx, "create_prepaid_asset", {
        "amount": 3000,
        "provider_purchase_invoice_id": "pinv-2",
        "reason": "setup PINV 2",
    })
    assert proposal["amount"] == 3000
    assert proposal["metadata"]["provider_purchase_invoice_id"] == "pinv-2"


def test_threshold_uses_document_amount_not_batch_total():
    from r2r.accounting_agent.executor import create_default_business_tools
    from r2r.accounting_agent.tools import create_initial_state, execute_agent_tool

    ctx = _batch_context()
    ctx["organization_policy"]["requires_approval_above"] = 5000
    tools = create_default_business_tools(ctx, dry_run=True)
    state = create_initial_state()
    result = execute_agent_tool(
        "create_prepaid_asset",
        {
            "amount": 3000,
            "provider_purchase_invoice_id": "pinv-2",
            "reason": "setup PINV 2 only",
            "description": "inv 2 | service 2026-09-01 to 2026-09-30",
        },
        ctx,
        tools,
        state,
    )
    assert result["content"].startswith("OK:")
    assert state["postedJournals"][0]["journal_proposal"]["amount"] == 3000


def test_invalid_gl_override_does_not_notify():
    from r2r.accounting_agent.executor import create_default_business_tools
    from r2r.accounting_agent.tools import create_initial_state, execute_agent_tool

    ctx = _base_context(
        po_context={
            "provider_purchase_order_id": "erp-po-1",
            "is_delivered": True,
            "invoice_received": False,
            "amount": 2000,
        },
    )
    tools = create_default_business_tools(ctx, dry_run=True)
    state = create_initial_state()
    execute_agent_tool(
        "create_cost_accrual",
        {"reason": "accrue PO", "amount": 2000, "cost_gl_account_code": "9999"},
        ctx,
        tools,
        state,
    )
    assert state["financeControllerNotifications"] == []
    assert any("Ignored invalid cost_gl_account_code 9999" in line for line in state["actionLog"])
    assert state["postedJournals"][0]["journal_proposal"]["debit_account"] == "6000"


def test_infer_prepaid_release_from_reverse_prepaid_journal():
    from r2r.accounting_agent.loop import _infer_decision_type

    assert _infer_decision_type({
        "toolSequence": [{"tool": "ReversePrepaidJournal", "action": "Release prepaid asset"}],
    }) == "release_prepaid_asset"


def test_max_agent_iterations_allows_multi_document_walk():
    from r2r.accounting_agent.constants import MAX_AGENT_ITERATIONS

    assert MAX_AGENT_ITERATIONS >= 16


def test_supplier_close_context_stays_document_neutral():
    from unittest.mock import patch
    from r2r.accounting_agent.discovery import build_supplier_close_context

    batch = {
        "provider_supplier_id": "sup-1",
        "supplier_name": "Acme",
        "purchase_orders": [
            {"provider_purchase_order_id": "po-1", "amount": 4000, "is_delivered": True},
            {"provider_purchase_order_id": "po-2", "amount": 6000, "is_delivered": True},
        ],
        "purchase_invoices": [
            {"provider_purchase_invoice_id": "pinv-1", "amount": 1000},
            {"provider_purchase_invoice_id": "pinv-2", "amount": 3000},
        ],
    }
    with patch("r2r.accounting_agent.discovery.get_accounting_period_context", return_value={
        "year": 2026, "period": 10, "is_open": True, "currency": "EUR",
    }), patch("r2r.accounting_agent.discovery.get_organization_context", return_value={
        "gl_accounts": {
            "cost_gl_account_code": "6000",
            "accrued_cost_gl_account_code": "2100",
            "prepaid_gl_account_code": "1600",
        },
    }), patch("r2r.accounting_agent.discovery.get_historical_context", return_value={}), patch(
        "r2r.accounting_agent.discovery.load_available_gl_accounts_for_agent", return_value=[],
    ), patch(
        "r2r.accounting_agent.discovery.load_existing_journals_for_supplier", return_value=[],
    ), patch(
        "r2r.accounting_agent.discovery.load_nova_po_gl_account_codes", return_value={},
    ):
        ctx = build_supplier_close_context(
            {
                "organization_id": "org-1",
                "event_type": "month_end",
                "occurred_at": "2026-10-31T12:00:00.000Z",
            },
            batch,
            {"start_date": "2026-08-01", "end_date": "2026-10-31"},
        )

    assert ctx["po_context"].get("provider_purchase_order_id") is None
    assert ctx["purchase_invoice_context"] == {}
    assert "amount" not in ctx["derived_metrics"]
    assert ctx["derived_metrics"]["current_period_key"] == "2026-10"
    assert len(ctx["supplier_context"]["purchase_orders"]) == 2
    assert len(ctx["supplier_context"]["purchase_invoices"]) == 2
    assert ctx["supplier_context"]["purchase_invoices"][1]["amount"] == 3000


def test_two_posts_are_kept_on_execution_state():
    from r2r.accounting_agent.executor import create_default_business_tools
    from r2r.accounting_agent.tools import create_initial_state, execute_agent_tool

    ctx = _batch_context()
    tools = create_default_business_tools(ctx, dry_run=True)
    state = create_initial_state()
    execute_agent_tool(
        "release_prepaid_asset",
        {
            "amount": 1000,
            "provider_purchase_invoice_id": "pinv-1",
            "reason": "release PINV 1",
            "description": "inv 1 | service 2026-08-01 to 2026-10-31",
        },
        ctx,
        tools,
        state,
    )
    execute_agent_tool(
        "release_prepaid_asset",
        {
            "amount": 2000,
            "provider_purchase_invoice_id": "pinv-2",
            "reason": "release PINV 2",
            "description": "inv 2 | service 2026-08-01 to 2026-10-31",
        },
        ctx,
        tools,
        state,
    )
    assert len(state["postedJournals"]) == 2
    assert state["postedJournals"][0]["journal_proposal"]["amount"] == 1000
    assert state["postedJournals"][1]["journal_proposal"]["amount"] == 2000
    assert state["lastProposal"]["amount"] == 2000

