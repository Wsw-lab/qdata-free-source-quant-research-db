-- A 股量化数据平台 Lambda：后台自动化 worker 运行记录

CREATE TABLE IF NOT EXISTS qmeta.worker_run (
    worker_run_id       BIGSERIAL PRIMARY KEY,
    run_code            VARCHAR(160) NOT NULL UNIQUE,
    trigger_mode        VARCHAR(32) NOT NULL DEFAULT 'manual',
    status              VARCHAR(24) NOT NULL DEFAULT 'running',
    task_filter         TEXT[] NOT NULL DEFAULT '{}',
    dry_run             BOOLEAN NOT NULL DEFAULT FALSE,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    processed_count     BIGINT NOT NULL DEFAULT 0,
    success_count       BIGINT NOT NULL DEFAULT 0,
    failed_count        BIGINT NOT NULL DEFAULT 0,
    warning_count       BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke')),
    CHECK (status IN ('running', 'success', 'warning', 'failed', 'skipped')),
    CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CHECK (processed_count >= 0),
    CHECK (success_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (warning_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_run_status_started
    ON qmeta.worker_run(status, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.worker_task_run (
    task_run_id         BIGSERIAL PRIMARY KEY,
    worker_run_id       BIGINT NOT NULL REFERENCES qmeta.worker_run(worker_run_id) ON DELETE CASCADE,
    task_name           VARCHAR(96) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'running',
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    processed_count     BIGINT NOT NULL DEFAULT 0,
    success_count       BIGINT NOT NULL DEFAULT 0,
    failed_count        BIGINT NOT NULL DEFAULT 0,
    warning_count       BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule')),
    CHECK (status IN ('running', 'success', 'warning', 'failed', 'skipped')),
    CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CHECK (processed_count >= 0),
    CHECK (success_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (warning_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_task_run_task_started
    ON qmeta.worker_task_run(task_name, started_at DESC, status);
