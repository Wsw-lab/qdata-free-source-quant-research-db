from __future__ import annotations

from collections import Counter

from qdata.ingest.models import CalendarRecord, DailyBarRecord, QualityReport, SecurityRecord


def check_daily_bundle_quality(
    securities: list[SecurityRecord],
    calendars: list[CalendarRecord],
    daily_bars: list[DailyBarRecord],
    expected_symbols: list[str] | None = None,
    min_completeness: float = 1.0,
) -> QualityReport:
    report = QualityReport()
    _check_security_master(securities, report)
    _check_calendar(calendars, report)
    _check_daily_bars(securities, calendars, daily_bars, report, expected_symbols, min_completeness)
    return report


def daily_bar_completeness(
    daily_bars: list[DailyBarRecord],
    expected_symbols: list[str] | None,
    securities: list[SecurityRecord] | None = None,
    trade_date: str | None = None,
) -> dict:
    expected = sorted({symbol.strip().upper() for symbol in expected_symbols or [] if symbol.strip()})
    actual = sorted({record.symbol for record in daily_bars})
    actual_set = set(actual)
    securities_by_symbol = {record.symbol: record for record in securities or []}
    if not expected:
        return {
            "expected_count": None,
            "actual_count": len(actual),
            "missing_count": 0,
            "missing_symbols": [],
            "completeness_rate": None,
            "expected_by_exchange": {},
            "actual_by_exchange": _count_by_exchange(actual),
            "missing_by_exchange": {},
            "completeness_by_exchange": {},
            "missing_explanations": {},
            "excluded_symbols": {},
            "unexplained_missing_count": 0,
        }

    effective_expected = []
    excluded_symbols: dict[str, list[str]] = {}
    missing_explanations: dict[str, dict] = {}
    for symbol in expected:
        reason = _inactive_reason(securities_by_symbol.get(symbol), trade_date)
        if reason:
            excluded_symbols.setdefault(reason, []).append(symbol)
            missing_explanations[symbol] = {
                "status": "excluded",
                "reason": reason,
                "exchange": _exchange_from_symbol(symbol),
            }
            continue
        effective_expected.append(symbol)

    expected_set = set(effective_expected)
    missing = sorted(expected_set - actual_set)
    missing_by_exchange = _group_by_exchange(missing)
    for symbol in missing:
        reason = "not_in_security_master" if securities is not None and symbol not in securities_by_symbol else "unexplained_missing"
        missing_explanations[symbol] = {
            "status": "missing",
            "reason": reason,
            "exchange": _exchange_from_symbol(symbol),
        }
    expected_by_exchange = _count_by_exchange(effective_expected)
    actual_expected_symbols = sorted(actual_set & expected_set)
    actual_by_exchange = _count_by_exchange(actual_expected_symbols)
    completeness_by_exchange = {
        exchange: (actual_by_exchange.get(exchange, 0) / expected_count if expected_count else None)
        for exchange, expected_count in expected_by_exchange.items()
    }
    return {
        "expected_count": len(effective_expected),
        "actual_count": len(actual_expected_symbols),
        "missing_count": len(missing),
        "missing_symbols": missing,
        "completeness_rate": len(actual_expected_symbols) / len(effective_expected) if effective_expected else None,
        "expected_by_exchange": expected_by_exchange,
        "actual_by_exchange": actual_by_exchange,
        "missing_by_exchange": missing_by_exchange,
        "completeness_by_exchange": completeness_by_exchange,
        "missing_explanations": missing_explanations,
        "excluded_symbols": excluded_symbols,
        "unexplained_missing_count": sum(
            1 for item in missing_explanations.values() if item.get("reason") == "unexplained_missing"
        ),
    }


def _check_security_master(securities: list[SecurityRecord], report: QualityReport) -> None:
    symbols = [record.symbol for record in securities]
    for symbol, count in Counter(symbols).items():
        if count > 1:
            report.add("security_master", "security_symbol_unique", "high", "duplicate security symbol", symbol=symbol)
    for record in securities:
        if not record.name:
            report.add("security_master", "security_name_required", "high", "security name is empty", symbol=record.symbol)
        if record.list_date and record.delist_date and record.delist_date < record.list_date:
            report.add("security_master", "security_date_order", "high", "delist_date is earlier than list_date", symbol=record.symbol)


