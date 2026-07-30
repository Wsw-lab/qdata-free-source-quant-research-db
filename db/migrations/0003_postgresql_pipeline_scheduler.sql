-- Pipeline scheduler Alpha for daily data production.

CREATE TABLE IF NOT EXISTS qmeta.pipeline_job (
    job_id              BIGSERIAL PRIMARY KEY,
    job_code            VARCHAR(128) NOT NULL UNIQUE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    provider            VARCHAR(64) NOT NULL,
    frequency           VARCHAR(32) NOT NULL DEFAULT 'daily',
    symbols             TEXT[] NOT NULL DEFAULT '{}',
    provider_config     JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_root            TEXT NOT NULL DEFAULT 'raw',
    strict_quality      BOOLEAN NOT NULL DEFAULT TRUE,
    retry_limit         INTEGER NOT NULL DEFAULT 1,
    schedule_timezone   VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (frequency IN ('daily', 'minute', 'quarterly', 'adhoc')),
    CHECK (retry_limit >= 0)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_job_dataset_source
    ON qmeta.pipeline_job(dataset_id, source_id, is_active);

CREATE TABLE IF NOT EXISTS qmeta.pipeline_run (
    run_id              BIGSERIAL PRIMARY KEY,
    job_id              BIGINT NOT NULL REFERENCES qmeta.pipeline_job(job_id),
    trade_date          DATE NOT NULL,
    attempt             INTEGER NOT NULL DEFAULT 1,
    run_type            VARCHAR(32) NOT NULL DEFAULT 'manual',
    status              VARCHAR(24) NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    input_symbols       TEXT[] NOT NULL DEFAULT '{}',
    provider_config     JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_paths           JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_count           BIGINT,
    quality_passed      BOOLEAN,
    error_count         BIGINT NOT NULL DEFAULT 0,
    warning_count       BIGINT NOT NULL DEFAULT 0,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, trade_date, attempt),
    CHECK (attempt >= 1),
    CHECK (run_type IN ('manual', 'scheduled', 'backfill', 'retry', 'dry_run')),
    CHECK (status IN ('created', 'running', 'success', 'partial_success', 'failed', 'skipped', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_job_date
    ON qmeta.pipeline_run(job_id, trade_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_status_started
    ON qmeta.pipeline_run(status, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.pipeline_watermark (
    job_id                  BIGINT PRIMARY KEY REFERENCES qmeta.pipeline_job(job_id),
    last_success_trade_date DATE,
    last_success_run_id     BIGINT REFERENCES qmeta.pipeline_run(run_id),
    last_attempt_trade_date DATE,
    last_attempt_run_id     BIGINT REFERENCES qmeta.pipeline_run(run_id),
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (consecutive_failures >= 0)
);
