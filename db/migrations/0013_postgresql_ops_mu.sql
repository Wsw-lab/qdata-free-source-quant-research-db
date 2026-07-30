-- A 股量化数据平台 Mu：后台 worker 调度器、锁和心跳

CREATE TABLE IF NOT EXISTS qmeta.worker_schedule (
    schedule_id         BIGSERIAL PRIMARY KEY,
    schedule_code       VARCHAR(160) NOT NULL UNIQUE,
    task_name           VARCHAR(96) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    frequency_seconds   INTEGER NOT NULL DEFAULT 300,
    max_runtime_seconds INTEGER NOT NULL DEFAULT 600,
    lock_timeout_seconds INTEGER NOT NULL DEFAULT 900,
    retry_limit         INTEGER NOT NULL DEFAULT 3,
    retry_backoff_seconds INTEGER NOT NULL DEFAULT 60,
    dry_run             BOOLEAN NOT NULL DEFAULT FALSE,
    task_args           JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_worker_run_id  BIGINT REFERENCES qmeta.worker_run(worker_run_id),
    last_status         VARCHAR(24),
    last_run_at         TIMESTAMPTZ,
    next_run_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_count           BIGINT NOT NULL DEFAULT 0,
    success_count       BIGINT NOT NULL DEFAULT 0,
    warning_count       BIGINT NOT NULL DEFAULT 0,
    failed_count        BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule')),
    CHECK (status IN ('active', 'paused', 'retired')),
    CHECK (last_status IS NULL OR last_status IN ('running', 'success', 'warning', 'failed', 'skipped')),
    CHECK (frequency_seconds > 0),
    CHECK (max_runtime_seconds > 0),
    CHECK (lock_timeout_seconds > 0),
    CHECK (retry_limit >= 0),
    CHECK (retry_backoff_seconds >= 0),
    CHECK (run_count >= 0),
    CHECK (success_count >= 0),
    CHECK (warning_count >= 0),
    CHECK (failed_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_schedule_due
    ON qmeta.worker_schedule(status, next_run_at, task_name);

CREATE TABLE IF NOT EXISTS qmeta.worker_lock (
    lock_name           VARCHAR(200) PRIMARY KEY,
    owner_id            VARCHAR(160) NOT NULL,
    acquired_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_worker_lock_expires
    ON qmeta.worker_lock(expires_at);

CREATE TABLE IF NOT EXISTS qmeta.worker_heartbeat (
    scheduler_id        VARCHAR(160) PRIMARY KEY,
    status              VARCHAR(24) NOT NULL DEFAULT 'running',
    host_name           VARCHAR(160),
    process_id          INTEGER,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    stopped_at          TIMESTAMPTZ,
    current_schedule_code VARCHAR(160),
    tick_count          BIGINT NOT NULL DEFAULT 0,
    run_count           BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('running', 'stopping', 'stopped', 'failed')),
    CHECK (tick_count >= 0),
    CHECK (run_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_heartbeat_status_seen
    ON qmeta.worker_heartbeat(status, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.worker_schedule_tick (
    tick_id             BIGSERIAL PRIMARY KEY,
    tick_code           VARCHAR(180) NOT NULL UNIQUE,
    scheduler_id        VARCHAR(160) NOT NULL,
    schedule_id         BIGINT REFERENCES qmeta.worker_schedule(schedule_id) ON DELETE SET NULL,
    schedule_code       VARCHAR(160) NOT NULL,
    task_name           VARCHAR(96) NOT NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'running',
    due_at              TIMESTAMPTZ,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    worker_run_id       BIGINT REFERENCES qmeta.worker_run(worker_run_id),
    lock_name           VARCHAR(200),
    lock_acquired       BOOLEAN NOT NULL DEFAULT FALSE,
    dry_run             BOOLEAN NOT NULL DEFAULT FALSE,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule')),
    CHECK (status IN ('running', 'success', 'warning', 'failed', 'skipped', 'skipped_locked')),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_schedule_tick_schedule_started
    ON qmeta.worker_schedule_tick(schedule_code, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_worker_schedule_tick_status_started
    ON qmeta.worker_schedule_tick(status, started_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES
    (
        'mu_usage_rollup_5m', 'usage_rollup', 300, 600, 900, 60,
        '{"cost_per_request":1.0,"cost_per_1000_rows":0.1}'::jsonb,
        '{"owner":"mu-default","purpose":"roll up API usage into api_usage_daily"}'::jsonb
    ),
    (
        'mu_alert_dispatch_1m', 'alert_dispatch', 60, 300, 300, 60,
        '{"alert_limit":50}'::jsonb,
        '{"owner":"mu-default","purpose":"dispatch open alerts to active channels"}'::jsonb
    ),
    (
        'mu_vendor_benchmark_daily', 'vendor_benchmark_schedule', 86400, 3600, 3600, 600,
        '{"include_manual_schedules":false}'::jsonb,
        '{"owner":"mu-default","purpose":"run due vendor benchmark schedules"}'::jsonb
    )
ON CONFLICT (schedule_code) DO NOTHING;
