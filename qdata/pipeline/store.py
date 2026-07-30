from __future__ import annotations

import json
from typing import Any

from qdata.exceptions import QDataValidationError
from qdata.loaders.sql_loader import SqlDailyBundleLoader
from qdata.pipeline.models import PipelineJobConfig, PipelineJobRecord


class PostgresPipelineStore:
    """PostgreSQL-backed scheduler metadata store."""

    def __init__(self, postgres_dsn: str) -> None:
        self.postgres_dsn = postgres_dsn
        self._conn = None

    def __enter__(self) -> "PostgresPipelineStore":
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def open(self) -> None:
        if self._conn is None:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise QDataValidationError("psycopg is required for pipeline scheduling") from exc
            self._conn = psycopg.connect(self.postgres_dsn, row_factory=dict_row)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def ensure_job(self, config: PipelineJobConfig) -> PipelineJobRecord:
        self.open()
        source_id, dataset_id = self._ensure_catalog_metadata(config.provider, config.dataset_code)
        symbols = config.normalized_symbols()
        provider_config = json.dumps(config.provider_config, ensure_ascii=False)
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.pipeline_job (
                    job_code, dataset_id, source_id, provider, frequency, symbols,
                    provider_config, raw_root, strict_quality, retry_limit, all_market, batch_size,
                    max_symbols, min_completeness, skip_closed_days, sleep_seconds, schedule_timezone, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (job_code) DO UPDATE SET
                    dataset_id = EXCLUDED.dataset_id,
                    source_id = EXCLUDED.source_id,
                    provider = EXCLUDED.provider,
                    frequency = EXCLUDED.frequency,
                    symbols = EXCLUDED.symbols,
                    provider_config = EXCLUDED.provider_config,
                    raw_root = EXCLUDED.raw_root,
                    strict_quality = EXCLUDED.strict_quality,
                    retry_limit = EXCLUDED.retry_limit,
                    all_market = EXCLUDED.all_market,
                    batch_size = EXCLUDED.batch_size,
                    max_symbols = EXCLUDED.max_symbols,
                    min_completeness = EXCLUDED.min_completeness,
                    skip_closed_days = EXCLUDED.skip_closed_days,
                    sleep_seconds = EXCLUDED.sleep_seconds,
                    schedule_timezone = EXCLUDED.schedule_timezone,
                    is_active = TRUE,
                    updated_at = now()
                RETURNING job_id, job_code, provider, retry_limit
                """,
                (
                    config.job_code,
                    dataset_id,
                    source_id,
                    config.provider,
                    config.frequency,
                    symbols,
                    provider_config,
                    config.raw_root,
                    config.strict_quality,
                    config.retry_limit,
                    config.all_market,
                    config.batch_size,
                    config.max_symbols,
                    config.min_completeness,
                    config.skip_closed_days,
                    config.sleep_seconds,
                    config.schedule_timezone,
                ),
            )
            row = cursor.fetchone()
        self._conn.commit()
        return PipelineJobRecord(
            job_id=row["job_id"],
            job_code=row["job_code"],
            provider=row["provider"],
            dataset_code=config.dataset_code,
            retry_limit=row["retry_limit"],
        )

    def has_success(self, job_id: int, trade_date: str) -> bool:
        self.open()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM qmeta.pipeline_run
                WHERE job_id = %s
                  AND trade_date = %s
                  AND status = 'success'
                LIMIT 1
                """,
                (job_id, trade_date),
            )
            return cursor.fetchone() is not None

    def next_attempt(self, job_id: int, trade_date: str) -> int:
        self.open()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(MAX(attempt), 0) + 1 AS next_attempt
                FROM qmeta.pipeline_run
                WHERE job_id = %s
                  AND trade_date = %s
                """,
                (job_id, trade_date),
            )
            row = cursor.fetchone()
        return int(row["next_attempt"])

    def start_run(
        self,
        job_id: int,
        trade_date: str,
        attempt: int,
        run_type: str,
        symbols: list[str],
        provider_config: dict,
    ) -> int:
        self.open()
        provider_config_json = json.dumps(provider_config, ensure_ascii=False)
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.pipeline_run (
                    job_id, trade_date, attempt, run_type, status,
                    input_symbols, provider_config, started_at
                ) VALUES (%s, %s, %s, %s, 'running', %s, %s::jsonb, now())
                RETURNING run_id
                """,
                (job_id, trade_date, attempt, run_type, symbols, provider_config_json),
            )
            run_id = cursor.fetchone()["run_id"]
        self._conn.commit()
        return run_id

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
        self.open()
        raw_paths_json = json.dumps(raw_paths or {}, ensure_ascii=False)
        expected_by_exchange_json = json.dumps(expected_by_exchange or {}, ensure_ascii=False)
        actual_by_exchange_json = json.dumps(actual_by_exchange or {}, ensure_ascii=False)
        missing_by_exchange_json = json.dumps(missing_by_exchange or {}, ensure_ascii=False)
        missing_explanations_json = json.dumps(missing_explanations or {}, ensure_ascii=False)
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.pipeline_run
                SET status = %s,
                    finished_at = now(),
                    duration_ms = %s,
                    row_count = %s,
                    quality_passed = %s,
                    error_count = %s,
                    warning_count = %s,
                    raw_paths = %s::jsonb,
                    error_message = %s,
                    expected_row_count = %s,
                    missing_count = %s,
                    missing_symbols = %s,
                    completeness_rate = %s,
                    expected_by_exchange = %s::jsonb,
                    actual_by_exchange = %s::jsonb,
                    missing_by_exchange = %s::jsonb,
                    missing_explanations = %s::jsonb,
                    batch_count = %s,
                    all_market = %s,
                    repair_status = %s
                WHERE run_id = %s
                """,
                (
                    status,
                    duration_ms,
                    row_count,
                    quality_passed,
                    error_count,
                    warning_count,
                    raw_paths_json,
                    error_message,
                    expected_row_count,
                    missing_count,
                    missing_symbols or [],
                    completeness_rate,
                    expected_by_exchange_json,
                    actual_by_exchange_json,
                    missing_by_exchange_json,
                    missing_explanations_json,
                    batch_count,
                    all_market,
                    repair_status,
                    run_id,
                ),
            )
        self._conn.commit()

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
        self.open()
        provider_config_json = json.dumps(provider_config, ensure_ascii=False)
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.pipeline_run (
                    job_id, trade_date, attempt, run_type, status, input_symbols,
                    provider_config, started_at, finished_at, duration_ms, row_count, error_message,
                    expected_row_count, missing_count, missing_symbols, completeness_rate, batch_count, all_market
                ) VALUES (%s, %s, %s, %s, 'skipped', %s, %s::jsonb, now(), now(), 0, 0, %s, %s, 0, '{}', NULL, %s, %s)
                RETURNING run_id
                """,
                (
                    job_id,
                    trade_date,
                    attempt,
                    run_type,
                    symbols,
                    provider_config_json,
                    reason,
                    expected_row_count,
                    batch_count,
                    all_market,
                ),
            )
            run_id = cursor.fetchone()["run_id"]
        self._conn.commit()
        return run_id

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
        self.open()
        details_json = json.dumps(details or {}, ensure_ascii=False)
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.pipeline_repair_queue (
                    job_id, run_id, trade_date, dataset_id, source_id, reason, status,
                    expected_row_count, row_count, missing_count, missing_symbols,
                    completeness_rate, details, updated_at
                )
                SELECT
                    j.job_id, %s, %s, j.dataset_id, j.source_id, %s, 'open',
                    %s, %s, %s, %s, %s, %s::jsonb, now()
                FROM qmeta.pipeline_job j
                WHERE j.job_id = %s
                ON CONFLICT (job_id, trade_date, reason) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    dataset_id = EXCLUDED.dataset_id,
                    source_id = EXCLUDED.source_id,
                    status = 'open',
                    expected_row_count = EXCLUDED.expected_row_count,
                    row_count = EXCLUDED.row_count,
                    missing_count = EXCLUDED.missing_count,
                    missing_symbols = EXCLUDED.missing_symbols,
                    completeness_rate = EXCLUDED.completeness_rate,
                    details = EXCLUDED.details,
                    updated_at = now(),
                    resolved_at = NULL
                """,
                (
                    run_id,
                    trade_date,
                    reason,
                    expected_row_count,
                    row_count,
                    missing_count,
                    missing_symbols or [],
                    completeness_rate,
                    details_json,
                    job_id,
                ),
            )
            cursor.execute(
                """
                UPDATE qmeta.pipeline_run
                SET repair_status = 'queued'
                WHERE run_id = %s
                """,
                (run_id,),
            )
        self._conn.commit()

    def resolve_repair_items(self, job_id: int, trade_date: str, run_id: int) -> None:
        self.open()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.pipeline_repair_queue
                SET status = 'resolved',
                    run_id = %s,
                    updated_at = now(),
                    resolved_at = now()
                WHERE job_id = %s
                  AND trade_date = %s
                  AND status IN ('open', 'in_progress')
                """,
                (run_id, job_id, trade_date),
            )
        self._conn.commit()

    def update_watermark_success(self, job_id: int, trade_date: str, run_id: int) -> None:
        self.open()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.pipeline_watermark (
                    job_id, last_success_trade_date, last_success_run_id,
                    last_attempt_trade_date, last_attempt_run_id, consecutive_failures, updated_at
                ) VALUES (%s, %s, %s, %s, %s, 0, now())
                ON CONFLICT (job_id) DO UPDATE SET
                    last_success_trade_date = EXCLUDED.last_success_trade_date,
                    last_success_run_id = EXCLUDED.last_success_run_id,
                    last_attempt_trade_date = EXCLUDED.last_attempt_trade_date,
                    last_attempt_run_id = EXCLUDED.last_attempt_run_id,
                    consecutive_failures = 0,
                    updated_at = now()
                """,
                (job_id, trade_date, run_id, trade_date, run_id),
            )
        self._conn.commit()

    def update_watermark_failure(self, job_id: int, trade_date: str, run_id: int) -> None:
        self.open()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.pipeline_watermark (
                    job_id, last_attempt_trade_date, last_attempt_run_id, consecutive_failures, updated_at
                ) VALUES (%s, %s, %s, 1, now())
                ON CONFLICT (job_id) DO UPDATE SET
                    last_attempt_trade_date = EXCLUDED.last_attempt_trade_date,
                    last_attempt_run_id = EXCLUDED.last_attempt_run_id,
                    consecutive_failures = qmeta.pipeline_watermark.consecutive_failures + 1,
                    updated_at = now()
                """,
                (job_id, trade_date, run_id),
            )
        self._conn.commit()

    def get_watermark(self, job_id: int) -> dict[str, Any] | None:
        self.open()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT job_id, last_success_trade_date, last_success_run_id,
                       last_attempt_trade_date, last_attempt_run_id, consecutive_failures, updated_at
                FROM qmeta.pipeline_watermark
                WHERE job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def get_watermark_by_job_code(self, job_code: str) -> dict[str, Any] | None:
        self.open()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT w.job_id, w.last_success_trade_date, w.last_success_run_id,
                       w.last_attempt_trade_date, w.last_attempt_run_id,
                       w.consecutive_failures, w.updated_at
                FROM qmeta.pipeline_watermark w
                JOIN qmeta.pipeline_job j ON j.job_id = w.job_id
                WHERE j.job_code = %s
                """,
                (job_code,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def get_job_config(self, job_code: str) -> PipelineJobConfig:
        self.open()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    j.job_code, j.provider, j.frequency, j.symbols, j.provider_config, j.raw_root,
                    j.strict_quality, j.retry_limit, j.all_market, j.batch_size, j.max_symbols,
                    j.min_completeness, j.skip_closed_days, j.sleep_seconds, j.schedule_timezone,
                    dc.dataset_code
                FROM qmeta.pipeline_job j
                JOIN qmeta.dataset_catalog dc ON dc.dataset_id = j.dataset_id
                WHERE j.job_code = %s
                """,
                (job_code,),
            )
            row = cursor.fetchone()
        if not row:
            raise QDataValidationError(f"pipeline job not found: {job_code}")
        return PipelineJobConfig(
            job_code=row["job_code"],
            provider=row["provider"],
            dataset_code=row["dataset_code"],
            frequency=row["frequency"],
            symbols=list(row["symbols"] or []),
            provider_config=_json_value(row["provider_config"], {}),
            raw_root=row["raw_root"],
            strict_quality=row["strict_quality"],
            retry_limit=int(row["retry_limit"]),
            all_market=bool(row["all_market"]),
            batch_size=int(row["batch_size"]),
            max_symbols=row["max_symbols"],
            min_completeness=float(row["min_completeness"]),
            skip_closed_days=bool(row["skip_closed_days"]),
            sleep_seconds=float(row["sleep_seconds"]),
            schedule_timezone=row["schedule_timezone"],
        )

    def list_repair_items(
        self,
        job_code: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.open()
        statuses = statuses or ["open"]
        where = ["rq.status = ANY(%s)"]
        params: list[Any] = [statuses]
        if job_code:
            where.append("j.job_code = %s")
            params.append(job_code)
        params.append(limit)
        with self._conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    rq.repair_id, j.job_code, rq.job_id, rq.run_id, rq.trade_date,
                    rq.reason, rq.status, rq.expected_row_count, rq.row_count,
                    rq.missing_count, rq.missing_symbols, rq.completeness_rate,
                    rq.details, rq.created_at, rq.updated_at, rq.resolved_at
                FROM qmeta.pipeline_repair_queue rq
                JOIN qmeta.pipeline_job j ON j.job_id = rq.job_id
                WHERE {' AND '.join(where)}
                ORDER BY rq.trade_date, rq.updated_at
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def production_report(self, job_code: str, start_date: str, end_date: str) -> dict[str, Any]:
        self.open()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    r.run_id, r.trade_date, r.attempt, r.status, r.row_count,
                    r.expected_row_count, r.missing_count, r.missing_symbols,
                    r.completeness_rate, r.expected_by_exchange, r.actual_by_exchange,
                    r.missing_by_exchange, r.repair_status, r.duration_ms, r.error_message
                FROM qmeta.pipeline_run r
                JOIN qmeta.pipeline_job j ON j.job_id = r.job_id
                WHERE j.job_code = %s
                  AND r.trade_date BETWEEN %s AND %s
                  AND r.run_id = (
                      SELECT r2.run_id
                      FROM qmeta.pipeline_run r2
                      WHERE r2.job_id = r.job_id
                        AND r2.trade_date = r.trade_date
                      ORDER BY r2.attempt DESC, r2.run_id DESC
                      LIMIT 1
                  )
                ORDER BY r.trade_date
                """,
                (job_code, start_date, end_date),
            )
            runs = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT rq.reason, rq.status, count(*) AS count
                FROM qmeta.pipeline_repair_queue rq
                JOIN qmeta.pipeline_job j ON j.job_id = rq.job_id
                WHERE j.job_code = %s
                  AND rq.trade_date BETWEEN %s AND %s
                GROUP BY rq.reason, rq.status
                ORDER BY rq.reason, rq.status
                """,
                (job_code, start_date, end_date),
            )
            repairs = [dict(row) for row in cursor.fetchall()]
        return {"job_code": job_code, "start_date": start_date, "end_date": end_date, "runs": runs, "repairs": repairs}

    def _ensure_catalog_metadata(self, provider: str, dataset_code: str) -> tuple[int, int]:
        source_name, source_type, license_scope = SqlDailyBundleLoader.SOURCES.get(
            provider,
            (provider, "vendor", "unknown"),
        )
        dataset_name, asset_type, frequency, storage_layer, pit_required = SqlDailyBundleLoader.DATASETS.get(
            dataset_code,
            (dataset_code, None, "daily", "postgresql", False),
        )
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.source_system (
                    source_code, source_name, source_type, license_scope, update_frequency, latency_level, owner
                ) VALUES (%s, %s, %s, %s, 'daily', 'L4', 'qdata')
                ON CONFLICT (source_code) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    source_type = EXCLUDED.source_type,
                    license_scope = EXCLUDED.license_scope,
                    update_frequency = EXCLUDED.update_frequency,
                    latency_level = EXCLUDED.latency_level,
                    owner = EXCLUDED.owner,
                    updated_at = now()
                RETURNING source_id
                """,
                (provider, source_name, source_type, license_scope),
            )
            source_id = cursor.fetchone()["source_id"]
            cursor.execute(
                """
                INSERT INTO qmeta.dataset_catalog (
                    dataset_code, dataset_name, asset_type, frequency, storage_layer,
                    primary_source_id, pit_required, description
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'created by pipeline scheduler')
                ON CONFLICT (dataset_code) DO UPDATE SET
                    dataset_name = EXCLUDED.dataset_name,
                    asset_type = EXCLUDED.asset_type,
                    frequency = EXCLUDED.frequency,
                    storage_layer = EXCLUDED.storage_layer,
                    primary_source_id = EXCLUDED.primary_source_id,
                    pit_required = EXCLUDED.pit_required,
                    updated_at = now()
                RETURNING dataset_id
                """,
                (dataset_code, dataset_name, asset_type, frequency, storage_layer, source_id, pit_required),
            )
            dataset_id = cursor.fetchone()["dataset_id"]
        self._conn.commit()
        return int(source_id), int(dataset_id)


def _json_value(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value
