"""ERP-agnostic errors. Adapters map vendor failures onto these."""


class ErpError(RuntimeError):
    pass


class ErpClosedPeriodError(ErpError):
    pass


class ErpUnsupportedError(ErpError):
    pass
