from __future__ import annotations

from datetime import timedelta
from time import perf_counter
from typing import Callable, Protocol

from qdata.backend_utils import date_range
from qdata.pipeline.models import PipelineJobConfig, PipelineJobRecord, PipelineRunResult
from qdata.pipeline.store import PostgresPipelineStore
from qdata.sources.sync import sync_daily_market
from qdata.sources.universe import is_provider_trade_date, list_provider_symbols


class PipelineStore(Protocol):
    def ensure_job(self, config: PipelineJobConfig) -> PipelineJobRecord:
        ...

    def has_success(self, job_id: int, trade_date: str) -> bool:
        ...

    def next_attempt(self, job_id: int, trade_date: str) -> int:
        ...

    def start_run(
        self,
        job_id: int,
        trade_date: str,
        attempt: int,
        run_type: str,
        symbols: list[str],
        provider_config: dict,
    ) -> int:
        ...

    def finish_run(
        self,
        run_id: int,
        status: str,
        duration_ms: int,
        row_count: int,
        quality_passed: bool | None,
        error_count: int,
        warning_count: int,
        raw_paths: dict[str, str] | None = None,
        error_message: str | None = None,
        expected_row_count: int | None = None,
        missing_count: int = 0,
        missing_symbols: list[str] | None = None,
        completeness_rate: float | None = None,
        expected_by_exchange: dict | None = None,
        actual_by_exchange: dict | None = None,
        missing_by_exchange: dict | None = None,
        missing_explanations: dict | None = None,
        batch_count: int = 1,
        all_market: bool = False,
        repair_status: str = "none",
    ) -> None:
        ...

    def record_skipped(
        self,
        job_id: int,
        trade_date: str,
        attempt: int,
        run_type: str,
        symbols: list[str],
        provider_config: dict,
        reason: str,
        expected_row_count: int | None = None,
        batch_count: int = 0,
        all_market: bool = False,
    ) -> int:
        ...

    def upsert_repair_item(
        self,
        job_id: int,
        run_id: int,
        trade_date: str,
        reason: str,
        expected_row_count: int | None,
        row_count: int,
        missing_count: int,
        missing_symbols: list[str],
        completeness_rate: float | None,
        details: dict,
    ) -> None:
        ...

    def resolve_repair_items(self, job_id: int, trade_date: str, run_id: int) -> None:
        ...

    def update_watermark_success(self, job_id: int, trade_date: str, run_id: int) -> None:
        ...

    def update_watermark_failure(self, job_id: int, trade_date: str, run_id: int) -> None:
        ...


SyncFunc = Callable[..., dict]


