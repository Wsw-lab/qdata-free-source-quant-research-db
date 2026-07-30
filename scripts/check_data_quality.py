#!/usr/bin/env python3
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.ingest import check_daily_bundle_quality, read_daily_bars, read_security_master, read_trading_calendar


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local CSV quality before daily-bar ingestion.")
    parser.add_argument("--security-master", default="raw/samples/security_master.csv")
    parser.add_argument("--calendar", default="raw/samples/trading_calendar.csv")
    parser.add_argument("--daily-bar", default="raw/samples/daily_bar.csv")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()

    securities = read_security_master(args.security_master)
    calendars = read_trading_calendar(args.calendar)
    daily_bars = read_daily_bars(args.daily_bar)
    report = check_daily_bundle_quality(securities, calendars, daily_bars)

    if args.json:
        print(
            json.dumps(
                {
                    "passed": report.passed,
                    "error_count": report.error_count,
                    "warning_count": report.warning_count,
                    "issues": [issue.__dict__ for issue in report.issues],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"passed={report.passed} errors={report.error_count} warnings={report.warning_count}")
        for issue in report.issues:
            print(
                f"[{issue.severity}] {issue.dataset_code}.{issue.check_name} "
                f"symbol={issue.symbol} trade_date={issue.trade_date} field={issue.field_name}: {issue.message}"
            )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
