"""ERP provider layer.

Same idea as Backend `supabase/functions/_shared/provider/`:
- `provider.router` is ERP-agnostic (switch on connected provider)
- `provider.exact` is the Exact Online adapter

Do not import `provider.router` here. Eager imports cause a cycle:
`provider.exact.const` → this package → router → Exact connection → r2r.config.
"""

__all__ = [
    "resolve_organization_erp_provider",
]


def __getattr__(name: str):
    if name == "resolve_organization_erp_provider":
        from provider.router import resolve_organization_erp_provider

        return resolve_organization_erp_provider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
