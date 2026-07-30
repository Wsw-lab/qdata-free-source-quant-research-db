from __future__ import annotations

from pathlib import Path

from qdata.exceptions import QDataValidationError
from qdata.ingest.models import TradableUniverseRecord
from qdata.loaders import SqlDailyBundleLoader
from qdata.sources.export import export_market_constraint_bundle, export_minute_market_bundle
from qdata.sources.registry import create_provider


def sync_market_constraints(
    provider_name: str,
    trade_date: str,
    symbols: list[str] | None,
    postgres_dsn: str,
    clickhouse_dsn: str,
    raw_root: str | Path = "raw",
    dry_run: bool = False,
    provider_kwargs: dict | None = None,
):
    provider = create_provider(provider_name, **(provider_kwargs or {}))
    bundle = provider.fetch_market_constraints(trade_date=trade_date, symbols=symbols)
    paths = export_market_constraint_bundle(bundle, raw_root=raw_root)
    if dry_run:
        return {"bundle": bundle, "paths": paths, "ingested": False}
    with SqlDailyBundleLoader(postgres_dsn, clickhouse_dsn, source_code=provider_name) as loader:
        loader.load_security_master(bundle.securities)
        loader.load_market_constraints(
            adjustment_factors=bundle.adjustment_factors,
            limit_prices=bundle.limit_prices,
            suspensions=bundle.suspensions,
        )
    return {"bundle": bundle, "paths": paths, "ingested": True}


def sync_minute_market(
    provider_name: str,
    trade_date: str,
    symbols: list[str] | None,
    postgres_dsn: str,
    clickhouse_dsn: str,
    raw_root: str | Path = "raw",
    dry_run: bool = False,
    provider_kwargs: dict | None = None,
):
    provider = create_provider(provider_name, **(provider_kwargs or {}))
    bundle = provider.fetch_minute_market(trade_date=trade_date, symbols=symbols)
    if not bundle.minute_bars:
        raise QDataValidationError(f"provider {provider_name} returned no minute bars for {trade_date}")
    paths = export_minute_market_bundle(bundle, raw_root=raw_root)
    if dry_run:
        return {"bundle": bundle, "paths": paths, "ingested": False}
    with SqlDailyBundleLoader(postgres_dsn, clickhouse_dsn, source_code=provider_name) as loader:
        loader.load_security_master(bundle.securities)
        loader.load_minute_bars(bundle.minute_bars)
    return {"bundle": bundle, "paths": paths, "ingested": True}


def build_tradable_universe(
    trade_date: str,
    symbols: list[str],
    constraints: list[dict],
    min_list_days: int = 30,
) -> list[TradableUniverseRecord]:
    constraint_by_symbol = {row["symbol"]: row for row in constraints}
    records = []
    for symbol in symbols:
        row = constraint_by_symbol.get(symbol, {})
        if row.get("is_suspended"):
            continue
        if row.get("is_st"):
            continue
        if row.get("is_delisting_period"):
            continue
        if row.get("is_new_listing"):
            continue
        if int(row.get("list_days") or 0) < min_list_days:
            continue
        records.append(TradableUniverseRecord(symbol=symbol, trade_date=trade_date))
    return records
