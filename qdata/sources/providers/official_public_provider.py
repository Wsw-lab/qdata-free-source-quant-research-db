from __future__ import annotations

from qdata.exceptions import QDataValidationError


class OfficialPublicProvider:
    """Scaffold for official public web sources.

    Exchange, CNINFO, and NBS public pages need dataset-specific endpoint,
    licensing, and cache contracts before they can be promoted to live adapters.
    The scaffold keeps Iota-5 source evaluation explicit instead of surfacing a
    generic registry "provider not implemented" error.
    """

    def __init__(self, source_code: str) -> None:
        self.source_code = source_code

    def fetch_daily_market(self, trade_date: str, symbols: list[str] | None = None):
        raise QDataValidationError(f"official_public_adapter_scaffold_only:{self.source_code}:market_dataset_contract_required")

    def list_symbols(self, trade_date: str | None = None) -> list[str]:
        raise QDataValidationError(f"official_public_adapter_scaffold_only:{self.source_code}:security_master_contract_required")

    def is_trade_date(self, trade_date: str) -> bool:
        raise QDataValidationError(f"official_public_adapter_scaffold_only:{self.source_code}:trading_calendar_contract_required")
