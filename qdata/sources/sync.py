from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any

from qdata.exceptions import QDataValidationError
from qdata.ingest.pipeline import ingest_daily_bundle
from qdata.ingest.quality import check_daily_bundle_quality, daily_bar_completeness
from qdata.loaders import SqlDailyBundleLoader
from qdata.phi5_route_policy import (
    finalize_route_decision,
    resolve_source_route,
    route_meta,
    write_source_route_decision_audit,
)
from qdata.sources.export import export_daily_market_bundle
from qdata.sources.models import DailyMarketBundle
from qdata.sources.registry import create_provider


def sync_daily_market(
    provider_name: str,
    trade_date: str,
    symbols: list[str] | None,
    postgres_dsn: str,
    clickhouse_dsn: str,
    raw_root: str | Path = "raw",
    strict_quality: bool = True,
    dry_run: bool = False,
    provider_kwargs: dict | None = None,
    expected_symbols: list[str] | None = None,
    min_completeness: float = 1.0,
    batch_size: int = 0,
    sleep_seconds: float = 0,
    quality_context: dict[str, Any] | None = None,
    use_route_policy: bool = False,
    route_provider_kwargs: dict[str, dict[str, Any]] | None = None,
    route_resolver=None,
    route_audit_writer=None,
):
    route_started_at = datetime.now(timezone.utc)
    route_decision = None
    if use_route_policy:
        resolver = route_resolver or resolve_source_route
        route_decision = resolver(
            postgres_dsn,
            dataset_code="daily_bar",
            requested_source_code=provider_name,
            as_of_date=trade_date,
            request_key=_route_request_key("daily_bar", trade_date, symbols),
            decision_context="sync",
        )
    provider_sequence = _provider_attempt_sequence(route_decision, provider_name)
    bundle = None
    final_provider_name = provider_sequence[0]
    attempt_sources: list[str] = []
    attempt_errors: list[dict[str, str]] = []
    for attempt_provider_name in provider_sequence:
        attempt_sources.append(attempt_provider_name)
        try:
            provider = create_provider(
                attempt_provider_name,
                **_provider_kwargs_for(
                    attempt_provider_name,
                    requested_provider_name=provider_name,
                    provider_kwargs=provider_kwargs,
                    route_provider_kwargs=route_provider_kwargs,
                ),
            )
            bundle = _fetch_bundle(
                provider=provider,
                provider_name=attempt_provider_name,
                trade_date=trade_date,
                symbols=symbols,
                batch_size=batch_size,
                sleep_seconds=sleep_seconds,
            )
            if not bundle.daily_bars:
                raise QDataValidationError(f"provider {attempt_provider_name} returned no daily bars for {trade_date}")
            final_provider_name = attempt_provider_name
            break
        except Exception as exc:
            attempt_errors.append({"source_code": attempt_provider_name, "error_message": str(exc)})
            if attempt_provider_name == provider_sequence[-1]:
                finalized = _finalize_and_write_route_decision(
                    postgres_dsn,
                    route_decision,
                    final_source_code=attempt_provider_name,
                    status="fallback_failed" if len(attempt_sources) > 1 else "failed",
                    attempt_sources=attempt_sources,
                    row_count=0,
                    duration_ms=_duration_ms(route_started_at),
                    error_message=str(exc),
                    fallback_reason=attempt_errors[0]["error_message"] if len(attempt_errors) > 1 else None,
                    details={"attempt_errors": attempt_errors},
                    started_at=route_started_at,
                    route_audit_writer=route_audit_writer,
                )
                if finalized:
                    route_decision = finalized
                raise
            continue
    if bundle is None:
        raise QDataValidationError(f"provider {provider_name} returned no daily bars for {trade_date}")
    try:
        paths = export_daily_market_bundle(bundle, raw_root=raw_root)
        expected = expected_symbols if expected_symbols is not None else symbols
        completeness = daily_bar_completeness(
            bundle.daily_bars,
            expected,
            securities=bundle.securities,
            trade_date=trade_date,
        )
        if dry_run:
            quality_report = check_daily_bundle_quality(
                bundle.securities,
                bundle.calendars,
                bundle.daily_bars,
                expected_symbols=expected,
                min_completeness=min_completeness,
            )
            result = {
                "bundle": bundle,
                "paths": paths,
                "summary": None,
                "quality_report": quality_report,
                "completeness": completeness,
                "batch_count": _batch_count(symbols, batch_size),
            }
        else:
            merged_quality_context = {
                **(quality_context or {}),
                **({"route_policy": route_meta(route_decision)} if route_decision else {}),
            }
            with SqlDailyBundleLoader(
                postgres_dsn=postgres_dsn,
                clickhouse_dsn=clickhouse_dsn,
                source_code=final_provider_name,
            ) as loader:
                summary = ingest_daily_bundle(
                    security_master_path=paths["security_master"],
                    trading_calendar_path=paths["trading_calendar"],
                    daily_bar_path=paths["daily_bar"],
                    loader=loader,
                    raw_root=raw_root,
                    source_name=final_provider_name,
                    strict_quality=strict_quality,
                    store_raw=False,
                    expected_symbols=expected,
                    min_completeness=min_completeness,
                    quality_context=merged_quality_context,
                )
            result = {
                "bundle": bundle,
                "paths": paths,
                "summary": summary,
                "completeness": completeness,
                "batch_count": _batch_count(symbols, batch_size),
            }
    except Exception as exc:
        finalized = _finalize_and_write_route_decision(
            postgres_dsn,
            route_decision,
            final_source_code=final_provider_name,
            status="failed",
            attempt_sources=attempt_sources,
            row_count=len(bundle.daily_bars),
            duration_ms=_duration_ms(route_started_at),
            error_message=str(exc),
            fallback_reason=attempt_errors[0]["error_message"] if attempt_errors else None,
            details={"attempt_errors": attempt_errors},
            started_at=route_started_at,
            route_audit_writer=route_audit_writer,
        )
        if finalized:
            route_decision = finalized
        raise
    finalized = _finalize_and_write_route_decision(
        postgres_dsn,
        route_decision,
        final_source_code=final_provider_name,
        status="fallback_success" if len(attempt_sources) > 1 else "success",
        attempt_sources=attempt_sources,
        row_count=len(bundle.daily_bars),
        duration_ms=_duration_ms(route_started_at),
        error_message=None,
        fallback_reason=attempt_errors[0]["error_message"] if attempt_errors else None,
        details={"attempt_errors": attempt_errors},
        started_at=route_started_at,
        route_audit_writer=route_audit_writer,
    )
    if finalized:
        result["route_decision"] = route_meta(finalized)
    return result


