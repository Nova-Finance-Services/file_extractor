"""Unit tests for prepaid status and journal proposal helpers."""
from r2r.accounting_agent.executor import build_journal_proposal, resolve_effective_cost_gl_account
from r2r.accounting_agent.gl_codes import pick_primary_gl_account_code_from_entry_lines
from r2r.accounting_agent.prepaid_status import get_prepaid_status, parse_prepaid_desc_meta
from r2r.accounting_agent.run import is_event_within_configured_window


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


def test_parse_prepaid_desc_meta():
    parsed = parse_prepaid_desc_meta(
        "Prepaid release 2026-09 | inv 12345 | service 2026-08-01 to 2026-10-31 | pinv:abc",
    )
    assert parsed["entry_number"] == 12345
    assert parsed["service_period_start"] == "2026-08-01"
    assert parsed["service_period_end"] == "2026-10-31"


def test_prepaid_status_suggests_monthly_release():
    pinv_id = "pinv-guid-1"
    ctx = _base_context(
        existing_journals=[
            {
                "id": "1",
                "date": "2026-07-31",
                "amount_dc": 3000,
                "role": "prepaid",
                "description": f"Prepaid setup 2026-07 | inv 99 | service 2026-08-01 to 2026-10-31 | pinv:{pinv_id}",
            },
            {
                "id": "2",
                "date": "2026-08-31",
                "amount_dc": -1000,
                "role": "prepaid",
                "description": f"Prepaid release 2026-08 | inv 99 | service 2026-08-01 to 2026-10-31 | pinv:{pinv_id}",
            },
        ],
    )
    status = get_prepaid_status(ctx, pinv_id)
    assert status["setup_amount"] == 3000
    assert status["released_to_date"] == 1000
    assert status["remaining"] == 2000
    assert status["suggested_release"] == 1000
    assert status["can_release"] is True
    assert status["inv_number"] == 99
    assert status["released_this_period"] is False


def test_prepaid_status_true_up_last_month():
    pinv_id = "pinv-guid-2"
    ctx = _base_context(
        event={
            "event_type": "month_end",
            "organization_id": "org-1",
            "occurred_at": "2026-10-31T12:00:00.000Z",
        },
        accounting_period={
            "year": 2026,
            "period": 10,
            "is_open": True,
            "currency": "EUR",
            "previous_period": {"year": 2026, "period": 9},
        },
        derived_metrics={
            "amount": 0,
            "invoice_months_covered": 0,
            "prepaid_monthly_release_amount": 0,
            "service_covers_current_period": False,
            "current_period_key": "2026-10",
        },
        existing_journals=[
            {
                "id": "1",
                "date": "2026-07-31",
                "amount_dc": 3000,
                "role": "prepaid",
                "description": f"Prepaid setup 2026-07 | inv 99 | service 2026-08-01 to 2026-10-31 | pinv:{pinv_id}",
            },
            {
                "id": "2",
                "date": "2026-08-31",
                "amount_dc": -1000,
                "role": "prepaid",
                "description": f"Prepaid release 2026-08 | inv 99 | service 2026-08-01 to 2026-10-31 | pinv:{pinv_id}",
            },
            {
                "id": "3",
                "date": "2026-09-30",
                "amount_dc": -1000,
                "role": "prepaid",
                "description": f"Prepaid release 2026-09 | inv 99 | service 2026-08-01 to 2026-10-31 | pinv:{pinv_id}",
            },
        ],
    )
    status = get_prepaid_status(ctx, pinv_id)
    assert status["remaining"] == 1000
    assert status["is_last_service_month"] is True
    assert status["suggested_release"] == 1000
    assert status["can_release"] is True
    assert "last_service_month_true_up" in status["flags"]


def test_prepaid_status_blocks_unclear_dates():
    pinv_id = "pinv-guid-3"
    ctx = _base_context(
        existing_journals=[
            {
                "id": "1",
                "date": "2026-07-31",
                "amount_dc": 3000,
                "role": "prepaid",
                "description": f"Prepaid setup 2026-07 | pinv:{pinv_id}",
            },
        ],
    )
    status = get_prepaid_status(ctx, pinv_id)
    assert status["setup_amount"] == 3000
    assert status["can_release"] is False
    assert "service_dates_missing_or_unclear" in status["flags"]


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


def test_pick_primary_gl_from_entry_lines():
    code = pick_primary_gl_account_code_from_entry_lines({
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
