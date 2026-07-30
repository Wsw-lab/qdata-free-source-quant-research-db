from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
import base64
import json
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from qdata.backend_utils import parse_date
from qdata.exceptions import QDataProviderError, QDataValidationError
from qdata.ingest.models import CalendarRecord, DailyBarRecord, SecurityRecord
from qdata.sources.field_mapping import normalize_vendor_row
from qdata.sources.models import DailyMarketBundle
from qdata.sources.providers.csv_provider import CsvProvider


@dataclass(frozen=True)
class ProviderErrorEvent:
    provider_name: str
    error_stage: str
    error_type: str
    retryable: bool
    error_message: str
    trade_date: str | None = None
    symbol: str | None = None
    attempt: int | None = None
    details: dict[str, Any] | None = None


class VendorHttpProvider:
    """Generic commercial vendor adapter.

    Production deployments configure HTTP mode with base_url/token/path. Local
    smoke tests can use fixture mode while exercising the same provider name,
    retry metadata, and source-quality scoring path.
    """

    def __init__(
        self,
        source_code: str = "vendor_http",
        base_url: str | None = None,
        daily_path: str = "/daily",
        token: str | None = None,
        auth_mode: str = "none",
        api_key_header: str = "X-API-Key",
        query_token_param: str = "token",
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30,
        retry_limit: int = 2,
        retry_sleep_seconds: float = 0,
        rate_limit_per_min: int | None = None,
        response_rows_key: str = "data",
        field_mapping: dict[str, str] | None = None,
        field_transforms: dict[str, str] | None = None,
        fixture_daily_bar_path: str | Path | None = None,
        fixture_security_master_path: str | Path = "raw/samples/security_master.csv",
        fixture_trading_calendar_path: str | Path = "raw/samples/trading_calendar.csv",
        close_offset_bps: float = 0,
        request_func: Callable[[Request, float], Any] | None = None,
    ) -> None:
        self.source_code = source_code
        self.base_url = base_url
        self.daily_path = daily_path
        self.token = token
        self.auth_mode = auth_mode
        self.api_key_header = api_key_header
        self.query_token_param = query_token_param
        self.username = username
        self.password = password
        self.timeout = timeout
        self.retry_limit = retry_limit
        self.retry_sleep_seconds = retry_sleep_seconds
        self.rate_limit_per_min = rate_limit_per_min
        self.response_rows_key = response_rows_key
        self.field_mapping = field_mapping
        self.field_transforms = field_transforms
        self.fixture_daily_bar_path = fixture_daily_bar_path
        self.fixture_security_master_path = fixture_security_master_path
        self.fixture_trading_calendar_path = fixture_trading_calendar_path
        self.close_offset_bps = close_offset_bps
        self.request_func = request_func or _default_request
        self.error_events: list[ProviderErrorEvent] = []
        self.request_count = 0
        self.last_duration_ms = 0.0
        self._request_times: list[float] = []

        if self.retry_limit < 0:
            raise QDataValidationError("retry_limit must be greater than or equal to 0")
        if self.rate_limit_per_min is not None and self.rate_limit_per_min <= 0:
            raise QDataValidationError("rate_limit_per_min must be greater than 0")
        if self.auth_mode not in {"none", "bearer", "header", "query", "basic"}:
            raise QDataValidationError("auth_mode must be one of: none, bearer, header, query, basic")

    def fetch_daily_market(self, trade_date: str, symbols: list[str] | None = None) -> DailyMarketBundle:
        parse_date(trade_date, "trade_date")
        if self.fixture_daily_bar_path:
            return self._fetch_fixture_daily_market(trade_date, symbols)
        if not self.base_url:
            raise QDataValidationError("base_url is required for vendor_http provider unless fixture_daily_bar_path is set")

        started = monotonic()
        payload = self._request_json(
            stage="request",
            params={
                "trade_date": trade_date,
                "symbols": ",".join(symbols or []),
            },
            trade_date=trade_date,
        )
        rows = _payload_rows(payload, self.response_rows_key)
        mapped_rows = [
            normalize_vendor_row(row, self.field_mapping, self.field_transforms)
            for row in rows
        ]
        daily_bars = [_row_to_daily_bar(row, trade_date) for row in mapped_rows]
        if symbols:
            wanted = set(symbols)
            daily_bars = [record for record in daily_bars if record.symbol in wanted]
        securities = _securities_from_rows(mapped_rows, symbols)
        exchanges = sorted({record.exchange for record in daily_bars})
        calendars = [
            CalendarRecord(exchange=exchange, trade_date=trade_date, is_open=bool(daily_bars))
            for exchange in exchanges
        ]
        self.last_duration_ms = (monotonic() - started) * 1000
        return DailyMarketBundle(
            provider=self.source_code,
            trade_date=trade_date,
            securities=securities,
            calendars=calendars,
            daily_bars=daily_bars,
        )

    def list_symbols(self, trade_date: str | None = None) -> list[str]:
        if self.fixture_daily_bar_path:
            return CsvProvider(
                security_master_path=self.fixture_security_master_path,
                trading_calendar_path=self.fixture_trading_calendar_path,
                daily_bar_path=self.fixture_daily_bar_path,
                provider_name=self.source_code,
            ).list_symbols(trade_date)
        raise QDataValidationError("vendor_http list_symbols requires fixture mode or a vendor-specific symbols endpoint")

    def is_trade_date(self, trade_date: str) -> bool:
        if self.fixture_daily_bar_path:
            return CsvProvider(
                security_master_path=self.fixture_security_master_path,
                trading_calendar_path=self.fixture_trading_calendar_path,
                daily_bar_path=self.fixture_daily_bar_path,
                provider_name=self.source_code,
            ).is_trade_date(trade_date)
        return parse_date(trade_date, "trade_date").weekday() < 5

    def _fetch_fixture_daily_market(self, trade_date: str, symbols: list[str] | None) -> DailyMarketBundle:
        provider = CsvProvider(
            security_master_path=self.fixture_security_master_path,
            trading_calendar_path=self.fixture_trading_calendar_path,
            daily_bar_path=self.fixture_daily_bar_path,
            provider_name=self.source_code,
            close_offset_bps=self.close_offset_bps,
        )
        started = monotonic()
        bundle = provider.fetch_daily_market(trade_date, symbols=symbols)
        self.last_duration_ms = (monotonic() - started) * 1000
        self.request_count += 1
        return bundle

    def _request_json(self, stage: str, params: dict[str, str], trade_date: str | None = None):
        last_error: Exception | None = None
        for attempt in range(self.retry_limit + 1):
            self._respect_rate_limit()
            request = self._build_request(params)
            try:
                self.request_count += 1
                response = self.request_func(request, self.timeout)
                raw = response.read()
                return json.loads(raw.decode("utf-8"))
            except Exception as exc:
                last_error = exc
                error_type, retryable = _classify_error(exc)
                self.error_events.append(
                    ProviderErrorEvent(
                        provider_name=self.source_code,
                        error_stage=stage,
                        error_type=error_type,
                        retryable=retryable,
                        error_message=str(exc),
                        trade_date=trade_date,
                        attempt=attempt,
                    )
                )
                if not retryable or attempt >= self.retry_limit:
                    break
                if self.retry_sleep_seconds:
                    sleep(self.retry_sleep_seconds)
        raise QDataProviderError(f"{self.source_code} request failed: {last_error}") from last_error

    def _build_request(self, params: dict[str, str]) -> Request:
        query = dict(params)
        headers = {"Accept": "application/json"}
        if self.auth_mode == "bearer":
            if not self.token:
                raise QDataValidationError("token is required for auth_mode='bearer'")
            headers["Authorization"] = f"Bearer {self.token}"
        elif self.auth_mode == "header":
            if not self.token:
                raise QDataValidationError("token is required for auth_mode='header'")
            headers[self.api_key_header] = self.token
        elif self.auth_mode == "query":
            if not self.token:
                raise QDataValidationError("token is required for auth_mode='query'")
            query[self.query_token_param] = self.token
        elif self.auth_mode == "basic":
            if not self.username or not self.password:
                raise QDataValidationError("username and password are required for auth_mode='basic'")
            encoded = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"

        url = urljoin(self.base_url.rstrip("/") + "/", self.daily_path.lstrip("/"))
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode({key: value for key, value in query.items() if value})}"
        return Request(url, headers=headers)

    def _respect_rate_limit(self) -> None:
        if not self.rate_limit_per_min:
            return
        now = monotonic()
        window_start = now - 60
        self._request_times = [timestamp for timestamp in self._request_times if timestamp >= window_start]
        if len(self._request_times) >= self.rate_limit_per_min:
            sleep(max(0, 60 - (now - self._request_times[0])))
        self._request_times.append(monotonic())


