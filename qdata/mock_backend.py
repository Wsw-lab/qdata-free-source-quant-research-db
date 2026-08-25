from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

from qdata.exceptions import QDataNotFoundError, QDataValidationError


class MockBackend:
    """Small in-memory backend that mirrors the MVP API contract."""

    def __init__(self) -> None:
        self.securities = [
            {
                "security_id": 1000001,
                "symbol": "600519.SH",
                "asset_type": "stock",
                "exchange": "SH",
                "name": "贵州茅台",
                "list_date": "2001-08-27",
                "delist_date": None,
                "status": "active",
            },
            {
                "security_id": 1000002,
                "symbol": "000001.SZ",
                "asset_type": "stock",
                "exchange": "SZ",
                "name": "平安银行",
                "list_date": "1991-04-03",
                "delist_date": None,
                "status": "active",
            },
            {
                "security_id": 1000003,
                "symbol": "300750.SZ",
                "asset_type": "stock",
                "exchange": "SZ",
                "name": "宁德时代",
                "list_date": "2018-06-11",
                "delist_date": None,
                "status": "active",
            },
        ]
        self._by_symbol = {row["symbol"]: row for row in self.securities}
        self._by_security_id = {row["security_id"]: row for row in self.securities}

        self.daily_bars = [
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "trade_date": "2024-01-02",
                "open": 1680.00,
                "high": 1702.00,
                "low": 1670.00,
                "close": 1698.00,
                "pre_close": 1675.00,
                "volume": 12500000.0,
                "amount": 21000000000.0,
                "vwap": 1680.00,
                "turnover_rate": 0.0135,
                "limit_up": 1842.50,
                "limit_down": 1507.50,
                "is_suspended": False,
            },
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "trade_date": "2024-01-03",
                "open": 1696.00,
                "high": 1710.00,
                "low": 1688.00,
                "close": 1705.00,
                "pre_close": 1698.00,
                "volume": 11200000.0,
                "amount": 19096000000.0,
                "vwap": 1705.00,
                "turnover_rate": 0.0121,
                "limit_up": 1867.80,
                "limit_down": 1528.20,
                "is_suspended": False,
            },
            {
                "symbol": "000001.SZ",
                "security_id": 1000002,
                "trade_date": "2024-01-02",
                "open": 9.45,
                "high": 9.62,
                "low": 9.38,
                "close": 9.58,
                "pre_close": 9.44,
                "volume": 86000000.0,
                "amount": 820000000.0,
                "vwap": 9.53,
                "turnover_rate": 0.0044,
                "limit_up": 10.38,
                "limit_down": 8.50,
                "is_suspended": False,
            },
            {
                "symbol": "000001.SZ",
                "security_id": 1000002,
                "trade_date": "2024-01-03",
                "open": 9.56,
                "high": 9.72,
                "low": 9.50,
                "close": 9.66,
                "pre_close": 9.58,
                "volume": 78000000.0,
                "amount": 752000000.0,
                "vwap": 9.64,
                "turnover_rate": 0.0040,
                "limit_up": 10.54,
                "limit_down": 8.62,
                "is_suspended": False,
            },
            {
                "symbol": "300750.SZ",
                "security_id": 1000003,
                "trade_date": "2024-01-02",
                "open": 158.20,
                "high": 162.50,
                "low": 157.30,
                "close": 161.80,
                "pre_close": 157.90,
                "volume": 42000000.0,
                "amount": 6750000000.0,
                "vwap": 160.71,
                "turnover_rate": 0.0128,
                "limit_up": 189.48,
                "limit_down": 126.32,
                "is_suspended": False,
            },
        ]

        self.minute_bars = [
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "trade_date": "2024-01-02",
                "bar_time": "2024-01-02T09:31:00+08:00",
                "open": 1680.00,
                "high": 1685.00,
                "low": 1679.50,
                "close": 1684.00,
                "volume": 120000.0,
                "amount": 202080000.0,
                "vwap": 1684.00,
            },
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "trade_date": "2024-01-02",
                "bar_time": "2024-01-02T09:32:00+08:00",
                "open": 1684.00,
                "high": 1686.00,
                "low": 1681.00,
                "close": 1682.00,
                "volume": 98000.0,
                "amount": 164836000.0,
                "vwap": 1682.00,
            },
        ]

        self.adjustment_factors = [
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "trade_date": "2024-01-02",
                "factor_forward": 0.5321,
                "factor_backward": 12.8723,
                "ex_right_type": "none",
            },
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "trade_date": "2024-01-03",
                "factor_forward": 0.5321,
                "factor_backward": 12.8723,
                "ex_right_type": "none",
            },
            {
                "symbol": "000001.SZ",
                "security_id": 1000002,
                "trade_date": "2024-01-02",
                "factor_forward": 1.1234,
                "factor_backward": 5.0312,
                "ex_right_type": "none",
            },
            {
                "symbol": "000001.SZ",
                "security_id": 1000002,
                "trade_date": "2024-01-03",
                "factor_forward": 1.1234,
                "factor_backward": 5.0312,
                "ex_right_type": "none",
            },
            {
                "symbol": "300750.SZ",
                "security_id": 1000003,
                "trade_date": "2024-01-02",
                "factor_forward": 0.8842,
                "factor_backward": 1.7331,
                "ex_right_type": "none",
            },
        ]

        self.financials = [
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "report_period": "2021-03-31",
                "field_name": "revenue",
                "field_value": 27271000000.0,
                "period_type": "ttm",
                "announce_time": "2021-04-27T19:30:00+08:00",
                "ingest_time": "2021-04-27T19:31:00+08:00",
                "revision_id": 1,
                "is_restated": False,
            },
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "report_period": "2021-03-31",
                "field_name": "net_profit_parent",
                "field_value": 13954000000.0,
                "period_type": "ttm",
                "announce_time": "2021-04-27T19:30:00+08:00",
                "ingest_time": "2021-04-27T19:31:00+08:00",
                "revision_id": 1,
                "is_restated": False,
            },
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "report_period": "2021-03-31",
                "field_name": "roe_ttm",
                "field_value": 0.283,
                "period_type": "ttm",
                "announce_time": "2021-04-27T19:30:00+08:00",
                "ingest_time": "2021-04-27T19:31:00+08:00",
                "revision_id": 1,
                "is_restated": False,
            },
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "report_period": "2021-06-30",
                "field_name": "revenue",
                "field_value": 50722000000.0,
                "period_type": "ttm",
                "announce_time": "2021-08-02T19:30:00+08:00",
                "ingest_time": "2021-08-02T19:31:00+08:00",
                "revision_id": 1,
                "is_restated": False,
            },
        ]

        self.index_members = [
            {
                "index_code": "000300.SH",
                "symbol": "600519.SH",
                "security_id": 1000001,
                "effective_date": "2023-12-11",
                "end_date": None,
                "weight": 0.0612,
            },
            {
                "index_code": "000300.SH",
                "symbol": "000001.SZ",
                "security_id": 1000002,
                "effective_date": "2023-12-11",
                "end_date": None,
                "weight": 0.0048,
            },
            {
                "index_code": "000852.SH",
                "symbol": "300750.SZ",
                "security_id": 1000003,
                "effective_date": "2023-12-11",
                "end_date": None,
                "weight": 0.0081,
            },
        ]

        self.industry_memberships = [
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "industry_system": "sw",
                "level": 1,
                "industry_code": "801120",
                "industry_name": "食品饮料",
                "effective_date": "2021-12-13",
                "end_date": None,
            },
            {
                "symbol": "000001.SZ",
                "security_id": 1000002,
                "industry_system": "sw",
                "level": 1,
                "industry_code": "801780",
                "industry_name": "银行",
                "effective_date": "2021-12-13",
                "end_date": None,
            },
            {
                "symbol": "300750.SZ",
                "security_id": 1000003,
                "industry_system": "sw",
                "level": 1,
                "industry_code": "801730",
                "industry_name": "电力设备",
                "effective_date": "2021-12-13",
                "end_date": None,
            },
        ]

        self.factor_values = [
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "trade_date": "2024-01-02",
                "factor_code": "momentum_20d",
                "factor_value": 0.032,
                "factor_version": "published",
                "quality_flag": "normal",
            },
            {
                "symbol": "000001.SZ",
                "security_id": 1000002,
                "trade_date": "2024-01-02",
                "factor_code": "momentum_20d",
                "factor_value": -0.011,
                "factor_version": "published",
                "quality_flag": "normal",
            },
            {
                "symbol": "600519.SH",
                "security_id": 1000001,
                "trade_date": "2024-01-02",
                "factor_code": "roe_ttm",
                "factor_value": 0.283,
                "factor_version": "published",
                "quality_flag": "normal",
            },
            {
                "symbol": "000001.SZ",
                "security_id": 1000002,
                "trade_date": "2024-01-02",
                "factor_code": "roe_ttm",
                "factor_value": 0.104,
                "factor_version": "published",
                "quality_flag": "normal",
            },
        ]

        self.dataset_health = [
            {
                "dataset_code": "daily_bar",
                "check_date": "2024-01-02",
                "check_name": "daily_bar_completeness",
                "status": "pass",
                "severity": "info",
                "metric_value": 1.0,
                "threshold_value": 0.999,
                "affected_rows": 0,
            },
            {
                "dataset_code": "minute_bar",
                "check_date": "2024-01-02",
                "check_name": "minute_bar_gap_check",
                "status": "warning",
                "severity": "medium",
                "metric_value": 0.995,
                "threshold_value": 0.999,
                "affected_rows": 2,
            },
        ]

    def get_security_master(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        asset_types: list[str] | None,
        exchanges: list[str] | None,
        asof_date: str | None,
        include_delisted: bool,
        fields: list[str] | None,
    ) -> dict[str, Any]:
        rows = list(self.securities)
        if symbols:
            rows = [row for row in rows if row["symbol"] in set(symbols)]
        if security_ids:
            rows = [row for row in rows if row["security_id"] in set(security_ids)]
        if asset_types:
            rows = [row for row in rows if row["asset_type"] in set(asset_types)]
        if exchanges:
            rows = [row for row in rows if row["exchange"] in set(exchanges)]
        if asof_date:
            self._parse_date(asof_date, "asof_date")
            rows = [
                {
                    **row,
                    "status": (
                        "active"
                        if row["status"] == "delisted"
                        and row["delist_date"] is not None
                        and asof_date < row["delist_date"]
                        else row["status"]
                    ),
                }
                for row in rows
                if row["list_date"] <= asof_date and (row["delist_date"] is None or row["delist_date"] >= asof_date)
            ]
        if not include_delisted:
            rows = [row for row in rows if row["status"] != "delisted"]
        return self._response(self._project(rows, fields), ["security_master:mock-v1"], "asof" if asof_date else "latest")

    def get_trading_calendar(
        self,
        exchange: str,
        start_date: str,
        end_date: str,
        open_only: bool,
    ) -> dict[str, Any]:
        start, end = self._date_range(start_date, end_date)
        rows = []
        current = start
        open_days = [day for day in self._iter_dates(start, end) if day.weekday() < 5]
        while current <= end:
            is_open = current.weekday() < 5
            if not open_only or is_open:
                previous_open = max((day for day in open_days if day < current), default=None)
                next_open = min((day for day in open_days if day > current), default=None)
                rows.append(
                    {
                        "exchange": exchange,
                        "trade_date": current.isoformat(),
                        "is_open": is_open,
                        "session_type": "full_day" if is_open else "closed",
                        "pretrade_date": previous_open.isoformat() if previous_open else None,
                        "next_trade_date": next_open.isoformat() if next_open else None,
                    }
                )
            current += timedelta(days=1)
        return self._response(rows, ["trading_calendar:mock-v1"], "latest")

    def get_price(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        universe: str | None,
        start_date: str | None,
        end_date: str | None,
        frequency: str,
        adjust: str,
        fields: list[str] | None,
        query_mode: str,
        asof_time: str | None,
        data_version: str | None,
    ) -> dict[str, Any]:
        if not start_date or not end_date:
            raise QDataValidationError("start_date and end_date are required")
        self._date_range(start_date, end_date)
        self._validate_enum(frequency, {"1d", "1m"}, "frequency")
        self._validate_enum(adjust, {"none", "forward", "backward"}, "adjust")
        self._validate_enum(query_mode, {"latest", "asof", "vintage"}, "query_mode")

        selected_symbols = self._resolve_symbols(symbols, security_ids, universe)
        source_rows = self.daily_bars if frequency == "1d" else self.minute_bars
        rows = [
            dict(row)
            for row in source_rows
            if row["symbol"] in selected_symbols and start_date <= row["trade_date"] <= end_date
        ]

        if adjust != "none":
            rows = [self._apply_adjustment(row, adjust) for row in rows]

        default_fields = ["open", "high", "low", "close", "volume", "amount"]
        requested_fields = fields or default_fields
        base_fields = ["symbol", "security_id", "trade_date"]
        if frequency == "1m":
            base_fields.append("bar_time")
        rows = self._project(rows, base_fields + requested_fields)
        return self._response(rows, [f"{frequency}_bar:mock-v1"], query_mode, asof_time, data_version)

    def get_adjustment_factor(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        start_date: str | None,
        end_date: str | None,
        factor_type: str,
        query_mode: str,
    ) -> dict[str, Any]:
        if query_mode != "latest":
            raise QDataValidationError(
                "get_adjustment_factor only supports query_mode='latest'; its public "
                "signature does not expose a knowledge cutoff or immutable data version"
            )
        if not start_date or not end_date:
            raise QDataValidationError("start_date and end_date are required")
        self._date_range(start_date, end_date)
        self._validate_enum(factor_type, {"forward", "backward", "both"}, "factor_type")
        selected_symbols = self._resolve_symbols(symbols, security_ids, None)

        fields = ["symbol", "security_id", "trade_date", "ex_right_type"]
        if factor_type in {"forward", "both"}:
            fields.append("factor_forward")
        if factor_type in {"backward", "both"}:
            fields.append("factor_backward")

        rows = [
            row
            for row in self.adjustment_factors
            if row["symbol"] in selected_symbols and start_date <= row["trade_date"] <= end_date
        ]
        return self._response(self._project(rows, fields), ["adjustment_factor:mock-v1"], query_mode)

    def get_trading_constraints(
        self,
        symbols: list[str] | None,
        universe: str | None,
        start_date: str | None,
        end_date: str | None,
        fields: list[str] | None,
    ) -> dict[str, Any]:
        if not start_date or not end_date:
            raise QDataValidationError("start_date and end_date are required")
        self._date_range(start_date, end_date)
        selected_symbols = self._resolve_symbols(symbols, None, universe)
        default_fields = [
            "is_suspended",
            "is_st",
            "limit_up",
            "limit_down",
            "can_buy",
            "can_sell",
            "list_days",
            "is_new_listing",
            "is_delisting_period",
        ]
        requested_fields = fields or default_fields

        rows = []
        for bar in self.daily_bars:
            if bar["symbol"] not in selected_symbols or not (start_date <= bar["trade_date"] <= end_date):
                continue
            security = self._by_symbol[bar["symbol"]]
            list_days = (self._parse_date(bar["trade_date"], "trade_date") - self._parse_date(security["list_date"], "list_date")).days
            row = {
                "symbol": bar["symbol"],
                "security_id": bar["security_id"],
                "trade_date": bar["trade_date"],
                "is_suspended": bar["is_suspended"],
                "is_st": False,
                "limit_up": bar["limit_up"],
                "limit_down": bar["limit_down"],
                "can_buy": not bar["is_suspended"],
                "can_sell": not bar["is_suspended"],
                "list_days": list_days,
                "is_new_listing": list_days < 30,
                "is_delisting_period": False,
            }
            rows.append(row)
        return self._response(self._project(rows, ["symbol", "security_id", "trade_date"] + requested_fields), ["trading_constraints:mock-v1"], "latest")

    def get_tradable_universe(
        self,
        asof_date: str,
        symbols: list[str] | None,
        universe: str | None,
        exclude_st: bool,
        exclude_suspended: bool,
        exclude_new_listing: bool,
        exclude_delisting_period: bool,
        min_list_days: int,
    ) -> dict[str, Any]:
        self._parse_date(asof_date, "asof_date")
        selected_symbols = self._resolve_symbols(symbols, None, universe) if (symbols or universe) else [row["symbol"] for row in self.securities]
        constraints = {
            row["symbol"]: row
            for row in self.get_trading_constraints(
                symbols=selected_symbols,
                universe=None,
                start_date=asof_date,
                end_date=asof_date,
                fields=None,
            )["data"]
        }
        rows = []
        for symbol in selected_symbols:
            constraint = constraints.get(symbol)
            if not constraint:
                continue
            if exclude_st and constraint.get("is_st"):
                continue
            if exclude_suspended and constraint.get("is_suspended"):
                continue
            if exclude_new_listing and constraint.get("is_new_listing"):
                continue
            if exclude_delisting_period and constraint.get("is_delisting_period"):
                continue
            if constraint.get("list_days", 0) < min_list_days:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "security_id": constraint["security_id"],
                    "asof_date": asof_date,
                    "can_buy": constraint["can_buy"],
                    "can_sell": constraint["can_sell"],
                    "list_days": constraint["list_days"],
                    "is_st": constraint["is_st"],
                    "is_suspended": constraint["is_suspended"],
                    "is_new_listing": constraint["is_new_listing"],
                    "is_delisting_period": constraint["is_delisting_period"],
                }
            )
        return self._response(rows, ["tradable_universe:mock-v1"], "asof")

    def get_fundamental_asof(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        fields: list[str] | None,
        asof_date: str | None,
        report_period: str | None,
        period_type: str,
        include_revision_info: bool,
    ) -> dict[str, Any]:
        if not asof_date:
            raise QDataValidationError("asof_date is required")
        if not fields:
            raise QDataValidationError("fields are required")
        self._parse_date(asof_date, "asof_date")

        selected_symbols = self._resolve_symbols(symbols, security_ids, None)
        rows = []
        for symbol in selected_symbols:
            for field in fields:
                candidates = [
                    row
                    for row in self.financials
                    if row["symbol"] == symbol
                    and row["field_name"] == field
                    and row["period_type"] == period_type
                    and row["announce_time"][:10] <= asof_date
                    and (report_period is None or row["report_period"] == report_period)
                ]
                if not candidates:
                    continue
                selected = max(candidates, key=lambda row: (row["report_period"], row["announce_time"], row["revision_id"]))
                result = {
                    "symbol": selected["symbol"],
                    "security_id": selected["security_id"],
                    "asof_date": asof_date,
                    "report_period": selected["report_period"],
                    "field_name": selected["field_name"],
                    "field_value": selected["field_value"],
                }
                if include_revision_info:
                    result.update(
                        {
                            "announce_time": selected["announce_time"],
                            "ingest_time": selected["ingest_time"],
                            "revision_id": selected["revision_id"],
                            "is_restated": selected["is_restated"],
                        }
                    )
                rows.append(result)
        return self._response(rows, ["financial_pit:mock-v1"], "asof")

    def get_index_members_asof(
        self,
        index_code: str,
        asof_date: str,
        fields: list[str] | None,
        include_weight: bool,
    ) -> dict[str, Any]:
        self._parse_date(asof_date, "asof_date")
        default_fields = ["index_code", "symbol", "security_id", "effective_date", "end_date"]
        if include_weight:
            default_fields.append("weight")
        rows = [
            row
            for row in self.index_members
            if row["index_code"] == index_code
            and row["effective_date"] <= asof_date
            and (row["end_date"] is None or row["end_date"] >= asof_date)
        ]
        return self._response(self._project(rows, fields or default_fields), ["index_member_pit:mock-v1"], "asof")

    def get_industry_asof(
        self,
        symbols: list[str] | None,
        universe: str | None,
        industry_system: str,
        level: int,
        asof_date: str | None,
    ) -> dict[str, Any]:
        if not asof_date:
            raise QDataValidationError("asof_date is required")
        self._parse_date(asof_date, "asof_date")
        selected_symbols = self._resolve_symbols(symbols, None, universe)
        rows = [
            row
            for row in self.industry_memberships
            if row["symbol"] in selected_symbols
            and row["industry_system"] == industry_system
            and row["level"] == level
            and row["effective_date"] <= asof_date
            and (row["end_date"] is None or row["end_date"] >= asof_date)
        ]
        return self._response(rows, ["industry_membership_pit:mock-v1"], "asof")

    def get_universe(
        self,
        universe: str,
        asof_date: str,
        filters: dict[str, Any],
        include_weight: bool,
    ) -> dict[str, Any]:
        self._parse_date(asof_date, "asof_date")
        symbols = self._universe_symbols(universe, asof_date)
        rows = []
        constraints = {
            row["symbol"]: row
            for row in self.get_trading_constraints(
                symbols=symbols,
                universe=None,
                start_date=asof_date,
                end_date=asof_date,
                fields=None,
            )["data"]
        }
        weights = {row["symbol"]: row.get("weight") for row in self.index_members}
        for symbol in symbols:
            security = self._by_symbol[symbol]
            constraint = constraints.get(symbol, {})
            if filters.get("exclude_st") and constraint.get("is_st"):
                continue
            if filters.get("exclude_suspended") and constraint.get("is_suspended"):
                continue
            if filters.get("exclude_delisting_period") and constraint.get("is_delisting_period"):
                continue
            if filters.get("exclude_new_listing") and constraint.get("is_new_listing"):
                continue
            if constraint.get("list_days", 10_000) < filters.get("min_list_days", 0):
                continue
            row = {
                "universe": universe,
                "symbol": symbol,
                "security_id": security["security_id"],
                "asof_date": asof_date,
            }
            if include_weight:
                row["weight"] = weights.get(symbol)
            rows.append(row)
        return self._response(rows, ["universe:mock-v1"], "asof")

    def get_factor(
        self,
        factors: list[str],
        symbols: list[str] | None,
        universe: str | None,
        start_date: str | None,
        end_date: str | None,
        factor_version: str,
        query_mode: str,
        format: str,
    ) -> dict[str, Any]:
        if query_mode != "latest":
            raise QDataValidationError(
                "get_factor only supports query_mode='latest'; its public signature "
                "does not expose a knowledge cutoff or immutable data version"
            )
        if not start_date or not end_date:
            raise QDataValidationError("start_date and end_date are required")
        self._date_range(start_date, end_date)
        self._validate_enum(format, {"long", "wide"}, "format")
        selected_symbols = self._resolve_symbols(symbols, None, universe)
        rows = [
            row
            for row in self.factor_values
            if row["symbol"] in selected_symbols
            and row["factor_code"] in set(factors)
            and row["factor_version"] == factor_version
            and start_date <= row["trade_date"] <= end_date
        ]
        if format == "wide":
            rows = self._factor_rows_to_wide(rows, factors)
        return self._response(rows, ["factor_value_daily:mock-v1"], query_mode)

    def get_dataset_health(
        self,
        dataset_code: str,
        start_date: str,
        end_date: str,
        severity: str | None,
    ) -> dict[str, Any]:
        self._date_range(start_date, end_date)
        rows = [
            row
            for row in self.dataset_health
            if row["dataset_code"] == dataset_code
            and start_date <= row["check_date"] <= end_date
            and (severity is None or row["severity"] == severity)
        ]
        return self._response(rows, [f"{dataset_code}:health:mock-v1"], "latest")

    def _resolve_symbols(
        self,
        symbols: list[str] | None,
        security_ids: list[int] | None,
        universe: str | None,
    ) -> set[str]:
        resolved: set[str] = set()
        if symbols:
            unknown = sorted(set(symbols) - set(self._by_symbol))
            if unknown:
                raise QDataNotFoundError(f"Unknown symbols: {unknown}")
            resolved.update(symbols)
        if security_ids:
            unknown_ids = sorted(set(security_ids) - set(self._by_security_id))
            if unknown_ids:
                raise QDataNotFoundError(f"Unknown security_ids: {unknown_ids}")
            resolved.update(self._by_security_id[security_id]["symbol"] for security_id in security_ids)
        if universe:
            resolved.update(self._universe_symbols(universe, None))
        if not resolved:
            raise QDataValidationError("symbols, security_ids, or universe is required")
        return resolved

    def _universe_symbols(self, universe: str, asof_date: str | None) -> list[str]:
        if universe in {"hs300", "000300.SH"}:
            rows = self.index_members
            if asof_date:
                rows = [
                    row
                    for row in rows
                    if row["index_code"] == "000300.SH"
                    and row["effective_date"] <= asof_date
                    and (row["end_date"] is None or row["end_date"] >= asof_date)
                ]
            else:
                rows = [row for row in rows if row["index_code"] == "000300.SH"]
            return [row["symbol"] for row in rows]
        if universe in {"zz800", "all_a"}:
            return [row["symbol"] for row in self.securities if row["asset_type"] == "stock"]
        raise QDataNotFoundError(f"Unknown universe: {universe}")

    def _apply_adjustment(self, row: dict[str, Any], adjust: str) -> dict[str, Any]:
        adjusted = dict(row)
        factor = next(
            (
                item
                for item in self.adjustment_factors
                if item["symbol"] == row["symbol"] and item["trade_date"] == row["trade_date"]
            ),
            None,
        )
        if factor is None:
            return adjusted
        factor_value = factor["factor_forward"] if adjust == "forward" else factor["factor_backward"]
        for field in ("open", "high", "low", "close", "pre_close", "vwap", "limit_up", "limit_down"):
            if field in adjusted and adjusted[field] is not None:
                adjusted[field] = round(adjusted[field] * factor_value, 6)
        return adjusted

    def _factor_rows_to_wide(self, rows: list[dict[str, Any]], factors: list[str]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row["symbol"], row["trade_date"])
            item = grouped.setdefault(
                key,
                {
                    "symbol": row["symbol"],
                    "security_id": row["security_id"],
                    "trade_date": row["trade_date"],
                },
            )
            item[row["factor_code"]] = row["factor_value"]
        for item in grouped.values():
            for factor in factors:
                item.setdefault(factor, None)
        return list(grouped.values())

    def _response(
        self,
        rows: list[dict[str, Any]],
        data_versions: list[str],
        query_mode: str,
        asof_time: str | None = None,
        data_version: str | None = None,
    ) -> dict[str, Any]:
        return {
            "request_id": f"req_{uuid4().hex[:12]}",
            "status": "success",
            "data": rows,
            "meta": {
                "query_mode": query_mode,
                "data_versions": data_versions,
                "row_count": len(rows),
                "asof_time": asof_time,
                "data_version": data_version,
            },
            "errors": [],
        }

    @staticmethod
    def _project(rows: list[dict[str, Any]], fields: list[str] | None) -> list[dict[str, Any]]:
        if not fields:
            return [dict(row) for row in rows]
        seen: set[str] = set()
        ordered_fields = [field for field in fields if not (field in seen or seen.add(field))]
        return [{field: row.get(field) for field in ordered_fields} for row in rows]

    @staticmethod
    def _date_range(start_date: str, end_date: str) -> tuple[date, date]:
        start = MockBackend._parse_date(start_date, "start_date")
        end = MockBackend._parse_date(end_date, "end_date")
        if start > end:
            raise QDataValidationError("start_date must be less than or equal to end_date")
        return start, end

    @staticmethod
    def _iter_dates(start: date, end: date) -> list[date]:
        days = []
        current = start
        while current <= end:
            days.append(current)
            current += timedelta(days=1)
        return days

    @staticmethod
    def _parse_date(value: str, field_name: str) -> date:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise QDataValidationError(f"{field_name} must use YYYY-MM-DD format") from exc

    @staticmethod
    def _validate_enum(value: str, allowed: set[str], field_name: str) -> None:
        if value not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise QDataValidationError(f"{field_name} must be one of: {allowed_text}")
