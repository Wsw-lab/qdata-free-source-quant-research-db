-- A 股量化数据平台 Lambda-5：免费源恢复编排、重试、告警和人工复核

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery'));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery'));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery'));

ALTER TABLE qmeta.alert_event
    DROP CONSTRAINT IF EXISTS alert_event_alert_type_check;

ALTER TABLE qmeta.alert_event
    ADD CONSTRAINT alert_event_alert_type_check
    CHECK (alert_type IN (
        'missing_run',
        'pipeline_status',
        'pipeline_late',
        'completeness_below_sla',
        'conflict_rate_above_sla',
        'api_error_rate_above_sla',
        'duration_above_sla',
        'vendor_score_below_sla',
        'vendor_conflict_rate_above_sla',
        'vendor_failure_rate_above_sla',
        'vendor_latency_above_sla',
        'provider_error_count_above_sla',
        'budget_threshold_warning',
        'budget_exceeded',
        'budget_blocked',
        'budget_usage_spike',
        'runtime_metric_warning',
        'runtime_metric_critical',
        'runtime_capacity_warning',
        'runtime_capacity_critical',
        'runtime_daily_degraded',
        'free_source_recovery_required'
    ));

CREATE TABLE IF NOT EXISTS qmeta.free_source_recovery_run (
    recovery_run_id                BIGSERIAL PRIMARY KEY,
    recovery_code                  VARCHAR(180) NOT NULL UNIQUE,
    requested_by                   VARCHAR(128) NOT NULL DEFAULT 'lambda5',
    trigger_mode                   VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                    VARCHAR(32) NOT NULL DEFAULT 'local',
    as_of_date                     DATE NOT NULL,
    lookback_hours                 INTEGER NOT NULL DEFAULT 24,
    dry_run                        BOOLEAN NOT NULL DEFAULT FALSE,
    status                         VARCHAR(32) NOT NULL DEFAULT 'planned',
    snapshot_count                 INTEGER NOT NULL DEFAULT 0,
    action_count                   INTEGER NOT NULL DEFAULT 0,
    retry_action_count             INTEGER NOT NULL DEFAULT 0,
    alert_action_count             INTEGER NOT NULL DEFAULT 0,
    manual_review_action_count     INTEGER NOT NULL DEFAULT 0,
    suppressed_action_count        INTEGER NOT NULL DEFAULT 0,
    blocked_action_count           INTEGER NOT NULL DEFAULT 0,
    created_alert_count            INTEGER NOT NULL DEFAULT 0,
    blocking_issues                TEXT[] NOT NULL DEFAULT '{}',
    next_actions                   TEXT[] NOT NULL DEFAULT '{}',
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                  TEXT,
    started_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                    TIMESTAMPTZ,
    duration_ms                    INTEGER,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (lookback_hours > 0),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'skipped')),
    CHECK (snapshot_count >= 0),
    CHECK (action_count >= 0),
    CHECK (retry_action_count >= 0),
    CHECK (alert_action_count >= 0),
    CHECK (manual_review_action_count >= 0),
    CHECK (suppressed_action_count >= 0),
    CHECK (blocked_action_count >= 0),
    CHECK (created_alert_count >= 0),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.free_source_recovery_action (
    action_id                      BIGSERIAL PRIMARY KEY,
    action_code                    VARCHAR(180) NOT NULL UNIQUE,
    recovery_run_id                BIGINT NOT NULL REFERENCES qmeta.free_source_recovery_run(recovery_run_id) ON DELETE CASCADE,
    snapshot_id                    BIGINT REFERENCES qmeta.free_source_reliability_snapshot(snapshot_id) ON DELETE SET NULL,
    source_id                      BIGINT REFERENCES qmeta.source_system(source_id),
    dataset_id                     BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    action_type                    VARCHAR(32) NOT NULL,
    status                         VARCHAR(32) NOT NULL DEFAULT 'planned',
    severity                       VARCHAR(16) NOT NULL DEFAULT 'low',
    reason_code                    VARCHAR(96) NOT NULL,
    recommended_role               VARCHAR(32) NOT NULL DEFAULT 'research_only',
    reliability_score              NUMERIC(8, 4),
    retry_after_minutes            INTEGER,
    next_retry_at                  TIMESTAMPTZ,
    alert_id                       BIGINT REFERENCES qmeta.alert_event(alert_id) ON DELETE SET NULL,
    degradation_reasons            TEXT[] NOT NULL DEFAULT '{}',
    recovery_actions               TEXT[] NOT NULL DEFAULT '{}',
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                  TEXT,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (action_type IN ('retry_canary', 'create_alert', 'manual_review', 'observe', 'suppress')),
    CHECK (status IN ('planned', 'skipped', 'scheduled', 'alerted', 'review_required', 'suppressed', 'failed', 'success')),
    CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    CHECK (reliability_score IS NULL OR (reliability_score >= 0 AND reliability_score <= 100)),
    CHECK (retry_after_minutes IS NULL OR retry_after_minutes > 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_run_lookup
    ON qmeta.free_source_recovery_run(started_at DESC, status, trigger_mode);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_action_run
    ON qmeta.free_source_recovery_action(recovery_run_id, status, action_type);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_action_source_dataset
    ON qmeta.free_source_recovery_action(source_id, dataset_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_action_severity
    ON qmeta.free_source_recovery_action(severity, status, created_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'mu_free_source_recovery_30m', 'free_source_recovery', 1800, 600, 900, 300,
    '{"free_source_lookback_hours":72,"free_source_max_actions":50,"free_source_min_retry_score":75.0,"free_source_write_alerts":true}'::jsonb,
    '{"owner":"lambda5","purpose":"schedule retry, alert and manual review actions from Kappa-5 free-source reliability scores"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
