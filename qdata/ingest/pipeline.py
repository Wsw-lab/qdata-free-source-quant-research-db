from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from qdata.exceptions import QDataValidationError
from qdata.ingest.csv_files import read_daily_bars, read_security_master, read_trading_calendar
from qdata.ingest.models import CalendarRecord, DailyBarRecord, IngestSummary, SecurityRecord
from qdata.ingest.quality import check_daily_bundle_quality
from qdata.ingest.raw_store import store_raw_files


class DailyBundleLoader(Protocol):
    def load_security_master(self, records: list[SecurityRecord]) -> None:
        ...

    def load_trading_calendar(self, records: list[CalendarRecord]) -> None:
        ...

    def load_daily_bars(self, records: list[DailyBarRecord]) -> None:
        ...

    def write_quality_report(
        self,
        report,
        check_date: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        ...


def ingest_daily_bundle(
    security_master_path: str | Path,
    trading_calendar_path: str | Path,
    daily_bar_path: str | Path,
    loader: DailyBundleLoader,
    raw_root: str | Path = "raw",
    source_name: str = "local_csv",
    strict_quality: bool = True,
    store_raw: bool = True,
    expected_symbols: list[str] | None = None,
    min_completeness: float = 1.0,
    quality_context: dict[str, Any] | None = None,
) -> IngestSummary:
    securities = read_security_master(security_master_path)
    calendars = read_trading_calendar(trading_calendar_path)
    daily_bars = read_daily_bars(daily_bar_path)
    quality_report = check_daily_bundle_quality(
        securities,
        calendars,
        daily_bars,
        expected_symbols=expected_symbols,
        min_completeness=min_completeness,
    )
    if strict_quality and not quality_report.passed:
        check_date = daily_bars[0].trade_date if daily_bars else calendars[0].trade_date if calendars else None
        loader.write_quality_report(quality_report, check_date=check_date, context=quality_context)
        raise QDataValidationError(f"quality check failed with {quality_report.error_count} blocking issue(s)")

    raw_paths = []
    if store_raw:
        raw_paths = store_raw_files(
            {
                "security_master": security_master_path,
                "trading_calendar": trading_calendar_path,
                "daily_bar": daily_bar_path,
            },
            raw_root=raw_root,
            source_name=source_name,
        )

    loader.load_security_master(securities)
    loader.load_trading_calendar(calendars)
    loader.load_daily_bars(daily_bars)
    check_date = daily_bars[0].trade_date if daily_bars else None
    loader.write_quality_report(quality_report, check_date=check_date, context=quality_context)

    return IngestSummary(
        security_count=len(securities),
        calendar_count=len(calendars),
        daily_bar_count=len(daily_bars),
        raw_paths=raw_paths,
        quality_report=quality_report,
    )
