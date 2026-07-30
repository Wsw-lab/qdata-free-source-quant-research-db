from __future__ import annotations

import json
import os
from typing import Any
from urllib import request

from qdata.backend_utils import parse_date
from qdata.exceptions import QDataProviderError, QDataValidationError
from qdata.ingest.models import CalendarRecord, DailyBarRecord, SecurityRecord
from qdata.sources.models import DailyMarketBundle


class TushareFreeProvider:
    """Tushare Pro HTTP provider for free-quota canaries.

    Tushare Pro requires a user token. The provider intentionally blocks with a
    validation error when the token is missing so free-source fabric never treats
    a local fixture as a successful Tushare run.
    """

    def __init__(
        self,
        token: str | None = None,
        token_env: str = "QDATA_TUSHARE_TOKEN",
        base_url: str = "http://api.tushare.pro",
        timeout_seconds: float = 12.0,
        request_func=None,
    ) -> None:
        self.token = token or os.getenv(token_env)
        self.token_env = token_env
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.request_func = request_func or request.urlopen

    def fetch_daily_market(self, trade_date: str, symbols: list[str] | None = None) -> DailyMarketBundle:
        parse_date(trade_date, "trade_date")
        normalized_symbols = _normalize_symbols(symbols)
        if not normalized_symbols:
            raise QDataValidationError("tushare_free provider requires --symbols for canary sync")
        rows = [
            row
            for symbol in normalized_symbols
            for row in self._call(
                "daily",
                {
                    "ts_code": symbol,
                    "start_date": _compact_date(trade_date),
                    "end_date": _compact_date(trade_date),
                },
                "ts_code,trade_date,open,high,low,close,pre_close,vol,amount",
            )
        ]
        daily_bars = [self._daily_bar_from_row(row) for row in rows]
        securities = [SecurityRecord(symbol=symbol, name=symbol, asset_type="stock", currency="CNY") for symbol in normalized_symbols]
        calendars = self._calendar_rows(trade_date, normalized_symbols, bool(daily_bars))
        return DailyMarketBundle(
            provider="tushare_free",
            trade_date=trade_date,
            securities=securities,
            calendars=calendars,
            daily_bars=daily_bars,
        )

    def list_symbols(self, trade_date: str | None = None) -> list[str]:
        rows = self._call(
            "stock_basic",
            {"exchange": "", "list_status": "L"},
            "ts_code,name,list_date,delist_date",
        )
        return [str(row["ts_code"]) for row in rows]

    def is_trade_date(self, trade_date: str) -> bool:
        rows = self._call(
            "trade_cal",
            {"exchange": "SSE", "start_date": _compact_date(trade_date), "end_date": _compact_date(trade_date)},
            "exchange,cal_date,is_open,pretrade_date",
        )
        return bool(rows and int(rows[0].get("is_open") or 0) == 1)

    def _calendar_rows(self, trade_date: str, symbols: list[str], fallback_open: bool) -> list[CalendarRecord]:
        exchanges = sorted({_tushare_exchange(symbol) for symbol in symbols})
        rows_by_exchange: dict[str, dict[str, Any]] = {}
        for exchange in exchanges:
            try:
                rows = self._call(
                    "trade_cal",
                    {"exchange": exchange, "start_date": _compact_date(trade_date), "end_date": _compact_date(trade_date)},
                    "exchange,cal_date,is_open,pretrade_date",
                )
            except QDataProviderError:
                rows = []
            if rows:
                rows_by_exchange[exchange] = rows[0]
        return [
            CalendarRecord(
                exchange=_qdata_exchange(exchange),
                trade_date=trade_date,
                is_open=bool(int((rows_by_exchange.get(exchange) or {}).get("is_open") or int(fallback_open))),
                session_type="full_day" if bool(int((rows_by_exchange.get(exchange) or {}).get("is_open") or int(fallback_open))) else "closed",
                pretrade_date=_format_tushare_date((rows_by_exchange.get(exchange) or {}).get("pretrade_date")),
            )
            for exchange in exchanges
        ]

    def _call(self, api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if not self.token:
            raise QDataValidationError(f"{self.token_env} is required for tushare_free provider")
        body = json.dumps(
            {
                "api_name": api_name,
                "token": self.token,
                "params": params,
                "fields": fields,
            }
        ).encode("utf-8")
        http_request = request.Request(
            self.base_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self.request_func(http_request, timeout=self.timeout_seconds)
            payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise QDataProviderError(f"tushare_free request failed for {api_name}: {exc}") from exc
        if int(payload.get("code") or 0) != 0:
            raise QDataProviderError(f"tushare_free {api_name} failed: {payload.get('msg')}")
        data = payload.get("data") or {}
        field_names = list(data.get("fields") or [])
        return [dict(zip(field_names, item)) for item in data.get("items") or []]

    @staticmethod
    def _daily_bar_from_row(row: dict[str, Any]) -> DailyBarRecord:
        symbol = str(row["ts_code"])
        pre_close = _float(row.get("pre_close"))
        limit_up, limit_down = _basic_limit_prices(symbol, pre_close)
        return DailyBarRecord(
            symbol=symbol,
            trade_date=_format_tushare_date(row["trade_date"]) or str(row["trade_date"]),
            open=_float(row.get("open")),
            high=_float(row.get("high")),
            low=_float(row.get("low")),
            close=_float(row.get("close")),
            pre_close=pre_close,
            volume=_float(row.get("vol"), 0.0) * 100,
            amount=_float(row.get("amount"), 0.0) * 1000,
            turnover_rate=None,
            limit_up=limit_up,
            limit_down=limit_down,
            is_suspended=False,
            factor_forward=1.0,
            factor_backward=1.0,
            ex_right_type="none",
        )


def _normalize_symbols(symbols: list[str] | None) -> list[str]:
    return [str(symbol).strip().upper() for symbol in symbols or [] if str(symbol).strip()]


def _compact_date(value: str) -> str:
    return value.replace("-", "")


def _format_tushare_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def _tushare_exchange(symbol: str) -> str:
    suffix = symbol.split(".")[1]
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(suffix, suffix)


def _qdata_exchange(exchange: str) -> str:
    return {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(exchange, exchange)


def _float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    text = str(value).replace(",", "").replace("%", "").strip()
    return float(text) if text else default


def _basic_limit_prices(symbol: str, pre_close: float | None) -> tuple[float | None, float | None]:
    if pre_close is None:
        return None, None
    code = symbol.split(".")[0]
    exchange = symbol.split(".")[1]
    pct = 0.30 if exchange == "BJ" else 0.20 if code.startswith(("30", "68")) else 0.10
    return round(pre_close * (1 + pct), 2), round(pre_close * (1 - pct), 2)