def _check_calendar(calendars: list[CalendarRecord], report: QualityReport) -> None:
    keys = [(record.exchange, record.trade_date) for record in calendars]
    for key, count in Counter(keys).items():
        if count > 1:
            report.add("trading_calendar", "calendar_unique", "high", "duplicate calendar row", trade_date=key[1])


def _check_daily_bars(
    securities: list[SecurityRecord],
    calendars: list[CalendarRecord],
    daily_bars: list[DailyBarRecord],
    report: QualityReport,
    expected_symbols: list[str] | None,
    min_completeness: float,
) -> None:
    security_symbols = {record.symbol for record in securities}
    open_dates_by_exchange = {
        (record.exchange, record.trade_date)
        for record in calendars
        if record.is_open
    }
    keys = [(record.symbol, record.trade_date) for record in daily_bars]
    for key, count in Counter(keys).items():
        if count > 1:
            report.add("daily_bar", "daily_bar_unique", "high", "duplicate daily bar row", symbol=key[0], trade_date=key[1])

    trade_date = daily_bars[0].trade_date if daily_bars else calendars[0].trade_date if calendars else None
    _check_completeness(daily_bars, expected_symbols, min_completeness, report, securities, trade_date)

    for record in daily_bars:
        if record.symbol not in security_symbols:
            report.add("daily_bar", "daily_bar_symbol_known", "high", "symbol is not present in security master", symbol=record.symbol, trade_date=record.trade_date)
        if (record.exchange, record.trade_date) not in open_dates_by_exchange:
            report.add("daily_bar", "daily_bar_open_day", "medium", "bar date is not marked as open in trading calendar", symbol=record.symbol, trade_date=record.trade_date)
        _check_ohlc(record, report)
        _check_positive_prices(record, report)
        _check_non_negative(record, report)
        _check_limit_prices(record, report)
        _check_adjustment(record, report)
        _check_vwap(record, report)
        _check_amount_consistency(record, report)
        _check_turnover_sanity(record, report)


def _check_ohlc(record: DailyBarRecord, report: QualityReport) -> None:
    prices = [record.open, record.high, record.low, record.close]
    if any(value is None for value in prices):
        report.add("daily_bar", "ohlc_not_null", "high", "OHLC contains null", symbol=record.symbol, trade_date=record.trade_date)
        return
    high_floor = max(record.open, record.low, record.close)
    low_ceiling = min(record.open, record.high, record.close)
    if record.high < high_floor:
        report.add("daily_bar", "ohlc_high_valid", "high", "high is lower than open/low/close", symbol=record.symbol, trade_date=record.trade_date, field_name="high")
    if record.low > low_ceiling:
        report.add("daily_bar", "ohlc_low_valid", "high", "low is higher than open/high/close", symbol=record.symbol, trade_date=record.trade_date, field_name="low")


def _check_non_negative(record: DailyBarRecord, report: QualityReport) -> None:
    for field_name in ("volume", "amount", "turnover_rate"):
        value = getattr(record, field_name)
        if value is not None and value < 0:
            report.add("daily_bar", "non_negative", "high", f"{field_name} is negative", symbol=record.symbol, trade_date=record.trade_date, field_name=field_name)


def _check_positive_prices(record: DailyBarRecord, report: QualityReport) -> None:
    for field_name in ("open", "high", "low", "close", "pre_close"):
        value = getattr(record, field_name)
        if value is not None and value <= 0:
            report.add("daily_bar", "positive_price", "high", f"{field_name} must be positive", symbol=record.symbol, trade_date=record.trade_date, field_name=field_name)


