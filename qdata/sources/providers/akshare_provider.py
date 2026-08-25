from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from qdata.backend_utils import parse_date
from qdata.exceptions import QDataProviderError, QDataValidationError
from qdata.ingest.models import (
    AdjustmentFactorRecord,
    CalendarRecord,
    DailyBarRecord,
    LimitPriceRecord,
    MinuteBarRecord,
    SecurityRecord,
    SuspensionRecord,
)
from qdata.sources.models import DailyMarketBundle, MarketConstraintBundle, MinuteMarketBundle


class AkShareProvider:
    """AkShare daily A-share provider.

    AkShare is imported lazily because it is an optional dependency. The
    provider currently syncs explicit symbols only; full-market sync should be
    batched before production use.
    """

    def __init__(self, adjust: str = "", lookup_names: bool = False, allow_full_market: bool = False) -> None:
        self.adjust = adjust
        self.lookup_names = lookup_names
        self.allow_full_market = allow_full_market

    def fetch_daily_market(
        self,
        trade_date: str,
        symbols: list[str] | None = None,
    ) -> DailyMarketBundle:
        if not symbols:
            if not self.allow_full_market:
                raise QDataValidationError("akshare provider requires --symbols unless allow_full_market=True")
            symbols = self.list_symbols(trade_date)
        parse_date(trade_date, "trade_date")
        ak = self._import_akshare()
        security_name_map = self._fetch_security_names(ak) if self.lookup_names else {}

        securities = [
            SecurityRecord(
                symbol=symbol,
                name=security_name_map.get(_code(symbol), symbol),
                asset_type="stock",
                currency="CNY",
                status="active",
            )
            for symbol in symbols
        ]
        daily_bars: list[DailyBarRecord] = []
        for symbol in symbols:
            _validate_symbol(symbol)
            hist_df = self._fetch_history(ak, symbol=symbol, trade_date=trade_date)
            daily_bars.extend(
                record
                for record in self._hist_to_bars(symbol, hist_df)
                if record.trade_date == trade_date
            )

        exchanges = sorted({record.exchange for record in daily_bars})
        calendars = [
            CalendarRecord(
                exchange=exchange,
                trade_date=trade_date,
                is_open=bool(daily_bars),
                session_type="full_day" if daily_bars else "closed",
            )
            for exchange in exchanges
        ]
        return DailyMarketBundle(
            provider="akshare",
            trade_date=trade_date,
            securities=securities,
            calendars=calendars,
            daily_bars=daily_bars,
        )

    def list_symbols(self, trade_date: str | None = None) -> list[str]:
        return [record.symbol for record in self.list_securities(trade_date)]

    def fetch_market_constraints(
        self,
        trade_date: str,
        symbols: list[str] | None = None,
    ) -> MarketConstraintBundle:
        bundle = self.fetch_daily_market(trade_date=trade_date, symbols=symbols)
        ak = self._import_akshare()
        adjustment_factors = [
            self._adjustment_factor_from_prices(ak, record)
            for record in bundle.daily_bars
        ]
        limit_prices = [
            LimitPriceRecord(
                symbol=record.symbol,
                trade_date=record.trade_date,
                limit_up=record.limit_up,
                limit_down=record.limit_down,
                limit_rule=_limit_rule(record.symbol),
                is_st=False,
                is_new_listing=False,
            )
            for record in bundle.daily_bars
        ]
        suspensions = [
            SuspensionRecord(
                symbol=record.symbol,
                start_time=f"{record.trade_date} 09:30:00",
                end_time=f"{record.trade_date} 15:00:00",
                suspension_type="full_day",
                reason="akshare daily bar marked suspended",
            )
            for record in bundle.daily_bars
            if record.is_suspended
        ]
        return MarketConstraintBundle(
            provider="akshare",
            trade_date=trade_date,
            securities=bundle.securities,
            adjustment_factors=adjustment_factors,
            limit_prices=limit_prices,
            suspensions=suspensions,
        )

    def fetch_minute_market(
        self,
        trade_date: str,
        symbols: list[str] | None = None,
    ) -> MinuteMarketBundle:
        if not symbols:
            if not self.allow_full_market:
                raise QDataValidationError("akshare minute provider requires --symbols unless allow_full_market=True")
            symbols = self.list_symbols(trade_date)
        ak = self._import_akshare()
        securities = [
            SecurityRecord(symbol=symbol, name=symbol, asset_type="stock", currency="CNY", status="active")
            for symbol in symbols
        ]
        minute_bars: list[MinuteBarRecord] = []
        for symbol in symbols:
            try:
                minute_df = ak.stock_zh_a_hist_min_em(
                    symbol=_code(symbol),
                    start_date=f"{trade_date} 09:30:00",
                    end_date=f"{trade_date} 15:00:00",
                    period="1",
                    adjust="",
                )
            except Exception as exc:
                raise QDataProviderError(
                    f"akshare minute fetch failed for {symbol} on {trade_date}: {exc}"
                ) from exc
            mapped = self._minute_df_to_bars(symbol, minute_df, trade_date)
            if not mapped:
                raise QDataProviderError(
                    f"akshare returned no minute bars for {symbol} on {trade_date}"
                )
            minute_bars.extend(mapped)
        return MinuteMarketBundle(
            provider="akshare",
            trade_date=trade_date,
            securities=securities,
            minute_bars=minute_bars,
        )

    def list_securities(self, trade_date: str | None = None) -> list[SecurityRecord]:
        ak = self._import_akshare()
        securities = self._list_securities_from_code_name(ak)
        if securities:
            return securities
        try:
            with _eastmoney_request_headers():
                spot_df = ak.stock_zh_a_spot_em()
        except Exception as exc:
            raise QDataProviderError(f"akshare full-market security list request failed: {exc}") from exc
        if spot_df is None or getattr(spot_df, "empty", True):
            raise QDataProviderError("akshare returned an empty full-market security list")
        columns = set(spot_df.columns)
        code_col = "代码" if "代码" in columns else "股票代码" if "股票代码" in columns else None
        name_col = "名称" if "名称" in columns else "股票简称" if "股票简称" in columns else None
        if not code_col:
            raise QDataProviderError("akshare full-market security list does not include a code column")
        securities: list[SecurityRecord] = []
        for _, row in spot_df.iterrows():
            code = str(row[code_col]).zfill(6)
            symbol = _symbol_from_code(code)
            if symbol is None:
                continue
            name = str(row[name_col]) if name_col else symbol
            securities.append(SecurityRecord(symbol=symbol, name=name, asset_type="stock", currency="CNY", status="active"))
        return securities

    @staticmethod
    def _list_securities_from_code_name(ak) -> list[SecurityRecord]:
        try:
            code_name_df = ak.stock_info_a_code_name()
        except Exception:
            return []
        if code_name_df is None or getattr(code_name_df, "empty", True):
            return []
        columns = set(code_name_df.columns)
        code_col = "code" if "code" in columns else "代码" if "代码" in columns else None
        name_col = "name" if "name" in columns else "名称" if "名称" in columns else None
        if not code_col:
            return []
        securities = []
        for _, row in code_name_df.iterrows():
            code = str(row[code_col]).zfill(6)
            symbol = _symbol_from_code(code)
            if symbol is None:
                continue
            name = str(row[name_col]) if name_col else symbol
            securities.append(SecurityRecord(symbol=symbol, name=name, asset_type="stock", currency="CNY", status="active"))
        return securities

    def is_trade_date(self, trade_date: str) -> bool:
        target = parse_date(trade_date, "trade_date")
        ak = self._import_akshare()
        try:
            calendar_df = ak.tool_trade_date_hist_sina()
            if calendar_df is not None and not getattr(calendar_df, "empty", True):
                date_col = "trade_date" if "trade_date" in set(calendar_df.columns) else calendar_df.columns[0]
                dates = {str(row[date_col])[:10] for _, row in calendar_df.iterrows()}
                return trade_date in dates
        except Exception:
            pass
        return target.weekday() < 5

    @staticmethod
    def _import_akshare():
        try:
            import akshare as ak
        except ImportError as exc:
            raise QDataValidationError(
                "akshare is required for provider='akshare'. Install qdata[akshare] with Python 3.10+."
            ) from exc
        return ak

    @classmethod
    def _fetch_security_names(cls, ak) -> dict[str, str]:
        try:
            with _eastmoney_request_headers():
                return cls._security_names(ak.stock_zh_a_spot_em())
        except Exception:
            return {}

    @staticmethod
    def _security_names(spot_df: Any) -> dict[str, str]:
        if spot_df is None or getattr(spot_df, "empty", True):
            return {}
        columns = set(spot_df.columns)
        code_col = "代码" if "代码" in columns else "股票代码" if "股票代码" in columns else None
        name_col = "名称" if "名称" in columns else "股票简称" if "股票简称" in columns else None
        if not code_col or not name_col:
            return {}
        return {
            str(row[code_col]).zfill(6): str(row[name_col])
            for _, row in spot_df[[code_col, name_col]].iterrows()
        }

    def _fetch_history(self, ak, symbol: str, trade_date: str):
        compact_date = trade_date.replace("-", "")
        try:
            with _eastmoney_request_headers():
                return ak.stock_zh_a_hist(
                    symbol=_code(symbol),
                    period="daily",
                    start_date=compact_date,
                    end_date=compact_date,
                    adjust=self.adjust,
                )
        except Exception as primary_exc:
            try:
                return ak.stock_zh_a_daily(
                    symbol=_akshare_daily_symbol(symbol),
                    start_date=_lookback_date(compact_date),
                    end_date=compact_date,
                    adjust=self.adjust,
                )
            except Exception as fallback_exc:
                raise QDataProviderError(
                    "akshare daily history request failed for "
                    f"{symbol}: hist={primary_exc}; daily={fallback_exc}"
                ) from fallback_exc

    def _adjustment_factor_from_prices(self, ak, record: DailyBarRecord) -> AdjustmentFactorRecord:
        raw_close = record.close
        forward_close = self._adjusted_close(ak, record.symbol, record.trade_date, "qfq")
        backward_close = self._adjusted_close(ak, record.symbol, record.trade_date, "hfq")
        factor_forward = forward_close / raw_close if raw_close and forward_close else record.factor_forward
        factor_backward = backward_close / raw_close if raw_close and backward_close else record.factor_backward
        return AdjustmentFactorRecord(
            symbol=record.symbol,
            trade_date=record.trade_date,
            factor_forward=factor_forward,
            factor_backward=factor_backward,
            ex_right_type=record.ex_right_type,
        )

    def _adjusted_close(self, ak, symbol: str, trade_date: str, adjust: str) -> float | None:
        compact_date = trade_date.replace("-", "")
        try:
            with _eastmoney_request_headers():
                hist_df = ak.stock_zh_a_hist(
                    symbol=_code(symbol),
                    period="daily",
                    start_date=compact_date,
                    end_date=compact_date,
                    adjust=adjust,
                )
        except Exception:
            try:
                hist_df = ak.stock_zh_a_daily(
                    symbol=_akshare_daily_symbol(symbol),
                    start_date=compact_date,
                    end_date=compact_date,
                    adjust=adjust,
                )
            except Exception:
                return None
        for item in self._hist_to_bars(symbol, hist_df):
            if item.trade_date == trade_date:
                return item.close
        return None

    def _hist_to_bars(self, symbol: str, hist_df: Any) -> list[DailyBarRecord]:
        if hist_df is None or getattr(hist_df, "empty", True):
            return []
        bars = []
        columns = set(hist_df.columns)
        chinese_schema = "日期" in columns
        previous_close = None
        for _, row in hist_df.iterrows():
            trade_date = str(row["日期"] if chinese_schema else row["date"])[:10]
            close = _float(row.get("收盘") if chinese_schema else row.get("close"))
            change_amount = _float(row.get("涨跌额"), default=0.0) if chinese_schema else None
            pre_close = close - change_amount if close is not None and change_amount is not None else previous_close
            raw_volume = _float(row.get("成交量") if chinese_schema else row.get("volume"))
            volume_shares = raw_volume * 100 if chinese_schema and raw_volume is not None else raw_volume
            raw_turnover = _float(row.get("换手率") if chinese_schema else row.get("turnover"))
            limit_up, limit_down = _basic_limit_prices(symbol, pre_close)
            bars.append(
                DailyBarRecord(
                    symbol=symbol,
                    trade_date=trade_date,
                    open=_float(row.get("开盘") if chinese_schema else row.get("open")),
                    high=_float(row.get("最高") if chinese_schema else row.get("high")),
                    low=_float(row.get("最低") if chinese_schema else row.get("low")),
                    close=close,
                    pre_close=pre_close,
                    volume=volume_shares,
                    amount=_float(row.get("成交额") if chinese_schema else row.get("amount")),
                    vwap=None,
                    turnover_rate=(raw_turnover / 100 if chinese_schema else raw_turnover)
                    if raw_turnover is not None
                    else None,
                    limit_up=limit_up,
                    limit_down=limit_down,
                    is_suspended=False,
                    factor_forward=1.0,
                    factor_backward=1.0,
                    ex_right_type="none",
                )
            )
            previous_close = close
        return bars

    @staticmethod
    def _minute_df_to_bars(symbol: str, minute_df: Any, trade_date: str) -> list[MinuteBarRecord]:
        if minute_df is None or getattr(minute_df, "empty", True):
            return []
        columns = set(minute_df.columns)
        time_col = "时间" if "时间" in columns else "day" if "day" in columns else minute_df.columns[0]
        bars = []
        for _, row in minute_df.iterrows():
            bar_time = str(row[time_col])[:19]
            if bar_time[:10] != trade_date:
                continue
            amount = _float(row.get("成交额") if "成交额" in columns else row.get("amount"))
            volume = _float(row.get("成交量") if "成交量" in columns else row.get("volume"))
            bars.append(
                MinuteBarRecord(
                    symbol=symbol,
                    trade_date=trade_date,
                    bar_time=bar_time,
                    open=_float(row.get("开盘") if "开盘" in columns else row.get("open")),
                    high=_float(row.get("最高") if "最高" in columns else row.get("high")),
                    low=_float(row.get("最低") if "最低" in columns else row.get("low")),
                    close=_float(row.get("收盘") if "收盘" in columns else row.get("close")),
                    volume=volume,
                    amount=amount,
                    vwap=(amount / volume) if amount is not None and volume not in {None, 0} else None,
                )
            )
        return bars


