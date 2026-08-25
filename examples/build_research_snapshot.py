"""Build a synthetic ``research_snapshot_v1`` contract demonstration.

The fixture is deterministic and database-free. It is not market data and is
not strategy or performance evidence.
"""

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
FIXTURE_NOTICE = (
    "Deterministic synthetic format/contract demonstration; not market data, "
    "strategy, or performance evidence."
)
FIXTURE_QUALITY_STATUS = {
    "status": "passed",
    "error_count": 0,
    "warning_count": 0,
}


def synthetic_datasets() -> dict[str, list[dict[str, Any]]]:
    """Return a tiny adversarial contract fixture with three sessions."""

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
                "bar_end_at": "2024-01-03T15:00:00+08:00",
                "available_at": "2024-01-03T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-02",
                "open_raw": "9.50",
                "high_raw": "9.55",
                "low_raw": "9.46",
                "close_raw": "9.46",
                "close_adjusted": "9.46",
                "adjustment_factor": "1.0",
                "volume": "135000000",
                "amount": "1277100000",
                "bar_end_at": "2024-01-02T15:00:00+08:00",
                "available_at": "2024-01-02T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
            {
                "symbol": "600519.SH",
                "trade_date": "2024-01-02",
                "open_raw": "1700.00",
                "high_raw": "1870.00",
                "low_raw": "1690.00",
                "close_raw": "1870.00",
                "close_adjusted": "1870.00",
                "adjustment_factor": "1.0",
                "volume": "2400000",
                "amount": "4116000000",
                "bar_end_at": "2024-01-02T15:00:00+08:00",
                "available_at": "2024-01-02T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-03",
                "open_raw": "9.46",
                "high_raw": "9.46",
                "low_raw": "9.46",
                "close_raw": "9.46",
                "close_adjusted": "9.46",
                "adjustment_factor": "1.0",
                "volume": "0",
                "amount": "0",
                "bar_end_at": "2024-01-03T15:00:00+08:00",
                "available_at": "2024-01-03T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
            {
                "symbol": "600519.SH",
                "trade_date": "2024-01-04",
                "open_raw": "1730.00",
                "high_raw": "1750.00",
                "low_raw": "1720.00",
                "close_raw": "1742.00",
                "close_adjusted": "1742.00",
                "adjustment_factor": "1.0",
                "volume": "2600000",
                "amount": "4529200000",
                "bar_end_at": "2024-01-04T15:00:00+08:00",
                "available_at": "2024-01-04T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-04",
                "open_raw": "9.47",
                "high_raw": "9.60",
                "low_raw": "9.40",
                "close_raw": "9.55",
                "close_adjusted": "9.55",
                "adjustment_factor": "1.0",
                "volume": "142000000",
                "amount": "1356100000",
                "bar_end_at": "2024-01-04T15:00:00+08:00",
                "available_at": "2024-01-04T15:05:00+08:00",
                "source_id": "synthetic",
                "batch_id": "batch-fixture-001",
                "data_version": FIXTURE_DATA_VERSION,
            },
        ],
        "tradability": [
            {
                "symbol": "600519.SH",
                "trade_date": "2024-01-03",
                "is_st": False,
                "is_suspended": False,
                "limit_up": "1900.00",
                "limit_down": "1600.00",
                "is_limit_up": False,
                "is_limit_down": False,
                "can_buy": True,
                "can_sell": True,
                "lot_size": 100,
                "t_plus_one": True,
                "available_at": "2024-01-03T09:15:00+08:00",
            },
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-02",
                "is_st": True,
                "is_suspended": False,
                "limit_up": "9.94",
                "limit_down": "9.46",
                "is_limit_up": False,
                "is_limit_down": True,
                "can_buy": True,
                "can_sell": False,
                "lot_size": 100,
                "t_plus_one": True,
                "available_at": "2024-01-02T09:15:00+08:00",
            },
            {
                "symbol": "600519.SH",
                "trade_date": "2024-01-02",
                "is_st": False,
                "is_suspended": False,
                "limit_up": "1870.00",
                "limit_down": "1530.00",
                "is_limit_up": True,
                "is_limit_down": False,
                "can_buy": False,
                "can_sell": True,
                "lot_size": 100,
                "t_plus_one": True,
                "available_at": "2024-01-02T09:15:00+08:00",
            },
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-03",
                "is_st": False,
                "is_suspended": True,
                "limit_up": "10.41",
                "limit_down": "8.51",
                "is_limit_up": False,
                "is_limit_down": False,
                "can_buy": False,
                "can_sell": False,
                "lot_size": 100,
                "t_plus_one": True,
                "available_at": "2024-01-03T09:15:00+08:00",
            },
            {
                "symbol": "600519.SH",
                "trade_date": "2024-01-04",
                "is_st": False,
                "is_suspended": False,
                "limit_up": "1900.00",
                "limit_down": "1600.00",
                "is_limit_up": False,
                "is_limit_down": False,
                "can_buy": True,
                "can_sell": True,
                "lot_size": 100,
                "t_plus_one": True,
                "available_at": "2024-01-04T09:15:00+08:00",
            },
            {
                "symbol": "000001.SZ",
                "trade_date": "2024-01-04",
                "is_st": False,
                "is_suspended": False,
                "limit_up": "10.41",
                "limit_down": "8.51",
                "is_limit_up": False,
                "is_limit_down": False,
                "can_buy": True,
                "can_sell": True,
                "lot_size": 100,
                "t_plus_one": True,
                "available_at": "2024-01-04T09:15:00+08:00",
            },
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
                "delist_date": "2024-01-05",
                "valid_from": "1991-04-03",
                "valid_to": "2024-01-05",
                "board": "SZSE_MAIN",
                "asset_type": "stock",
                "status": "delisted",
                "available_at": "2023-12-29T18:00:00+08:00",
            },
        ],
        "fundamental_pit": [
            {
                "symbol": "600519.SH",
                "report_period_end": "2023-09-30",
                "field_name": "roe_ttm",
                "field_value": "0.315",
                "published_at": "2023-10-20T18:30:00+08:00",
                "first_seen_at": "2023-10-20T18:35:00+08:00",
                "available_at": "2023-10-23T09:00:00+08:00",
                "revision_id": "original",
                "is_restated": False,
                "source_id": "synthetic",
            },
            {
                "symbol": "600519.SH",
                "report_period_end": "2023-09-30",
                "field_name": "roe_ttm",
                "field_value": "0.318",
                "published_at": "2024-01-03T18:30:00+08:00",
                "first_seen_at": "2024-01-03T18:35:00+08:00",
                "available_at": "2024-01-04T09:00:00+08:00",
                "revision_id": "restatement-1",
                "is_restated": True,
                "source_id": "synthetic",
            },
            {
                "symbol": "000001.SZ",
                "report_period_end": "2023-09-30",
                "field_name": "roe_ttm",
                "field_value": "0.112",
                "published_at": "2023-10-23T18:30:00+08:00",
                "first_seen_at": "2023-10-23T18:35:00+08:00",
                "available_at": "2023-10-24T09:00:00+08:00",
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
        artifact_notice=FIXTURE_NOTICE,
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
