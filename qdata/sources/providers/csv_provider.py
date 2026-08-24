from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from qdata.exceptions import QDataProviderError
from qdata.ingest.csv_files import (
    read_adjustment_factors,
    read_daily_bars,
    read_limit_prices,
    read_minute_bars,
    read_security_master,
    read_suspensions,
    read_trading_calendar,
)
from qdata.ingest.models import AdjustmentFactorRecord, LimitPriceRecord, SuspensionRecord
from qdata.sources.models import DailyMarketBundle, MarketConstraintBundle, MinuteMarketBundle


class CsvProvider:
    def __init__(
        self,
        security_master_path: str | Path = "raw/samples/security_master.csv",
        trading_calendar_path: str | Path = "raw/samples/trading_calendar.csv",
        daily_bar_path: str | Path = "raw/samples/daily_bar.csv",
        adjustment_factor_path: str | Path = "raw/samples/adjustment_factor.csv",
        limit_price_path: str | Path = "raw/samples/limit_price_daily.csv",
        suspension_path: str | Path = "raw/samples/suspension_history.csv",
        minute_bar_path: str | Path = "raw/samples/minute_bar.csv",
        provider_name: str = "csv",
        close_offset_bps: float = 0.0,
        fail_daily: bool = False,
    ) -> None:
        self.security_master_path = security_master_path
        self.trading_calendar_path = trading_calendar_path
        self.daily_bar_path = daily_bar_path
        self.adjustment_factor_path = adjustment_factor_path
        self.limit_price_path = limit_price_path
        self.suspension_path = suspension_path
        self.minute_bar_path = minute_bar_path
        self.provider_name = provider_name
        self.close_offset_bps = close_offset_bps
        self.fail_daily = fail_daily

    def fetch_daily_market(
        self,
        trade_date: str,
        symbols: list[str] | None = None,
    ) -> DailyMarketBundle:
        if self.fail_daily:
            raise RuntimeError(f"{self.provider_name} daily market fetch failed by configuration")
        securities = read_security_master(self.security_master_path)
        calendars = read_trading_calendar(self.trading_calendar_path)
        daily_bars = read_daily_bars(self.daily_bar_path)
        if symbols:
            wanted = set(symbols)
            securities = [record for record in securities if record.symbol in wanted]
            daily_bars = [record for record in daily_bars if record.symbol in wanted]
        if trade_date:
            daily_bars = [record for record in daily_bars if record.trade_date == trade_date]
            exchanges = {record.exchange for record in daily_bars}
            calendars = [
                record
                for record in calendars
                if record.trade_date == trade_date and record.exchange in exchanges
            ]
        daily_bars = self._apply_close_offset(daily_bars)
        return DailyMarketBundle(
            provider=self.provider_name,
            trade_date=trade_date,
            securities=securities,
            calendars=calendars,
            daily_bars=daily_bars,
        )

    def fetch_market_constraints(
        self,
        trade_date: str,
        symbols: list[str] | None = None,
    ) -> MarketConstraintBundle:
        securities = read_security_master(self.security_master_path)
        daily_bars = read_daily_bars(self.daily_bar_path)
        wanted = set(symbols or [])
        if symbols:
            securities = [record for record in securities if record.symbol in wanted]
            daily_bars = [record for record in daily_bars if record.symbol in wanted]
        daily_bars = [record for record in daily_bars if record.trade_date == trade_date]
        adjustment_factors = _read_or_derive_adjustment_factors(self.adjustment_factor_path, daily_bars, trade_date, wanted)
        limit_prices = _read_or_derive_limit_prices(self.limit_price_path, daily_bars, securities, trade_date, wanted)
        suspensions = _read_or_derive_suspensions(self.suspension_path, daily_bars, trade_date, wanted)
        return MarketConstraintBundle(
            provider=self.provider_name,
            trade_date=trade_date,
            securities=securities,
            adjustment_factors=adjustment_factors,
            limit_prices=limit_prices,
            suspensions=suspensions,
        )

    def fetch_minute_market(
        self,
        trade_date: str,
        symbols: list[str] | None = None,
    ) -> MinuteMarketBundle:
        securities = read_security_master(self.security_master_path)
        wanted = set(symbols or [])
        if symbols:
            securities = [record for record in securities if record.symbol in wanted]
        if not Path(self.minute_bar_path).exists():
            raise QDataProviderError(
                f"csv minute data is unavailable: {self.minute_bar_path}; "
                "daily bars cannot be substituted for minute bars"
            )
        minute_bars = read_minute_bars(self.minute_bar_path)
        minute_bars = [record for record in minute_bars if record.trade_date == trade_date]
        if symbols:
            minute_bars = [record for record in minute_bars if record.symbol in wanted]
        return MinuteMarketBundle(
            provider=self.provider_name,
            trade_date=trade_date,
            securities=securities,
            minute_bars=minute_bars,
        )

    def list_symbols(self, trade_date: str | None = None) -> list[str]:
        return [record.symbol for record in read_security_master(self.security_master_path)]

    def is_trade_date(self, trade_date: str) -> bool:
        return any(
            record.trade_date == trade_date and record.is_open
            for record in read_trading_calendar(self.trading_calendar_path)
        )

    def _apply_close_offset(self, records):
        if not self.close_offset_bps:
            return records
        multiplier = 1 + self.close_offset_bps / 10_000
        return [
            replace(record, close=round(record.close * multiplier, 6)) if record.close is not None else record
            for record in records
        ]


