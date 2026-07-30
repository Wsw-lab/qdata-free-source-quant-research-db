-- Nu-5: free source recovery health snapshots, SLA guardrails and runbook evidence.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health'
    ));

CREATE TABLE IF NOT EXISTS qmeta.free_source_recovery_health_snapshot (
    snapshot_id                   BIGSERIAL PRIMARY KEY,
    snapshot_code                 VARCHAR(180) NOT NULL UNIQUE,
    requested_by                  VARCHAR(128) NOT NULL DEFAULT 'nu5',
    trigger_mode                  VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                   VARCHAR(32) NOT NULL DEFAULT 'local',
    status                        VARCHAR(32) NOT NULL DEFAULT 'healthy',
    as_of_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    lookback_hours                INTEGER NOT NULL DEFAULT 24,
    approval_sla_hours            INTEGER NOT NULL DEFAULT 4,
    max_backlog_actions           INTEGER NOT NULL DEFAULT 50,
    max_failure_rate              NUMERIC(8, 4) NOT NULL DEFAULT 0.5000,
    max_stale_minutes             INTEGER NOT NULL DEFAULT 90,
    schedule_code                 VARCHAR(160) NOT NULL DEFAULT 'mu_free_source_recovery_execute_30m',
    pending_action_count          INTEGER NOT NULL DEFAULT 0,
    pending_retry_count           INTEGER NOT NULL DEFAULT 0,
    pending_manual_review_count   INTEGER NOT NULL DEFAULT 0,
    execution_count               INTEGER NOT NULL DEFAULT 0,
    recovered_count               INTEGER NOT NULL DEFAULT 0,
    failed_count                  INTEGER NOT NULL DEFAULT 0,
    suppressed_count              INTEGER NOT NULL DEFAULT 0,
    review_requested_count        INTEGER NOT NULL DEFAULT 0,
    blocked_count                 INTEGER NOT NULL DEFAULT 0,
    failure_rate                  NUMERIC(8, 4) NOT NULL DEFAULT 0,
    approval_pending_count        INTEGER NOT NULL DEFAULT 0,
    approval_overdue_count        INTEGER NOT NULL DEFAULT 0,
    backlog_count                 INTEGER NOT NULL DEFAULT 0,
    stale_schedule_count          INTEGER NOT NULL DEFAULT 0,
    recent_worker_run_count       INTEGER NOT NULL DEFAULT 0,
    latest_worker_status          VARCHAR(32),
    latest_schedule_status        VARCHAR(32),
    latest_execution_status       VARCHAR(32),
    health_issues                 TEXT[] NOT NULL DEFAULT '{}',
    runbook_actions               TEXT[] NOT NULL DEFAULT '{}',
    evidence                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                 TEXT,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('healthy', 'warning', 'critical', 'failed', 'skipped')),
    CHECK (lookback_hours > 0),
    CHECK (approval_sla_hours > 0),
    CHECK (max_backlog_actions >= 0),
    CHECK (max_failure_rate >= 0 AND max_failure_rate <= 1),
    CHECK (max_stale_minutes > 0),
    CHECK (pending_action_count >= 0),
    CHECK (pending_retry_count >= 0),
    CHECK (pending_manual_review_count >= 0),
    CHECK (execution_count >= 0),
    CHECK (recovered_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (suppressed_count >= 0),
    CHECK (review_requested_count >= 0),
    CHECK (blocked_count >= 0),
    CHECK (failure_rate >= 0 AND failure_rate <= 1),
    CHECK (approval_pending_count >= 0),
    CHECK (approval_overdue_count >= 0),
    CHECK (backlog_count >= 0),
    CHECK (stale_schedule_count >= 0),
    CHECK (recent_worker_run_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_health_lookup
    ON qmeta.free_source_recovery_health_snapshot(as_of_at DESC, status);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_health_sla
    ON qmeta.free_source_recovery_health_snapshot(approval_overdue_count, backlog_count, stale_schedule_count, as_of_at DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_health_schedule
    ON qmeta.free_source_recovery_health_snapshot(schedule_code, as_of_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'nu_free_source_recovery_health_15m', 'free_source_recovery_health', 900, 300, 300, 120,
    '{"nu5_lookback_hours":24,"nu5_approval_sla_hours":4,"nu5_max_backlog_actions":50,"nu5_max_failure_rate":0.5,"nu5_max_stale_minutes":90}'::jsonb,
    '{"owner":"nu5","purpose":"snapshot Mu-5 recovery health, approval SLA, backlog, failure rate and stale scheduler risk"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
