from __future__ import annotations

from qdata.sources.providers.akshare_provider import AkShareProvider
from qdata.sources.providers.baostock_provider import BaoStockProvider
from qdata.sources.providers.csv_provider import CsvProvider
from qdata.sources.providers.official_public_provider import OfficialPublicProvider
from qdata.sources.providers.tushare_provider import TushareFreeProvider
from qdata.sources.providers.vendor_http_provider import VendorHttpProvider


def create_provider(provider: str, **kwargs):
    if provider == "csv":
        return CsvProvider(**kwargs)
    if provider == "csv_mirror":
        kwargs.setdefault("provider_name", "csv_mirror")
        return CsvProvider(**kwargs)
    if provider == "akshare":
        return AkShareProvider(**kwargs)
    if provider == "baostock":
        return BaoStockProvider(**kwargs)
    if provider == "tushare_free":
        return TushareFreeProvider(**kwargs)
    if provider in {"cninfo_public", "sse_public", "szse_public", "nbs_public"}:
        kwargs.setdefault("source_code", provider)
        return OfficialPublicProvider(**kwargs)
    if provider in {"vendor_http", "commercial_http"}:
        kwargs.setdefault("source_code", provider)
        return VendorHttpProvider(**kwargs)
    raise ValueError(f"Unsupported provider: {provider}")
