"""Exact Online adapter (mirrors Backend supabase/functions/_shared/provider/exact)."""
from provider.exact.connection import get_organization_connection, require_connection
from provider.exact.const import (
    EXACT_API_BASE_URL,
    EXACT_CLIENT_ID,
    EXACT_CLIENT_SECRET,
    EXACT_TOKEN_URL,
)
from provider.exact.documents import ExactClient
from provider.exact.gl import (
    find_period_for_date,
    get_financial_period_for_date,
    get_gl_account_guid_by_code,
    get_gl_accounts,
    get_reporting_year_and_period,
    list_financial_periods,
)
from provider.exact.journals import (
    ExactMemorialPostError,
    is_closed_accounting_period_error,
    list_journal_entry_lines,
    post_general_journal_entry,
)
from provider.exact.odata import (
    GUID_RE,
    exact_get_json,
    exact_v1,
    is_exact_guid,
    normalize_exact_date,
    odata_entity,
    odata_results,
    with_division,
)
from provider.exact.purchasing import (
    PO_STATUS_CANCELLED,
    PO_STATUS_COMPLETE,
    get_purchase_entries,
    get_purchase_entry,
    get_purchase_order,
    get_purchase_orders,
)

__all__ = [
    "EXACT_API_BASE_URL",
    "EXACT_CLIENT_ID",
    "EXACT_CLIENT_SECRET",
    "EXACT_TOKEN_URL",
    "ExactClient",
    "ExactMemorialPostError",
    "GUID_RE",
    "PO_STATUS_CANCELLED",
    "PO_STATUS_COMPLETE",
    "exact_get_json",
    "exact_v1",
    "find_period_for_date",
    "get_financial_period_for_date",
    "get_gl_account_guid_by_code",
    "get_gl_accounts",
    "get_organization_connection",
    "get_purchase_entries",
    "get_purchase_entry",
    "get_purchase_order",
    "get_purchase_orders",
    "get_reporting_year_and_period",
    "is_closed_accounting_period_error",
    "is_exact_guid",
    "list_financial_periods",
    "list_journal_entry_lines",
    "normalize_exact_date",
    "odata_entity",
    "odata_results",
    "post_general_journal_entry",
    "require_connection",
    "with_division",
]