def _default_request(request: Request, timeout: float):
    return urlopen(request, timeout=timeout)


def _payload_rows(payload: Any, rows_key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get(rows_key)
        if rows is None and rows_key != "rows":
            rows = payload.get("rows")
        if isinstance(rows, list):
            return rows
    raise QDataProviderError("vendor response does not contain a list of rows")


def _row_to_daily_bar(row: dict[str, Any], default_trade_date: str) -> DailyBarRecord:
    try:
        raw_symbol = _first_present(row, "symbol", "ts_code", "code")
        if raw_symbol is None:
            raise KeyError("symbol")
        symbol = str(raw_symbol).upper()
        trade_date = str(_first_present(row, "trade_date", "date", default=default_trade_date))[:10]
        amount_value = _first_present(row, "amount", "turnover_amount")
        turnover_rate_value = _first_present(row, "turnover_rate", "turnover_ratio", "turnover_pct")
        if "turnover" in row:
            if amount_value is None and turnover_rate_value is None:
                amount_value = row.get("turnover")
            elif turnover_rate_value is None:
                turnover_rate_value = row.get("turnover")
        return DailyBarRecord(
            symbol=symbol,
            trade_date=trade_date,
            open=_float_or_none(row.get("open")),
            high=_float_or_none(row.get("high")),
            low=_float_or_none(row.get("low")),
            close=_float_or_none(row.get("close")),
            pre_close=_float_or_none(_first_present(row, "pre_close", "previous_close")),
            volume=_float_or_none(_first_present(row, "volume", "vol")),
            amount=_float_or_none(amount_value),
            vwap=_float_or_none(row.get("vwap")),
            turnover_rate=_float_or_none(turnover_rate_value),
            limit_up=_float_or_none(row.get("limit_up")),
            limit_down=_float_or_none(row.get("limit_down")),
            is_suspended=_bool(row.get("is_suspended", False)),
            factor_forward=_float_or_none(row.get("factor_forward")) or 1.0,
            factor_backward=_float_or_none(row.get("factor_backward")) or 1.0,
            ex_right_type=str(row.get("ex_right_type") or "none"),
        )
    except KeyError as exc:
        raise QDataProviderError(f"vendor row missing required field: {exc}") from exc


def _securities_from_rows(rows: list[dict[str, Any]], symbols: list[str] | None) -> list[SecurityRecord]:
    by_symbol: dict[str, SecurityRecord] = {}
    for row in rows:
        symbol = str(row.get("symbol") or row.get("ts_code") or row.get("code") or "").upper()
        if not symbol:
            continue
        by_symbol[symbol] = SecurityRecord(
            symbol=symbol,
            name=str(row.get("name") or symbol),
            asset_type=str(row.get("asset_type") or "stock"),
            currency=str(row.get("currency") or "CNY"),
            list_date=row.get("list_date") or None,
            delist_date=row.get("delist_date") or None,
            status=str(row.get("status") or "active"),
        )
    for symbol in symbols or []:
        by_symbol.setdefault(
            symbol,
            SecurityRecord(symbol=symbol, name=symbol, asset_type="stock", currency="CNY", status="active"),
        )
    return list(by_symbol.values())


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _first_present(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] is not None and row[key] != "":
            return row[key]
    return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y"}


def _classify_error(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, HTTPError):
        if exc.code == 401 or exc.code == 403:
            return "auth", False
        if exc.code == 429:
            return "rate_limit", True
        if 500 <= exc.code < 600:
            return "server", True
        return "client", False
    if isinstance(exc, TimeoutError):
        return "timeout", True
    if isinstance(exc, URLError):
        return "network", True
    if isinstance(exc, json.JSONDecodeError):
        return "schema", False
    return "unknown", False