def _fetch_bundle(
    provider,
    provider_name: str,
    trade_date: str,
    symbols: list[str] | None,
    batch_size: int,
    sleep_seconds: float,
) -> DailyMarketBundle:
    if not symbols or batch_size <= 0 or len(symbols) <= batch_size:
        return provider.fetch_daily_market(trade_date=trade_date, symbols=symbols)
    bundles = []
    for index, symbol_batch in enumerate(_chunks(symbols, batch_size)):
        bundles.append(provider.fetch_daily_market(trade_date=trade_date, symbols=symbol_batch))
        if sleep_seconds > 0 and index < _batch_count(symbols, batch_size) - 1:
            sleep(sleep_seconds)
    return _merge_bundles(provider_name, trade_date, bundles)


def _merge_bundles(provider_name: str, trade_date: str, bundles: list[DailyMarketBundle]) -> DailyMarketBundle:
    securities = {}
    calendars = {}
    daily_bars = []
    for bundle in bundles:
        for record in bundle.securities:
            securities.setdefault(record.symbol, record)
        for record in bundle.calendars:
            calendars.setdefault((record.exchange, record.trade_date), record)
        daily_bars.extend(bundle.daily_bars)
    return DailyMarketBundle(
        provider=provider_name,
        trade_date=trade_date,
        securities=list(securities.values()),
        calendars=list(calendars.values()),
        daily_bars=daily_bars,
    )


def _chunks(items: list[str], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _batch_count(symbols: list[str] | None, batch_size: int) -> int:
    if not symbols:
        return 1
    if batch_size <= 0:
        return 1
    return (len(symbols) + batch_size - 1) // batch_size


def _provider_attempt_sequence(route_decision: dict[str, Any] | None, requested_provider_name: str) -> list[str]:
    if not route_decision:
        return [requested_provider_name]
    selected = str(route_decision.get("selected_source_code") or requested_provider_name)
    fallback_codes = [str(code) for code in route_decision.get("fallback_source_codes") or [] if code]
    return _dedupe([selected, *fallback_codes, requested_provider_name])


def _provider_kwargs_for(
    provider_name: str,
    *,
    requested_provider_name: str,
    provider_kwargs: dict[str, Any] | None,
    route_provider_kwargs: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    if route_provider_kwargs and provider_name in route_provider_kwargs:
        return dict(route_provider_kwargs[provider_name])
    if provider_name == requested_provider_name:
        return dict(provider_kwargs or {})
    if route_provider_kwargs and "*" in route_provider_kwargs:
        return dict(route_provider_kwargs["*"])
    return {}


def _finalize_and_write_route_decision(
    postgres_dsn: str,
    route_decision: dict[str, Any] | None,
    *,
    final_source_code: str,
    status: str,
    attempt_sources: list[str],
    row_count: int | None,
    duration_ms: int,
    error_message: str | None,
    fallback_reason: str | None,
    details: dict[str, Any],
    started_at: datetime,
    route_audit_writer=None,
) -> dict[str, Any] | None:
    if not route_decision:
        return None
    finalized = finalize_route_decision(
        route_decision,
        final_source_code=final_source_code,
        status=status,
        attempt_sources=attempt_sources,
        row_count=row_count,
        duration_ms=duration_ms,
        error_message=error_message,
        fallback_reason=fallback_reason,
        details=details,
    )
    writer = route_audit_writer or write_source_route_decision_audit
    writer(postgres_dsn, finalized, started_at=started_at, finished_at=datetime.now(timezone.utc))
    return finalized


def _route_request_key(dataset_code: str, trade_date: str, symbols: list[str] | None) -> str:
    symbol_key = ",".join(symbols or ["*"])
    return f"sync:{dataset_code}:{trade_date}:{symbol_key}"


def _duration_ms(started_at: datetime) -> int:
    return int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
