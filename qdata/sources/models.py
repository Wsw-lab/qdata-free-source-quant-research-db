from __future__ import annotations

from dataclasses import dataclass

from qdata.ingest.models import (
    AdjustmentFactorRecord,
    CalendarRecord,
    DailyBarRecord,
    LimitPriceRecord,
    MinuteBarRecord,
    SecurityRecord,
    SuspensionRecord,
)


@dataclass(frozen=True)
class DailyMarketBundle:
    provider: str
    trade_date: str
    securities: list[SecurityRecord]
    calendars: list[CalendarRecord]
    daily_bars: list[DailyBarRecord]


@dataclass(frozen=True)
class MarketConstraintBundle:
    provider: str
    trade_date: str
    securities: list[SecurityRecord]
    adjustment_factors: list[AdjustmentFactorRecord]
    limit_prices: list[LimitPriceRecord]
    suspensions: list[SuspensionRecord]


@dataclass(frozen=True)
class MinuteMarketBundle:
    provider: str
    trade_date: str
    securities: list[SecurityRecord]
    minute_bars: list[MinuteBarRecord]