def _code(symbol: str) -> str:
    return symbol.split(".")[0]


def _akshare_daily_symbol(symbol: str) -> str:
    exchange = symbol.split(".")[1].lower()
    if exchange == "bj":
        exchange = "bj"
    return f"{exchange}{_code(symbol)}"


def _symbol_from_code(code: str) -> str | None:
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "2", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8", "9")):
        return f"{code}.BJ"
    return None


def _lookback_date(compact_date: str) -> str:
    date_value = datetime.strptime(compact_date, "%Y%m%d").date()
    return (date_value - timedelta(days=20)).strftime("%Y%m%d")


@contextmanager
def _eastmoney_request_headers():
    try:
        import requests
    except ImportError:
        yield
        return

    original_request = requests.sessions.Session.request

    def request_with_headers(self, method, url, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        )
        headers.setdefault("Referer", "https://quote.eastmoney.com/")
        return original_request(self, method, url, headers=headers, **kwargs)

    requests.sessions.Session.request = request_with_headers
    try:
        yield
    finally:
        requests.sessions.Session.request = original_request


def _float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        if value != value:
            return default
    except TypeError:
        pass
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text:
        return default
    return float(text)


def _validate_symbol(symbol: str) -> None:
    parts = symbol.split(".")
    if len(parts) != 2 or parts[1] not in {"SH", "SZ", "BJ"}:
        raise QDataValidationError(f"symbol must look like 600519.SH, 000001.SZ or 430047.BJ: {symbol}")


def _basic_limit_prices(symbol: str, pre_close: float | None) -> tuple[float | None, float | None]:
    if pre_close is None:
        return None, None
    code = _code(symbol)
    exchange = symbol.split(".")[1]
    pct = 0.30 if exchange == "BJ" else 0.20 if code.startswith(("30", "68")) else 0.10
    return round(pre_close * (1 + pct), 2), round(pre_close * (1 - pct), 2)


def _limit_rule(symbol: str) -> str:
    code = _code(symbol)
    if symbol.endswith(".BJ"):
        return "bj_30pct"
    if code.startswith(("30", "68")):
        return "growth_20pct"
    return "main_10pct"
