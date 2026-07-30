-- Sigma-5: primary vendor production SLA, capacity, cost and scheduler stability.

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
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor'
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
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor'
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
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_primary_stability_snapshot (
    snapshot_id                                BIGSERIAL PRIMARY KEY,
    snapshot_code                              VARCHAR(180) NOT NULL UNIQUE,
    source_id                                  BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id                          BIGINT REFERENCES qmeta.source_system(source_id),
    promotion_id                               BIGINT REFERENCES qmeta.vendor_primary_promotion_run(promotion_id) ON DELETE SET NULL,
    post_promotion_monitor_id                  BIGINT REFERENCES qmeta.vendor_post_promotion_monitor_run(monitor_id) ON DELETE SET NULL,
    as_of_at                                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of_date                                 DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                               VARCHAR(128) NOT NULL DEFAULT 'sigma5',
    trigger_mode                               VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                                VARCHAR(32) NOT NULL DEFAULT 'local',
    monitor_scope                              VARCHAR(32) NOT NULL DEFAULT 'primary_source',
    status                                     VARCHAR(32) NOT NULL DEFAULT 'no_primary_promotion',
    stability_role                             VARCHAR(32) NOT NULL DEFAULT 'watch',
    lookback_hours                             INTEGER NOT NULL DEFAULT 24,
    capacity_window_days                       INTEGER NOT NULL DEFAULT 7,
    min_success_rate                           NUMERIC(8, 6) NOT NULL DEFAULT 0.995000,
    max_error_rate                             NUMERIC(8, 6) NOT NULL DEFAULT 0.005000,
    max_latency_p95_ms                         NUMERIC(12, 4) NOT NULL DEFAULT 2000,
    max_timeout_rate                           NUMERIC(8, 6) NOT NULL DEFAULT 0.010000,
    max_cost_units                             NUMERIC(18, 6) NOT NULL DEFAULT 500,
    max_scheduler_lag_minutes                  INTEGER NOT NULL DEFAULT 90,
    max_backlog_count                          INTEGER NOT NULL DEFAULT 50,
    max_post_promotion_no_applied_count        INTEGER NOT NULL DEFAULT 0,
    dataset_count                              INTEGER NOT NULL DEFAULT 0,
    primary_dataset_count                      INTEGER NOT NULL DEFAULT 0,
    healthy_dataset_count                      INTEGER NOT NULL DEFAULT 0,
    warning_dataset_count                      INTEGER NOT NULL DEFAULT 0,
    critical_dataset_count                     INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count                      INTEGER NOT NULL DEFAULT 0,
    no_primary_dataset_count                   INTEGER NOT NULL DEFAULT 0,
    api_request_count                          BIGINT NOT NULL DEFAULT 0,
    api_failed_count                           BIGINT NOT NULL DEFAULT 0,
    api_error_rate                             NUMERIC(10, 6) NOT NULL DEFAULT 0,
    api_success_rate                           NUMERIC(10, 6) NOT NULL DEFAULT 1,
    api_timeout_count                          BIGINT NOT NULL DEFAULT 0,
    api_timeout_rate                           NUMERIC(10, 6) NOT NULL DEFAULT 0,
    api_latency_p95_ms                         NUMERIC(12, 4) NOT NULL DEFAULT 0,
    rows_returned_count                        BIGINT NOT NULL DEFAULT 0,
    cost_units                                 NUMERIC(18, 6) NOT NULL DEFAULT 0,
    worker_run_count                           INTEGER NOT NULL DEFAULT 0,
    worker_failed_count                        INTEGER NOT NULL DEFAULT 0,
    worker_warning_count                       INTEGER NOT NULL DEFAULT 0,
    scheduler_lag_minutes                      INTEGER NOT NULL DEFAULT 0,
    backlog_count                              INTEGER NOT NULL DEFAULT 0,
    post_promotion_monitor_count               INTEGER NOT NULL DEFAULT 0,
    post_promotion_no_applied_count            INTEGER NOT NULL DEFAULT 0,
    post_promotion_rollback_recommended_count  INTEGER NOT NULL DEFAULT 0,
    open_capacity_alert_count                  INTEGER NOT NULL DEFAULT 0,
    open_critical_capacity_alert_count         INTEGER NOT NULL DEFAULT 0,
    stability_score                            NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                            TEXT[] NOT NULL DEFAULT '{}',
    required_actions                           TEXT[] NOT NULL DEFAULT '{}',
    request_payload                            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                           JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                              TEXT,
    started_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                                TIMESTAMPTZ,
    duration_ms                                INTEGER,
    created_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (monitor_scope IN ('primary_source', 'all_datasets', 'full_market')),
    CHECK (status IN ('healthy', 'warning', 'critical', 'blocked', 'no_primary_promotion')),
    CHECK (stability_role IN ('primary', 'watch', 'degraded', 'blocked')),
    CHECK (lookback_hours > 0),
    CHECK (capacity_window_days > 0),
    CHECK (min_success_rate >= 0 AND min_success_rate <= 1),
    CHECK (max_error_rate >= 0 AND max_error_rate <= 1),
    CHECK (max_latency_p95_ms >= 0),
    CHECK (max_timeout_rate >= 0 AND max_timeout_rate <= 1),
    CHECK (max_cost_units >= 0),
    CHECK (max_scheduler_lag_minutes >= 0),
    CHECK (max_backlog_count >= 0),
    CHECK (max_post_promotion_no_applied_count >= 0),
    CHECK (dataset_count >= 0),
    CHECK (primary_dataset_count >= 0),
    CHECK (healthy_dataset_count >= 0),
    CHECK (warning_dataset_count >= 0),
    CHECK (critical_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (no_primary_dataset_count >= 0),
    CHECK (api_request_count >= 0),
    CHECK (api_failed_count >= 0),
    CHECK (api_timeout_count >= 0),
    CHECK (rows_returned_count >= 0),
    CHECK (cost_units >= 0),
    CHECK (worker_run_count >= 0),
    CHECK (worker_failed_count >= 0),
    CHECK (worker_warning_count >= 0),
    CHECK (scheduler_lag_minutes >= 0),
    CHECK (backlog_count >= 0),
    CHECK (post_promotion_monitor_count >= 0),
    CHECK (post_promotion_no_applied_count >= 0),
    CHECK (post_promotion_rollback_recommended_count >= 0),
    CHECK (open_capacity_alert_count >= 0),
    CHECK (open_critical_capacity_alert_count >= 0),
    CHECK (stability_score >= 0 AND stability_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_snapshot_lookup
    ON qmeta.vendor_primary_stability_snapshot(source_id, as_of_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_snapshot_status
    ON qmeta.vendor_primary_stability_snapshot(status, stability_role, as_of_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_snapshot_promotion
    ON qmeta.vendor_primary_stability_snapshot(promotion_id, post_promotion_monitor_id);

CREATE TABLE IF NOT EXISTS qmeta.vendor_primary_stability_dataset_snapshot (
    dataset_snapshot_id              BIGSERIAL PRIMARY KEY,
    dataset_snapshot_code            VARCHAR(180) NOT NULL UNIQUE,
    snapshot_id                      BIGINT NOT NULL REFERENCES qmeta.vendor_primary_stability_snapshot(snapshot_id) ON DELETE CASCADE,
    source_id                        BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                       BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id                BIGINT REFERENCES qmeta.source_system(source_id),
    current_priority_id              BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    as_of_date                       DATE NOT NULL DEFAULT CURRENT_DATE,
    monitor_scope                    VARCHAR(32) NOT NULL DEFAULT 'primary_source',
    status                           VARCHAR(32) NOT NULL DEFAULT 'no_primary_promotion',
    stability_role                   VARCHAR(32) NOT NULL DEFAULT 'watch',
    entitlement_status               VARCHAR(32),
    allowed_role                     VARCHAR(32),
    production_use_allowed           BOOLEAN NOT NULL DEFAULT FALSE,
    schema_status                    VARCHAR(32),
    current_primary_source_code      VARCHAR(64),
    current_priority                 INTEGER,
    is_primary_route                 BOOLEAN NOT NULL DEFAULT FALSE,
    promotion_status                 VARCHAR(32),
    promotion_result_status          VARCHAR(32),
    post_promotion_status            VARCHAR(32),
    api_request_count                BIGINT NOT NULL DEFAULT 0,
    api_failed_count                 BIGINT NOT NULL DEFAULT 0,
    api_error_rate                   NUMERIC(10, 6) NOT NULL DEFAULT 0,
    api_success_rate                 NUMERIC(10, 6) NOT NULL DEFAULT 1,
    api_timeout_count                BIGINT NOT NULL DEFAULT 0,
    api_timeout_rate                 NUMERIC(10, 6) NOT NULL DEFAULT 0,
    api_latency_p95_ms               NUMERIC(12, 4) NOT NULL DEFAULT 0,
    rows_returned_count              BIGINT NOT NULL DEFAULT 0,
    cost_units                       NUMERIC(18, 6) NOT NULL DEFAULT 0,
    stability_score                  NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                  TEXT[] NOT NULL DEFAULT '{}',
    required_actions                 TEXT[] NOT NULL DEFAULT '{}',
    evidence                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                    TEXT,
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (monitor_scope IN ('primary_source', 'all_datasets', 'full_market')),
    CHECK (status IN ('healthy', 'warning', 'critical', 'blocked', 'no_primary_promotion')),
    CHECK (stability_role IN ('primary', 'watch', 'degraded', 'blocked')),
    CHECK (current_priority IS NULL OR current_priority >= 0),
    CHECK (api_request_count >= 0),
    CHECK (api_failed_count >= 0),
    CHECK (api_timeout_count >= 0),
    CHECK (rows_returned_count >= 0),
    CHECK (cost_units >= 0),
    CHECK (stability_score >= 0 AND stability_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_dataset_lookup
    ON qmeta.vendor_primary_stability_dataset_snapshot(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_dataset_snapshot
    ON qmeta.vendor_primary_stability_dataset_snapshot(snapshot_id, status, dataset_snapshot_id DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_dataset_role
    ON qmeta.vendor_primary_stability_dataset_snapshot(stability_role, is_primary_route, created_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'sigma5_vendor_primary_stability_1h', 'vendor_primary_stability_monitor', 3600, 600, 600, 300,
    '{"sigma5_monitor_scope":"primary_source","sigma5_lookback_hours":24,"sigma5_capacity_window_days":7,"sigma5_min_success_rate":0.995,"sigma5_max_error_rate":0.005,"sigma5_max_latency_p95_ms":2000,"sigma5_max_timeout_rate":0.01,"sigma5_max_cost_units":500,"sigma5_max_scheduler_lag_minutes":90,"sigma5_max_backlog_count":50,"sigma5_max_post_promotion_no_applied_count":0}'::jsonb,
    '{"owner":"sigma5","purpose":"monitor primary vendor production SLA, API capacity, cost envelope and scheduler stability after Pi-5/Rho-5"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