class DailyPipelineRunner:
    def __init__(
        self,
        store: PipelineStore,
        postgres_dsn: str,
        clickhouse_dsn: str,
        sync_func: SyncFunc = sync_daily_market,
    ) -> None:
        self.store = store
        self.postgres_dsn = postgres_dsn
        self.clickhouse_dsn = clickhouse_dsn
        self.sync_func = sync_func

    def run(
        self,
        config: PipelineJobConfig,
        start_date: str,
        end_date: str,
        force: bool = False,
        dry_run: bool = False,
        max_retries: int | None = None,
        run_type: str = "manual",
    ) -> list[PipelineRunResult]:
        job = self.store.ensure_job(config)
        symbols = config.normalized_symbols()
        retry_limit = job.retry_limit if max_retries is None else max_retries
        if dry_run:
            run_type = "dry_run"

        results: list[PipelineRunResult] = []
        for trade_date in iter_trade_dates(start_date, end_date):
            trade_date_text = trade_date.isoformat()
            if config.skip_closed_days and not is_provider_trade_date(config.provider, trade_date_text, config.provider_config):
                attempt = self.store.next_attempt(job.job_id, trade_date_text)
                reason = "market is closed for provider calendar"
                run_id = self.store.record_skipped(
                    job.job_id,
                    trade_date_text,
                    attempt,
                    run_type,
                    symbols,
                    config.provider_config,
                    reason,
                    expected_row_count=None,
                    batch_count=0,
                    all_market=config.all_market,
                )
                results.append(
                    PipelineRunResult(
                        job_code=job.job_code,
                        run_id=run_id,
                        trade_date=trade_date_text,
                        attempt=attempt,
                        status="skipped",
                        skipped_reason=reason,
                        batch_count=0,
                        all_market=config.all_market,
                    )
                )
                continue
            if not force and self.store.has_success(job.job_id, trade_date_text):
                attempt = self.store.next_attempt(job.job_id, trade_date_text)
                reason = "existing successful run; use --force to rerun"
                run_id = self.store.record_skipped(
                    job.job_id,
                    trade_date_text,
                    attempt,
                    run_type,
                    symbols,
                    config.provider_config,
                    reason,
                    expected_row_count=len(symbols) if symbols else None,
                    batch_count=_batch_count(symbols, config.batch_size),
                    all_market=config.all_market,
                )
                results.append(
                    PipelineRunResult(
                        job_code=job.job_code,
                        run_id=run_id,
                        trade_date=trade_date_text,
                        attempt=attempt,
                        status="skipped",
                        skipped_reason=reason,
                        all_market=config.all_market,
                    )
                )
                continue

            run_symbols = self._symbols_for_date(config, trade_date_text, symbols)
            for retry_index in range(retry_limit + 1):
                attempt = self.store.next_attempt(job.job_id, trade_date_text)
                run_id = self.store.start_run(
                    job.job_id,
                    trade_date_text,
                    attempt,
                    run_type,
                    run_symbols,
                    config.provider_config,
                )
                started = perf_counter()
                try:
                    sync_result = self.sync_func(
                        provider_name=config.provider,
                        trade_date=trade_date_text,
                        symbols=run_symbols or None,
                        postgres_dsn=self.postgres_dsn,
                        clickhouse_dsn=self.clickhouse_dsn,
                        raw_root=config.raw_root,
                        strict_quality=config.strict_quality,
                        dry_run=dry_run,
                        provider_kwargs=config.provider_config,
                        expected_symbols=run_symbols,
                        min_completeness=config.min_completeness,
                        batch_size=config.batch_size,
                        sleep_seconds=config.sleep_seconds,
                        quality_context={
                            "job_code": job.job_code,
                            "run_id": run_id,
                            "run_type": run_type,
                            "all_market": config.all_market,
                        },
                    )
                    result = self._finish_success(
                        job.job_code,
                        run_id,
                        trade_date_text,
                        attempt,
                        started,
                        sync_result,
                        config,
                    )
                    results.append(result)
                    if not dry_run:
                        if result.status == "success":
                            self.store.update_watermark_success(job.job_id, trade_date_text, run_id)
                            self.store.resolve_repair_items(job.job_id, trade_date_text, run_id)
                        else:
                            self.store.update_watermark_failure(job.job_id, trade_date_text, run_id)
                            self.store.upsert_repair_item(
                                job_id=job.job_id,
                                run_id=run_id,
                                trade_date=trade_date_text,
                                reason=_repair_reason(result, config),
                                expected_row_count=result.expected_row_count,
                                row_count=result.row_count,
                                missing_count=result.missing_count,
                                missing_symbols=result.missing_symbols,
                                completeness_rate=result.completeness_rate,
                                details={
                                    "expected_by_exchange": result.expected_by_exchange,
                                    "actual_by_exchange": result.actual_by_exchange,
                                    "missing_by_exchange": result.missing_by_exchange,
                                    "missing_explanations": result.missing_explanations,
                                    "min_completeness": config.min_completeness,
                                    "all_market": config.all_market,
                                },
                            )
                    break
                except Exception as exc:
                    duration_ms = _duration_ms(started)
                    message = _trim_error(exc)
                    self.store.finish_run(
                        run_id=run_id,
                        status="failed",
                        duration_ms=duration_ms,
                        row_count=0,
                        quality_passed=False,
                        error_count=1,
                        warning_count=0,
                        raw_paths={},
                        error_message=message,
                        expected_row_count=len(run_symbols) if run_symbols else None,
                        missing_count=0,
                        missing_symbols=[],
                        completeness_rate=None,
                        expected_by_exchange={},
                        actual_by_exchange={},
                        missing_by_exchange={},
                        missing_explanations={},
                        batch_count=_batch_count(run_symbols, config.batch_size),
                        all_market=config.all_market,
                        repair_status="queued",
                    )
                    self.store.update_watermark_failure(job.job_id, trade_date_text, run_id)
                    self.store.upsert_repair_item(
                        job_id=job.job_id,
                        run_id=run_id,
                        trade_date=trade_date_text,
                        reason="failed",
                        expected_row_count=len(run_symbols) if run_symbols else None,
                        row_count=0,
                        missing_count=0,
                        missing_symbols=[],
                        completeness_rate=None,
                        details={"error_message": message, "all_market": config.all_market},
                    )
                    results.append(
                        PipelineRunResult(
                            job_code=job.job_code,
                            run_id=run_id,
                            trade_date=trade_date_text,
                            attempt=attempt,
                            status="failed",
                            error_count=1,
                            error_message=message,
                            expected_row_count=len(run_symbols) if run_symbols else None,
                            batch_count=_batch_count(run_symbols, config.batch_size),
                            all_market=config.all_market,
                            repair_status="queued",
                        )
                    )
                    if retry_index >= retry_limit:
                        break
        return results

    def _finish_success(
        self,
        job_code: str,
        run_id: int,
        trade_date: str,
        attempt: int,
        started: float,
        sync_result: dict,
        config: PipelineJobConfig,
    ) -> PipelineRunResult:
        bundle = sync_result["bundle"]
        summary = sync_result.get("summary")
        quality_report = getattr(summary, "quality_report", None) or sync_result.get("quality_report")
        quality_passed = getattr(quality_report, "passed", None)
        error_count = int(getattr(quality_report, "error_count", 0))
        warning_count = int(getattr(quality_report, "warning_count", 0))
        completeness = sync_result.get("completeness") or {}
        expected_row_count = completeness.get("expected_count")
        missing_symbols = completeness.get("missing_symbols") or []
        missing_count = int(completeness.get("missing_count") or 0)
        completeness_rate = completeness.get("completeness_rate")
        expected_by_exchange = completeness.get("expected_by_exchange") or {}
        actual_by_exchange = completeness.get("actual_by_exchange") or {}
        missing_by_exchange = completeness.get("missing_by_exchange") or {}
        missing_explanations = completeness.get("missing_explanations") or {}
        row_count = len(bundle.daily_bars)
        completeness_passed = completeness_rate is None or completeness_rate >= config.min_completeness
        status = "success" if quality_passed is not False and completeness_passed else "partial_success"
        repair_status = "none" if status == "success" else "queued"
        raw_paths = sync_result.get("paths", {})
        batch_count = int(sync_result.get("batch_count") or 1)
        duration_ms = _duration_ms(started)
        self.store.finish_run(
            run_id=run_id,
            status=status,
            duration_ms=duration_ms,
            row_count=row_count,
            quality_passed=quality_passed,
            error_count=error_count,
            warning_count=warning_count,
            raw_paths=raw_paths,
            error_message=None,
            expected_row_count=expected_row_count,
            missing_count=missing_count,
            missing_symbols=missing_symbols,
            completeness_rate=completeness_rate,
            expected_by_exchange=expected_by_exchange,
            actual_by_exchange=actual_by_exchange,
            missing_by_exchange=missing_by_exchange,
            missing_explanations=missing_explanations,
            batch_count=batch_count,
            all_market=config.all_market,
            repair_status=repair_status,
        )
        return PipelineRunResult(
            job_code=job_code,
            run_id=run_id,
            trade_date=trade_date,
            attempt=attempt,
            status=status,
            row_count=row_count,
            quality_passed=quality_passed,
            error_count=error_count,
            warning_count=warning_count,
            expected_row_count=expected_row_count,
            missing_count=missing_count,
            missing_symbols=missing_symbols,
            completeness_rate=completeness_rate,
            expected_by_exchange=expected_by_exchange,
            actual_by_exchange=actual_by_exchange,
            missing_by_exchange=missing_by_exchange,
            missing_explanations=missing_explanations,
            batch_count=batch_count,
            all_market=config.all_market,
            repair_status=repair_status,
            raw_paths=raw_paths,
        )

    def _symbols_for_date(self, config: PipelineJobConfig, trade_date: str, configured_symbols: list[str]) -> list[str]:
        if not config.all_market:
            return configured_symbols
        return list_provider_symbols(
            provider_name=config.provider,
            trade_date=trade_date,
            provider_kwargs=config.provider_config,
            max_symbols=config.max_symbols,
        )