def _check_limit_prices(record: DailyBarRecord, report: QualityReport) -> None:
    if record.limit_up is not None and record.close is not None and record.limit_up < record.close:
        report.add("limit_price_daily", "limit_up_valid", "high", "limit_up is lower than close", symbol=record.symbol, trade_date=record.trade_date, field_name="limit_up")
    if record.limit_down is not None and record.close is not None and record.limit_down > record.close:
        report.add("limit_price_daily", "limit_down_valid", "high", "limit_down is higher than close", symbol=record.symbol, trade_date=record.trade_date, field_name="limit_down")


def _check_adjustment(record: DailyBarRecord, report: QualityReport) -> None:
    for field_name in ("factor_forward", "factor_backward"):
        value = getattr(record, field_name)
        if value is not None and value <= 0:
            report.add("adjustment_factor", "adjustment_factor_positive", "high", f"{field_name} must be positive", symbol=record.symbol, trade_date=record.trade_date, field_name=field_name)


def _check_vwap(record: DailyBarRecord, report: QualityReport) -> None:
    if record.vwap is None or record.low is None or record.high is None:
        return
    if record.vwap < record.low or record.vwap > record.high:
        report.add("daily_bar", "vwap_in_price_range", "medium", "vwap is outside low/high range", symbol=record.symbol, trade_date=record.trade_date, field_name="vwap")


def _check_amount_consistency(record: DailyBarRecord, report: QualityReport) -> None:
    if not record.volume or record.amount is None or record.vwap is None:
        return
    expected_amount = record.volume * record.vwap
    if expected_amount <= 0:
        return
    relative_diff = abs(record.amount - expected_amount) / expected_amount
    if relative_diff > 0.05:
        report.add("daily_bar", "amount_volume_vwap_consistency", "medium", "amount differs from volume * vwap by more than 5%", symbol=record.symbol, trade_date=record.trade_date, field_name="amount")


def _check_turnover_sanity(record: DailyBarRecord, report: QualityReport) -> None:
    if record.turnover_rate is not None and record.turnover_rate > 3:
        report.add("daily_bar", "turnover_rate_sanity", "medium", "turnover_rate is greater than 300%", symbol=record.symbol, trade_date=record.trade_date, field_name="turnover_rate")


def _check_completeness(
    daily_bars: list[DailyBarRecord],
    expected_symbols: list[str] | None,
    min_completeness: float,
    report: QualityReport,
    securities: list[SecurityRecord],
    trade_date: str | None,
) -> None:
    completeness = daily_bar_completeness(
        daily_bars,
        expected_symbols,
        securities=securities,
        trade_date=trade_date,
    )
    expected_count = completeness["expected_count"]
    if not expected_count:
        return
    missing_symbols = completeness["missing_symbols"]
    completeness_rate = completeness["completeness_rate"]
    if missing_symbols:
        report.add(
            "daily_bar",
            "daily_bar_missing_symbols",
            "medium",
            f"{len(missing_symbols)} expected symbol(s) have no daily bar",
        )
    if completeness_rate is not None and completeness_rate < min_completeness:
        report.add(
            "daily_bar",
            "daily_bar_completeness_below_threshold",
            "medium",
            f"daily bar completeness {completeness_rate:.4f} is below threshold {min_completeness:.4f}",
        )


def _inactive_reason(security: SecurityRecord | None, trade_date: str | None) -> str | None:
    if not security or not trade_date:
        return None
    if security.list_date and security.list_date > trade_date:
        return "listed_after_trade_date"
    if security.delist_date and security.delist_date < trade_date:
        return "delisted_before_trade_date"
    return None


def _exchange_from_symbol(symbol: str) -> str:
    parts = symbol.split(".")
    return parts[1] if len(parts) > 1 and parts[1] else "UNKNOWN"


def _count_by_exchange(symbols: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for symbol in symbols:
        exchange = _exchange_from_symbol(symbol)
        result[exchange] = result.get(exchange, 0) + 1
    return result


def _group_by_exchange(symbols: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for symbol in symbols:
        result.setdefault(_exchange_from_symbol(symbol), []).append(symbol)
    return result
