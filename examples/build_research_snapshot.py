"""Build a deterministic, database-free ``research_snapshot_v1`` fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.research_snapshot import build_research_snapshot, verify_research_snapshot


FIXTURE_CUTOFF_TS = "2024-05-01T16:00:00+08:00"
FIXTURE_TIMEZONE = "Asia/Shanghai"
FIXTURE_SOURCE = "deterministic_synthetic_fixture"
FIXTURE_DATA_VERSION = "fixture-v1"
FIXTURE_QUALITY_STATUS = {
    "status": "passed",
    "error_count": 0,
    "warning_count": 0,
}


def synthetic_datasets() -> dict[str, list[dict[str, Any]]]:
    """Return a tiny deterministic fixture with two symbols and two sessions."""

    return {
        # Deliberately not primary-key sorted: the builder owns canonical order.
        "daily_bar": [
            {
                "symbol": "600519.SH",
                "trade_date": "2024-01-03",
                "open_raw": "1710.00",
                "high_raw": "1735.00",
                "low_raw": "1702.00",
                "close_raw": "1728.00",
                "close_adjusted": "1728.00",
                "adjustment_factor": "1.0",
                "volume": "2534000",
                "amount": "4368000000",
                "available_at": "2024-01-03T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-02",
                "open_raw": "9.40",
                "high_raw": "9.55",
                "low_raw": "9.31",
                "close_raw": "9.46",
                "close_adjusted": "9.46",
                "adjustment_factor": "1.0",
                "volume": "135000000",
                "amount": "1277100000",
                "available_at": "2024-01-02T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
            {
                "symbol": "600519.SH",
                "trade_date": "2024-01-02",
                "open_raw": "1700.00",
                "high_raw": "1726.00",
                "low_raw": "1690.00",
                "close_raw": "1715.00",
                "close_adjusted": "1715.00",
                "adjustment_factor": "1.0",
                "volume": "2400000",
                "amount": "4116000000",
                "available_at": "2024-01-02T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-03",
                "open_raw": "9.47",
                "high_raw": "9.61",
                "low_raw": "9.38",
                "close_raw": "9.52",
                "close_adjusted": "9.52",
                "adjustment_factor": "1.0",
                "volume": "140000000",
                "amount": "1332800000",
                "available_at": "2024-01-03T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
        ],
        "tradability": [
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "is_st": False,
                "is_suspended": False,
                "limit_up": limit_up,
                "limit_down": limit_down,
                "is_limit_up": False,
                "is_limit_down": False,
                "can_buy": True,
                "can_sell": True,
                "lot_size": 100,
                "t_plus_one": True,
                "available_at": f"{trade_date}T09:15:00+08:00",
            }
            for symbol, trade_date, limit_up, limit_down in (
                ("600519.SH", "2024-01-03", "1886.50", "1543.50"),
                ("000001.SZ", "2024-01-02", "10.34", "8.46"),
                ("600519.SH", "2024-01-02", "1870.00", "1530.00"),
                ("000001.SZ", "2024-01-03", "10.41", "8.51"),
            )
        ],
        "security_membership": [
            {
                "symbol": "600519.SH",
                "list_date": "2001-08-27",
                "delist_date": None,
                "valid_from": "2001-08-27",
                "valid_to": None,
                "board": "SSE_MAIN",
                "asset_type": "stock",
                "status": "active",
                "available_at": "2020-01-01T00:00:00+08:00",
            },
            {
                "symbol": "000001.SZ",
                "list_date": "1991-04-03",
                "delist_date": None,
                "valid_from": "1991-04-03",
                "valid_to": None,
                "board": "SZSE_MAIN",
                "asset_type": "stock",
                "status": "active",
                "available_at": "2020-01-01T00:00:00+08:00",
            },
        ],
        "fundamental_pit": [
            {
                "symbol": "600519.SH",
                "report_period_end": "2023-12-31",
                "field_name": "roe_ttm",
                "field_value": "0.315",
                "published_at": "2024-04-03T18:30:00+08:00",
                "first_seen_at": "2024-04-03T18:35:00+08:00",
                "available_at": "2024-04-04T09:00:00+08:00",
                "revision_id": "original",
                "is_restated": False,
                "source_id": "synthetic",
            },
            {
                "symbol": "000001.SZ",
                "report_period_end": "2023-12-31",
                "field_name": "roe_ttm",
                "field_value": "0.112",
                "published_at": "2024-03-15T18:30:00+08:00",
                "first_seen_at": "2024-03-15T18:35:00+08:00",
                "available_at": "2024-03-18T09:00:00+08:00",
                "revision_id": "original",
                "is_restated": False,
                "source_id": "synthetic",
            },
        ],
    }


def run(output_dir: str | Path) -> dict[str, Any]:
    return build_research_snapshot(
        output_dir,
        synthetic_datasets(),
        cutoff_ts=FIXTURE_CUTOFF_TS,
        timezone_name=FIXTURE_TIMEZONE,
        source=FIXTURE_SOURCE,
        data_version=FIXTURE_DATA_VERSION,
        quality_status=FIXTURE_QUALITY_STATUS,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build", help="build the deterministic fixture")
    build_parser.add_argument(
        "output_dir", help="new snapshot directory; existing data is never replaced"
    )
    verify_parser = subparsers.add_parser("verify", help="verify an existing snapshot")
    verify_parser.add_argument("snapshot_dir", help="snapshot directory to verify")
    args = parser.parse_args()
    if args.command == "build":
        manifest = run(args.output_dir)
    else:
        manifest = verify_research_snapshot(args.snapshot_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
