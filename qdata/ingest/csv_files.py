from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from qdata.backend_utils import parse_date
from qdata.exceptions import QDataValidationError
from qdata.ingest.models import (
    AdjustmentFactorRecord,
    CalendarRecord,
    DailyBarRecord,
    LimitPriceRecord,
    MinuteBarRecord,
    SecurityRecord,
    SuspensionRecord,
)


def read_security_master(path: str | Path) -> list[SecurityRecord]:
    rows = _read_csv(path)
    _require_columns(rows, {"symbol", "name"}, str(path))
    records = []
    for row in rows:
        symbol = _normalize_symbol(row["symbol"])
        list_date = _optional_date(row.get("list_date"), "list_date")
        delist_date = _optional_date(row.get("delist_date"), "delist_date")
        status_effective_date = _optional_date(
            row.get("status_effective_date"),
            "status_effective_date",
        )
        identifier_effective_date = _optional_date(
            row.get("identifier_effective_date"),
            "identifier_effective_date",
        )
        name_effective_date = _optional_date(
            row.get("name_effective_date"),
            "name_effective_date",
        )
        records.append(
            SecurityRecord(
                symbol=symbol,
                name=row["name"].strip(),
                asset_type=(row.get("asset_type") or "stock").strip(),
                currency=(row.get("currency") or "CNY").strip(),
                list_date=list_date,
                delist_date=delist_date,
                status=(row.get("status") or "").strip() or None,
                status_effective_date=status_effective_date,
                security_id=(
                    int(row["security_id"])
                    if row.get("security_id") not in (None, "")
                    else None
                ),
                identifier_effective_date=identifier_effective_date,
                name_effective_date=name_effective_date,
            )
        )
    return records


def read_trading_calendar(path: str | Path) -> list[CalendarRecord]:
    rows = _read_csv(path)
    _require_columns(rows, {"exchange", "trade_date", "is_open"}, str(path))
    records = []
    for row in rows:
        records.append(
            CalendarRecord(
                exchange=row["exchange"].strip(),
                trade_date=_required_date(row["trade_date"], "trade_date"),
                is_open=_parse_bool(row["is_open"]),
                session_type=(row.get("session_type") or "full_day").strip(),
                pretrade_date=_optional_date(row.get("pretrade_date"), "pretrade_date"),
                next_trade_date=_optional_date(row.get("next_trade_date"), "next_trade_date"),
                open_time=(row.get("open_time") or "09:30").strip() or None,
                close_time=(row.get("close_time") or "15:00").strip() or None,
            )
        )
    return records


def read_daily_bars(path: str | Path) -> list[DailyBarRecord]:
    rows = _read_csv(path)
    _require_columns(
        rows,
        {"symbol", "trade_date", "open", "high", "low", "close", "pre_close", "volume", "amount"},
        str(path),
    )
    records = []
    for row in rows:
        amount = _optional_float(row.get("amount"), "amount")
        volume = _optional_float(row.get("volume"), "volume")
        vwap = _optional_float(row.get("vwap"), "vwap")
        if vwap is None and amount is not None and volume not in {None, 0}:
            vwap = amount / volume
        records.append(
            DailyBarRecord(
                symbol=_normalize_symbol(row["symbol"]),
                trade_date=_required_date(row["trade_date"], "trade_date"),
                open=_optional_float(row.get("open"), "open"),
                high=_optional_float(row.get("high"), "high"),
                low=_optional_float(row.get("low"), "low"),
                close=_optional_float(row.get("close"), "close"),
                pre_close=_optional_float(row.get("pre_close"), "pre_close"),
                volume=volume,
                amount=amount,
                vwap=vwap,
                turnover_rate=_optional_float(row.get("turnover_rate"), "turnover_rate"),
                limit_up=_optional_float(row.get("limit_up"), "limit_up"),
                limit_down=_optional_float(row.get("limit_down"), "limit_down"),
                is_suspended=_parse_bool(row.get("is_suspended", "false")),
                factor_forward=_optional_float(row.get("factor_forward"), "factor_forward", default=1.0),
                factor_backward=_optional_float(row.get("factor_backward"), "factor_backward", default=1.0),
                ex_right_type=(row.get("ex_right_type") or "none").strip(),
            )
        )
    return records