def _read_or_derive_adjustment_factors(path, daily_bars, trade_date: str, wanted: set[str]):
    if Path(path).exists():
        records = read_adjustment_factors(path)
        return _filter_records(records, trade_date, wanted)
    return [
        AdjustmentFactorRecord(
            symbol=record.symbol,
            trade_date=record.trade_date,
            factor_forward=record.factor_forward,
            factor_backward=record.factor_backward,
            ex_right_type=record.ex_right_type,
        )
        for record in daily_bars
    ]


def _read_or_derive_limit_prices(path, daily_bars, securities, trade_date: str, wanted: set[str]):
    if Path(path).exists():
        records = read_limit_prices(path)
        return _filter_records(records, trade_date, wanted)
    security_by_symbol = {record.symbol: record for record in securities}
    return [
        LimitPriceRecord(
            symbol=record.symbol,
            trade_date=record.trade_date,
            limit_up=record.limit_up,
            limit_down=record.limit_down,
            limit_rule=_limit_rule(record.symbol, security_by_symbol.get(record.symbol), record.trade_date),
            is_st=_is_st(security_by_symbol.get(record.symbol)),
            is_new_listing=_is_new_listing(security_by_symbol.get(record.symbol), record.trade_date),
        )
        for record in daily_bars
    ]


def _read_or_derive_suspensions(path, daily_bars, trade_date: str, wanted: set[str]):
    if Path(path).exists():
        records = read_suspensions(path)
        if wanted:
            records = [record for record in records if record.symbol in wanted]
        return [
            record
            for record in records
            if record.start_time[:10] <= trade_date and (record.end_time is None or record.end_time[:10] >= trade_date)
        ]
    return [
        SuspensionRecord(
            symbol=record.symbol,
            start_time=f"{record.trade_date} 09:30:00",
            end_time=f"{record.trade_date} 15:00:00",
            suspension_type="full_day",
            reason="derived from daily bar is_suspended",
        )
        for record in daily_bars
        if record.is_suspended
    ]


def _filter_records(records, trade_date: str, wanted: set[str]):
    filtered = [record for record in records if record.trade_date == trade_date]
    if wanted:
        filtered = [record for record in filtered if record.symbol in wanted]
    return filtered


def _is_st(security) -> bool:
    return bool(security and security.name.upper().startswith(("ST", "*ST")))


def _is_new_listing(security, trade_date: str) -> bool:
    if not security or not security.list_date:
        return False
    from datetime import date

    return (date.fromisoformat(trade_date) - date.fromisoformat(security.list_date)).days < 30


def _limit_rule(symbol: str, security, trade_date: str) -> str:
    if _is_st(security):
        return "st_5pct"
    code = symbol.split(".")[0]
    if symbol.endswith(".BJ") or code.startswith(("3", "68")):
        return "growth_20pct"
    if _is_new_listing(security, trade_date):
        return "new_listing"
    return "main_10pct"
