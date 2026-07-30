from __future__ import annotations

from qdata.exceptions import QDataValidationError
from qdata.sources.registry import create_provider


def list_provider_symbols(
    provider_name: str,
    trade_date: str,
    provider_kwargs: dict | None = None,
    max_symbols: int | None = None,
) -> list[str]:
    provider = create_provider(provider_name, **(provider_kwargs or {}))
    list_symbols = getattr(provider, "list_symbols", None)
    if list_symbols is None:
        raise QDataValidationError(f"provider {provider_name} does not support full-market symbol discovery")
    symbols = [symbol.strip().upper() for symbol in list_symbols(trade_date) if symbol.strip()]
    unique_symbols = list(dict.fromkeys(symbols))
    return unique_symbols[:max_symbols] if max_symbols else unique_symbols


def is_provider_trade_date(
    provider_name: str,
    trade_date: str,
    provider_kwargs: dict | None = None,
) -> bool:
    provider = create_provider(provider_name, **(provider_kwargs or {}))
    is_trade_date = getattr(provider, "is_trade_date", None)
    if is_trade_date is None:
        return True
    return bool(is_trade_date(trade_date))
