-- Rho-5: post-promotion shadow monitoring, rollback and degradation drill.

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
        'vendor_post_promotion_monitor'
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
        'vendor_post_promotion_monitor'
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
        'vendor_post_promotion_monitor'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_post_promotion_monitor_run (
    monitor_id                      BIGSERIAL PRIMARY KEY,
    monitor_code                    VARCHAR(180) NOT NULL UNIQUE,
    promotion_id                    BIGINT REFERENCES qmeta.vendor_primary_promotion_run(promotion_id) ON DELETE SET NULL,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    as_of_date                      DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                    VARCHAR(128) NOT NULL DEFAULT 'rho5',
    trigger_mode                    VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                     VARCHAR(32) NOT NULL DEFAULT 'local',
    monitor_scope                   VARCHAR(32) NOT NULL DEFAULT 'post_promotion',
    status                          VARCHAR(32) NOT NULL DEFAULT 'no_applied_promotion',
    rollback_mode                   VARCHAR(32) NOT NULL DEFAULT 'review_only',
    require_applied_promotion       BOOLEAN NOT NULL DEFAULT TRUE,
    rollback_allowed                BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_applied                BOOLEAN NOT NULL DEFAULT FALSE,
    dataset_count                   INTEGER NOT NULL DEFAULT 0,
    healthy_dataset_count           INTEGER NOT NULL DEFAULT 0,
    warning_dataset_count           INTEGER NOT NULL DEFAULT 0,
    rollback_recommended_count      INTEGER NOT NULL DEFAULT 0,
    rolled_back_dataset_count       INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count           INTEGER NOT NULL DEFAULT 0,
    no_applied_dataset_count        INTEGER NOT NULL DEFAULT 0,
    shadow_window_hours             INTEGER NOT NULL DEFAULT 24,
    max_conflict_rate_bps           NUMERIC(10, 4) NOT NULL DEFAULT 5.0000,
    max_failure_rate                NUMERIC(8, 6) NOT NULL DEFAULT 0.010000,
    max_stale_minutes               INTEGER NOT NULL DEFAULT 90,
    current_primary_source_codes    TEXT[] NOT NULL DEFAULT '{}',
    previous_primary_source_codes   TEXT[] NOT NULL DEFAULT '{}',
    monitor_score                   NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    required_actions                TEXT[] NOT NULL DEFAULT '{}',
    request_payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    started_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                     TIMESTAMPTZ,
    duration_ms                     INTEGER,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (monitor_scope IN ('shadow', 'post_promotion', 'rollback_drill')),
    CHECK (status IN ('healthy', 'warning', 'rollback_recommended', 'rolled_back', 'blocked', 'no_applied_promotion')),
    CHECK (rollback_mode IN ('review_only', 'dry_run', 'apply')),
    CHECK (dataset_count >= 0),
    CHECK (healthy_dataset_count >= 0),
    CHECK (warning_dataset_count >= 0),
    CHECK (rollback_recommended_count >= 0),
    CHECK (rolled_back_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (no_applied_dataset_count >= 0),
    CHECK (shadow_window_hours > 0),
    CHECK (max_conflict_rate_bps >= 0),
    CHECK (max_failure_rate >= 0),
    CHECK (max_stale_minutes >= 0),
    CHECK (monitor_score >= 0 AND monitor_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_monitor_lookup
    ON qmeta.vendor_post_promotion_monitor_run(source_id, as_of_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_monitor_status
    ON qmeta.vendor_post_promotion_monitor_run(status, monitor_scope, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_monitor_promotion
    ON qmeta.vendor_post_promotion_monitor_run(promotion_id, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_post_promotion_dataset_monitor (
    result_id                       BIGSERIAL PRIMARY KEY,
    result_code                     VARCHAR(180) NOT NULL UNIQUE,
    monitor_id                      BIGINT NOT NULL REFERENCES qmeta.vendor_post_promotion_monitor_run(monitor_id) ON DELETE CASCADE,
    promotion_id                    BIGINT REFERENCES qmeta.vendor_primary_promotion_run(promotion_id) ON DELETE SET NULL,
    promotion_result_id             BIGINT REFERENCES qmeta.vendor_primary_promotion_dataset_result(result_id) ON DELETE SET NULL,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                      BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    previous_primary_source_id      BIGINT REFERENCES qmeta.source_system(source_id),
    current_priority_id             BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    previous_priority_id            BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    as_of_date                      DATE NOT NULL DEFAULT CURRENT_DATE,
    monitor_scope                   VARCHAR(32) NOT NULL DEFAULT 'post_promotion',
    status                          VARCHAR(32) NOT NULL DEFAULT 'no_applied_promotion',
    rollback_mode                   VARCHAR(32) NOT NULL DEFAULT 'review_only',
    rollback_allowed                BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_applied                BOOLEAN NOT NULL DEFAULT FALSE,
    promotion_status                VARCHAR(32),
    promotion_role                  VARCHAR(32),
    routing_change_applied          BOOLEAN NOT NULL DEFAULT FALSE,
    current_primary_source_code     VARCHAR(64),
    current_priority                INTEGER,
    previous_primary_source_code    VARCHAR(64),
    previous_priority               INTEGER,
    target_priority                 INTEGER NOT NULL DEFAULT 0,
    shadow_status                   VARCHAR(32) NOT NULL DEFAULT 'not_available',
    shadow_conflict_rate_bps        NUMERIC(10, 4) NOT NULL DEFAULT 0,
    shadow_failure_rate             NUMERIC(8, 6) NOT NULL DEFAULT 0,
    shadow_latency_p95_ms           NUMERIC(12, 4),
    stale_minutes                   INTEGER NOT NULL DEFAULT 0,
    monitor_score                   NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    required_actions                TEXT[] NOT NULL DEFAULT '{}',
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (monitor_scope IN ('shadow', 'post_promotion', 'rollback_drill')),
    CHECK (status IN ('healthy', 'warning', 'rollback_recommended', 'rolled_back', 'blocked', 'no_applied_promotion')),
    CHECK (rollback_mode IN ('review_only', 'dry_run', 'apply')),
    CHECK (promotion_role IS NULL OR promotion_role IN ('blocked', 'validator', 'backup', 'primary')),
    CHECK (current_priority IS NULL OR current_priority >= 0),
    CHECK (previous_priority IS NULL OR previous_priority >= 0),
    CHECK (target_priority >= 0),
    CHECK (shadow_conflict_rate_bps >= 0),
    CHECK (shadow_failure_rate >= 0),
    CHECK (stale_minutes >= 0),
    CHECK (monitor_score >= 0 AND monitor_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_result_lookup
    ON qmeta.vendor_post_promotion_dataset_monitor(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_result_monitor
    ON qmeta.vendor_post_promotion_dataset_monitor(monitor_id, status, result_id DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_result_promotion
    ON qmeta.vendor_post_promotion_dataset_monitor(promotion_id, promotion_result_id);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'rho5_post_promotion_monitor_1h', 'vendor_post_promotion_monitor', 3600, 600, 600, 300,
    '{"rho5_monitor_scope":"post_promotion","rho5_require_applied_promotion":true,"rho5_apply_rollback":false,"rho5_shadow_window_hours":24,"rho5_max_conflict_rate_bps":5.0,"rho5_max_failure_rate":0.01,"rho5_max_stale_minutes":90}'::jsonb,
    '{"owner":"rho5","purpose":"monitor Pi-5 primary-source promotions with shadow reconciliation, rollback recommendation and review-only rollback drill by default"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