def read_adjustment_factors(path: str | Path) -> list[AdjustmentFactorRecord]:
    rows = _read_csv(path)
    _require_columns(rows, {"symbol", "trade_date", "factor_forward", "factor_backward"}, str(path))
    return [
        AdjustmentFactorRecord(
            symbol=_normalize_symbol(row["symbol"]),
            trade_date=_required_date(row["trade_date"], "trade_date"),
            factor_forward=_optional_float(row.get("factor_forward"), "factor_forward"),
            factor_backward=_optional_float(row.get("factor_backward"), "factor_backward"),
            ex_right_type=(row.get("ex_right_type") or "none").strip(),
        )
        for row in rows
    ]


def read_limit_prices(path: str | Path) -> list[LimitPriceRecord]:
    rows = _read_csv(path)
    _require_columns(rows, {"symbol", "trade_date", "limit_up", "limit_down"}, str(path))
    return [
        LimitPriceRecord(
            symbol=_normalize_symbol(row["symbol"]),
            trade_date=_required_date(row["trade_date"], "trade_date"),
            limit_up=_optional_float(row.get("limit_up"), "limit_up"),
            limit_down=_optional_float(row.get("limit_down"), "limit_down"),
            limit_rule=(row.get("limit_rule") or "unknown").strip(),
            is_st=_parse_bool(row.get("is_st", "false")),
            is_new_listing=_parse_bool(row.get("is_new_listing", "false")),
        )
        for row in rows
    ]


def read_suspensions(path: str | Path) -> list[SuspensionRecord]:
    rows = _read_csv(path)
    _require_columns(rows, {"symbol", "start_time"}, str(path))
    return [
        SuspensionRecord(
            symbol=_normalize_symbol(row["symbol"]),
            start_time=_required_datetime(row["start_time"], "start_time"),
            end_time=_optional_datetime(row.get("end_time"), "end_time"),
            suspension_type=(row.get("suspension_type") or "full_day").strip(),
            reason=(row.get("reason") or "").strip() or None,
        )
        for row in rows
    ]


def read_minute_bars(path: str | Path) -> list[MinuteBarRecord]:
    rows = _read_csv(path)
    _require_columns(
        rows,
        {"symbol", "trade_date", "bar_time", "open", "high", "low", "close", "volume", "amount"},
        str(path),
    )
    records = []
    for row in rows:
        amount = _optional_float(row.get("amount"), "amount")
        volume = _optional_float(row.get("volume"), "volume")
        vwap = _optional_float(row.get("vwap"), "vwap")
        if vwap is None and amount is not None and volume not in {None, 0}:
            vwap = amount / volume
        records.append(
            MinuteBarRecord(
                symbol=_normalize_symbol(row["symbol"]),
                trade_date=_required_date(row["trade_date"], "trade_date"),
                bar_time=_required_datetime(row["bar_time"], "bar_time"),
                open=_optional_float(row.get("open"), "open"),
                high=_optional_float(row.get("high"), "high"),
                low=_optional_float(row.get("low"), "low"),
                close=_optional_float(row.get("close"), "close"),
                volume=volume,
                amount=amount,
                vwap=vwap,
            )
        )
    return records


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise QDataValidationError(f"CSV file has no header: {path}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def _require_columns(rows: list[dict[str, Any]], required: set[str], label: str) -> None:
    if not rows:
        raise QDataValidationError(f"CSV file has no data rows: {label}")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise QDataValidationError(f"CSV file {label} missing required columns: {missing}")


def _normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    parts = symbol.split(".")
    if len(parts) != 2 or not parts[0] or parts[1] not in {"SH", "SZ", "BJ"}:
        raise QDataValidationError(f"Invalid symbol format: {value}")
    return symbol


def _required_date(value: str, field_name: str) -> str:
    parse_date(value, field_name)
    return value


def _optional_date(value: str | None, field_name: str) -> str | None:
    if not value:
        return None
    return _required_date(value, field_name)


def _required_datetime(value: str, field_name: str) -> str:
    if len(value) == 10:
        parse_date(value, field_name)
        return f"{value} 00:00:00"
    try:
        from datetime import datetime

        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QDataValidationError(f"{field_name} must be ISO datetime or YYYY-MM-DD") from exc
    return value


def _optional_datetime(value: str | None, field_name: str) -> str | None:
    if not value:
        return None
    return _required_datetime(value, field_name)


def _optional_float(value: str | None, field_name: str, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise QDataValidationError(f"{field_name} must be numeric") from exc


def _parse_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    normalized = (value or "").strip().lower()
    if normalized in {"1", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", ""}:
        return False
    raise QDataValidationError(f"Invalid boolean value: {value}")