def run_daily_pipeline(
    config: PipelineJobConfig,
    start_date: str,
    end_date: str,
    postgres_dsn: str,
    clickhouse_dsn: str,
    force: bool = False,
    dry_run: bool = False,
    max_retries: int | None = None,
    run_type: str = "manual",
) -> list[PipelineRunResult]:
    with PostgresPipelineStore(postgres_dsn) as store:
        runner = DailyPipelineRunner(
            store=store,
            postgres_dsn=postgres_dsn,
            clickhouse_dsn=clickhouse_dsn,
        )
        return runner.run(
            config=config,
            start_date=start_date,
            end_date=end_date,
            force=force,
            dry_run=dry_run,
            max_retries=max_retries,
            run_type=run_type,
        )


def iter_trade_dates(start_date: str, end_date: str):
    start, end = date_range(start_date, end_date)
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _duration_ms(started: float) -> int:
    return max(int((perf_counter() - started) * 1000), 0)


def _trim_error(exc: Exception) -> str:
    message = f"{exc.__class__.__name__}: {exc}"
    return message[:2000]


def _batch_count(symbols: list[str], batch_size: int) -> int:
    if not symbols:
        return 1
    if batch_size <= 0:
        return 1
    return (len(symbols) + batch_size - 1) // batch_size


def _repair_reason(result: PipelineRunResult, config: PipelineJobConfig) -> str:
    if result.status == "failed":
        return "failed"
    if result.completeness_rate is not None and result.completeness_rate < config.min_completeness:
        return "completeness_below_threshold"
    return "partial_success"
