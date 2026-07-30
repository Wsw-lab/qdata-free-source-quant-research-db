from __future__ import annotations

import csv
from pathlib import Path

from qdata.sources.models import DailyMarketBundle, MarketConstraintBundle, MinuteMarketBundle


def export_daily_market_bundle(
    bundle: DailyMarketBundle,
    raw_root: str | Path = "raw",
) -> dict[str, str]:
    base = Path(raw_root) / "vendor" / bundle.provider / "daily_market" / f"trade_date={bundle.trade_date}"
    base.mkdir(parents=True, exist_ok=True)
    paths = {
        "security_master": base / "security_master.csv",
        "trading_calendar": base / "trading_calendar.csv",
        "daily_bar": base / "daily_bar.csv",
    }
    _write_security_master(paths["security_master"], bundle)
    _write_trading_calendar(paths["trading_calendar"], bundle)
    _write_daily_bar(paths["daily_bar"], bundle)
    return {key: str(value) for key, value in paths.items()}


def export_market_constraint_bundle(
    bundle: MarketConstraintBundle,
    raw_root: str | Path = "raw",
) -> dict[str, str]:
    base = Path(raw_root) / "vendor" / bundle.provider / "market_constraints" / f"trade_date={bundle.trade_date}"
    base.mkdir(parents=True, exist_ok=True)
    paths = {
        "security_master": base / "security_master.csv",
        "adjustment_factor": base / "adjustment_factor.csv",
        "limit_price_daily": base / "limit_price_daily.csv",
        "suspension_history": base / "suspension_history.csv",
    }
    _write_security_master(paths["security_master"], bundle)
    _write_adjustment_factor(paths["adjustment_factor"], bundle)
    _write_limit_price(paths["limit_price_daily"], bundle)
    _write_suspension(paths["suspension_history"], bundle)
    return {key: str(value) for key, value in paths.items()}


def export_minute_market_bundle(
    bundle: MinuteMarketBundle,
    raw_root: str | Path = "raw",
) -> dict[str, str]:
    base = Path(raw_root) / "vendor" / bundle.provider / "minute_market" / f"trade_date={bundle.trade_date}"
    base.mkdir(parents=True, exist_ok=True)
    paths = {
        "security_master": base / "security_master.csv",
        "minute_bar": base / "minute_bar.csv",
    }
    _write_security_master(paths["security_master"], bundle)
    _write_minute_bar(paths["minute_bar"], bundle)
    return {key: str(value) for key, value in paths.items()}


def _write_security_master(path: Path, bundle: DailyMarketBundle) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["symbol", "name", "asset_type", "currency", "list_date", "delist_date", "status"],
        )
        writer.writeheader()
        for record in bundle.securities:
            writer.writerow(
                {
                    "symbol": record.symbol,
                    "name": record.name,
                    "asset_type": record.asset_type,
                    "currency": record.currency,
                    "list_date": record.list_date or "",
                    "delist_date": record.delist_date or "",
                    "status": record.status,
                }
            )


def _write_trading_calendar(path: Path, bundle: DailyMarketBundle) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "exchange",
                "trade_date",
                "is_open",
                "session_type",
                "pretrade_date",
                "next_trade_date",
                "open_time",
                "close_time",
            ],
        )
        writer.writeheader()
        for record in bundle.calendars:
            writer.writerow(
                {
                    "exchange": record.exchange,
                    "trade_date": record.trade_date,
                    "is_open": str(record.is_open).lower(),
                    "session_type": record.session_type,
                    "pretrade_date": record.pretrade_date or "",
                    "next_trade_date": record.next_trade_date or "",
                    "open_time": record.open_time or "",
                    "close_time": record.close_time or "",
                }
            )


def _write_daily_bar(path: Path, bundle: DailyMarketBundle) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "symbol",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "volume",
                "amount",
                "vwap",
                "turnover_rate",
                "limit_up",
                "limit_down",
                "is_suspended",
                "factor_forward",
                "factor_backward",
                "ex_right_type",
            ],
        )
        writer.writeheader()
        for record in bundle.daily_bars:
            writer.writerow(
                {
                    "symbol": record.symbol,
                    "trade_date": record.trade_date,
                    "open": _blank(record.open),
                    "high": _blank(record.high),
                    "low": _blank(record.low),
                    "close": _blank(record.close),
                    "pre_close": _blank(record.pre_close),
                    "volume": _blank(record.volume),
                    "amount": _blank(record.amount),
                    "vwap": _blank(record.vwap),
                    "turnover_rate": _blank(record.turnover_rate),
                    "limit_up": _blank(record.limit_up),
                    "limit_down": _blank(record.limit_down),
                    "is_suspended": str(record.is_suspended).lower(),
                    "factor_forward": _blank(record.factor_forward),
                    "factor_backward": _blank(record.factor_backward),
                    "ex_right_type": record.ex_right_type,
                }
            )


def _write_adjustment_factor(path: Path, bundle: MarketConstraintBundle) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["symbol", "trade_date", "factor_forward", "factor_backward", "ex_right_type"],
        )
        writer.writeheader()
        for record in bundle.adjustment_factors:
            writer.writerow(
                {
                    "symbol": record.symbol,
                    "trade_date": record.trade_date,
                    "factor_forward": _blank(record.factor_forward),
                    "factor_backward": _blank(record.factor_backward),
                    "ex_right_type": record.ex_right_type,
                }
            )


def _write_limit_price(path: Path, bundle: MarketConstraintBundle) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["symbol", "trade_date", "limit_up", "limit_down", "limit_rule", "is_st", "is_new_listing"],
        )
        writer.writeheader()
        for record in bundle.limit_prices:
            writer.writerow(
                {
                    "symbol": record.symbol,
                    "trade_date": record.trade_date,
                    "limit_up": _blank(record.limit_up),
                    "limit_down": _blank(record.limit_down),
                    "limit_rule": record.limit_rule,
                    "is_st": str(record.is_st).lower(),
                    "is_new_listing": str(record.is_new_listing).lower(),
                }
            )


def _write_suspension(path: Path, bundle: MarketConstraintBundle) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["symbol", "start_time", "end_time", "suspension_type", "reason"],
        )
        writer.writeheader()
        for record in bundle.suspensions:
            writer.writerow(
                {
                    "symbol": record.symbol,
                    "start_time": record.start_time,
                    "end_time": record.end_time or "",
                    "suspension_type": record.suspension_type,
                    "reason": record.reason or "",
                }
            )


def _write_minute_bar(path: Path, bundle: MinuteMarketBundle) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["symbol", "trade_date", "bar_time", "open", "high", "low", "close", "volume", "amount", "vwap"],
        )
        writer.writeheader()
        for record in bundle.minute_bars:
            writer.writerow(
                {
                    "symbol": record.symbol,
                    "trade_date": record.trade_date,
                    "bar_time": record.bar_time,
                    "open": _blank(record.open),
                    "high": _blank(record.high),
                    "low": _blank(record.low),
                    "close": _blank(record.close),
                    "volume": _blank(record.volume),
                    "amount": _blank(record.amount),
                    "vwap": _blank(record.vwap),
                }
            )


def _blank(value) -> str:
    return "" if value is None else str(value)
