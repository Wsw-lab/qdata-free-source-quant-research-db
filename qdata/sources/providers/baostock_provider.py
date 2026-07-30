from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import socket
from typing import Any

from qdata.backend_utils import parse_date
from qdata.exceptions import QDataProviderError, QDataValidationError
from qdata.ingest.models import CalendarRecord, DailyBarRecord, SecurityRecord
from qdata.sources.models import DailyMarketBundle


class BaoStockProvider:
    """BaoStock A-share daily provider.

    BaoStock uses a socket connection rather than normal HTTP requests, so the
    provider wraps login with a socket default timeout to avoid live canaries
    hanging indefinitely when the BaoStock host or port is unreachable.
    """

    def __init__(self, timeout_seconds: float = 8.0, baostock_module: Any | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self._baostock_module = baostock_module

    def fetch_daily_market(self, trade_date: str, symbols: list[str] | None = None) -> DailyMarketBundle:
        parse_date(trade_date, "trade_date")
        normalized_symbols = _normalize_symbols(symbols)
        if not normalized_symbols:
            raise QDataValidationError("baostock provider requires --symbols for canary sync")
        bs = self._import_baostock()
        with self._session(bs):
            daily_bars = [
                bar
                for symbol in normalized_symbols
                for bar in self._fetch_daily_bars(bs, symbol, trade_date)
            ]
            securities = [
                self._fetch_security(bs, symbol) or SecurityRecord(symbol=symbol, name=symbol)
                for symbol in normalized_symbols
            ]
            calendars = self._fetch_calendar(bs, trade_date, normalized_symbols, bool(daily_bars))
        return DailyMarketBundle(
            provider="baostock",
            trade_date=trade_date,
            securities=securities,
            calendars=calendars,
            daily_bars=daily_bars,
        )

    def list_symbols(self, trade_date: str | None = None) -> list[str]:
        raise QDataValidationError("baostock list_symbols is disabled for canary; pass explicit symbols")

    def is_trade_date(self, trade_date: str) -> bool:
        bs = self._import_baostock()
        with self._session(bs):
            rows = self._result_rows(bs.query_trade_dates(start_date=trade_date, end_date=trade_date))
        if not rows:
            return parse_date(trade_date, "trade_date").weekday() < 5
        return str(rows[0].get("is_trading_day")) == "1"

    @contextmanager
    def _session(self, bs):
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self.timeout_seconds)
        logged_in = False
        try:
            login_result = bs.login()
            logged_in = True
            if str(getattr(login_result, "error_code", "0")) != "0":
                raise QDataProviderError(f"baostock login failed: {getattr(login_result, 'error_msg', '')}")
            yield
        except (OSError, TimeoutError) as exc:
            raise QDataProviderError(f"baostock connection failed or timed out: {exc}") from exc
        finally:
            if logged_in:
                try:
                    bs.logout()
                except Exception:
                    pass
            socket.setdefaulttimeout(previous_timeout)

    def _fetch_daily_bars(self, bs, symbol: str, trade_date: str) -> list[DailyBarRecord]:
        result = bs.query_history_k_data_plus(
            _baostock_code(symbol),
            "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg,isST",
            start_date=trade_date,
            end_date=trade_date,
            frequency="d",
            adjustflag="3",
        )
        return [self._daily_bar_from_row(row) for row in self._result_rows(result)]

    def _fetch_security(self, bs, symbol: str) -> SecurityRecord | None:
        try:
            rows = self._result_rows(bs.query_stock_basic(code=_baostock_code(symbol)))
        except Exception:
            return None
        if not rows:
            return None
        row = rows[0]
        return SecurityRecord(
            symbol=symbol,
            name=str(row.get("code_name") or symbol),
            asset_type="stock",
            currency="CNY",
            list_date=_date_or_none(row.get("ipoDate")),
            delist_date=_date_or_none(row.get("outDate")),
            status="active" if str(row.get("status") or "1") == "1" else "inactive",
        )

    def _fetch_calendar(self, bs, trade_date: str, symbols: list[str], has_daily_rows: bool) -> list[CalendarRecord]:
        exchanges = sorted({symbol.split(".")[1] for symbol in symbols})
        try:
            rows = self._result_rows(bs.query_trade_dates(start_date=trade_date, end_date=trade_date))
        except Exception:
            rows = []
        is_open = str(rows[0].get("is_trading_day")) == "1" if rows else has_daily_rows
        return [
            CalendarRecord(
                exchange=exchange,
                trade_date=trade_date,
                is_open=is_open,
                session_type="full_day" if is_open else "closed",
            )
            for exchange in exchanges
        ]

    @staticmethod
    def _daily_bar_from_row(row: dict[str, Any]) -> DailyBarRecord:
        symbol = _symbol_from_baostock_code(str(row["code"]))
        pre_close = _float(row.get("preclose"))
        limit_up, limit_down = _basic_limit_prices(symbol, pre_close)
        return DailyBarRecord(
            symbol=symbol,
            trade_date=str(row["date"])[:10],
            open=_float(row.get("open")),
            high=_float(row.get("high")),
            low=_float(row.get("low")),
            close=_float(row.get("close")),
            pre_close=pre_close,
            volume=_float(row.get("volume")),
            amount=_float(row.get("amount")),
            turnover_rate=_pct_to_ratio(row.get("turn")),
            limit_up=limit_up,
            limit_down=limit_down,
            is_suspended=False,
            factor_forward=1.0,
            factor_backward=1.0,
            ex_right_type="none",
        )

    @staticmethod
    def _result_rows(result) -> list[dict[str, Any]]:
        if str(getattr(result, "error_code", "0")) != "0":
            raise QDataProviderError(f"baostock query failed: {getattr(result, 'error_msg', '')}")
        fields = list(getattr(result, "fields", []) or [])
        rows: list[dict[str, Any]] = []
        while result.next():
            rows.append(dict(zip(fields, result.get_row_data())))
        return rows

    def _import_baostock(self):
        if self._baostock_module is not None:
            return self._baostock_module
        try:
            import baostock as bs
        except ImportError as exc:
            raise QDataValidationError(
                "baostock is required for provider='baostock'. Install qdata[free-sources]."
            ) from exc
        return bs


def _normalize_symbols(symbols: list[str] | None) -> list[str]:
    return [str(symbol).strip().upper() for symbol in symbols or [] if str(symbol).strip()]


def _baostock_code(symbol: str) -> str:
    parts = symbol.split(".")
    if len(parts) != 2 or parts[1] not in {"SH", "SZ", "BJ"}:
        raise QDataValidationError(f"symbol must look like 600519.SH, 000001.SZ or 430047.BJ: {symbol}")
    return f"{parts[1].lower()}.{parts[0]}"


def _symbol_from_baostock_code(code: str) -> str:
    exchange, raw_code = code.split(".", 1)
    return f"{raw_code.upper()}.{exchange.upper()}"


def _date_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)[:10]
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    text = str(value).replace(",", "").replace("%", "").strip()
    return float(text) if text else default


def _pct_to_ratio(value: Any) -> float | None:
    numeric = _float(value)
    return numeric / 100 if numeric is not None else None


def _basic_limit_prices(symbol: str, pre_close: float | None) -> tuple[float | None, float | None]:
    if pre_close is None:
        return None, None
    code = symbol.split(".")[0]
    exchange = symbol.split(".")[1]
    pct = 0.30 if exchange == "BJ" else 0.20 if code.startswith(("30", "68")) else 0.10
    return round(pre_close * (1 + pct), 2), round(pre_close * (1 - pct), 2)
