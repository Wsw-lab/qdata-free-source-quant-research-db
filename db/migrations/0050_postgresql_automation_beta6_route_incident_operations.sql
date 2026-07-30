-- Beta-6: route incident approval queue, notification dedupe and pressure-test evidence.

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
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer',
        'vendor_route_weight_executor',
        'source_route_feedback_monitor',
        'route_incident_automation',
        'route_incident_control',
        'route_incident_control_health',
        'route_incident_operations'
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
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer',
        'vendor_route_weight_executor',
        'source_route_feedback_monitor',
        'route_incident_automation',
        'route_incident_control',
        'route_incident_control_health',
        'route_incident_operations'
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
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer',
        'vendor_route_weight_executor',
        'source_route_feedback_monitor',
        'route_incident_automation',
        'route_incident_control',
        'route_incident_control_health',
        'route_incident_operations'
    ));

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_operation_batch (
    batch_id                         BIGSERIAL PRIMARY KEY,
    batch_code                       VARCHAR(180) NOT NULL UNIQUE,
    requested_by                     VARCHAR(128) NOT NULL DEFAULT 'beta6',
    trigger_mode                     VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                      VARCHAR(32) NOT NULL DEFAULT 'local',
    operation_mode                   VARCHAR(32) NOT NULL DEFAULT 'approval_queue',
    approval_decision                VARCHAR(16) NOT NULL DEFAULT 'approve',
    notification_policy              VARCHAR(32) NOT NULL DEFAULT 'dedupe_digest',
    stress_scope                     VARCHAR(32) NOT NULL DEFAULT 'full_market',
    status                           VARCHAR(24) NOT NULL DEFAULT 'planned',
    started_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                      TIMESTAMPTZ,
    duration_ms                      INTEGER,
    lookback_hours                   INTEGER NOT NULL DEFAULT 24,
    max_controls                     INTEGER NOT NULL DEFAULT 100,
    dry_run                          BOOLEAN NOT NULL DEFAULT TRUE,
    apply_decisions                  BOOLEAN NOT NULL DEFAULT FALSE,
    notify_wecom                     BOOLEAN NOT NULL DEFAULT FALSE,
    allow_wecom_external             BOOLEAN NOT NULL DEFAULT FALSE,
    candidate_count                  INTEGER NOT NULL DEFAULT 0,
    eligible_count                   INTEGER NOT NULL DEFAULT 0,
    approved_count                   INTEGER NOT NULL DEFAULT 0,
    rejected_count                   INTEGER NOT NULL DEFAULT 0,
    held_count                       INTEGER NOT NULL DEFAULT 0,
    skipped_count                    INTEGER NOT NULL DEFAULT 0,
    failed_count                     INTEGER NOT NULL DEFAULT 0,
    high_risk_count                  INTEGER NOT NULL DEFAULT 0,
    overdue_count                    INTEGER NOT NULL DEFAULT 0,
    blocked_receipt_count            INTEGER NOT NULL DEFAULT 0,
    notification_group_count         INTEGER NOT NULL DEFAULT 0,
    deduped_notification_count       INTEGER NOT NULL DEFAULT 0,
    suppressed_notification_count    INTEGER NOT NULL DEFAULT 0,
    critical_notification_count      INTEGER NOT NULL DEFAULT 0,
    stress_dataset_count             INTEGER NOT NULL DEFAULT 0,
    stress_source_count              INTEGER NOT NULL DEFAULT 0,
    stress_scenario_count            INTEGER NOT NULL DEFAULT 0,
    operation_issues                 TEXT[] NOT NULL DEFAULT '{}',
    required_actions                 TEXT[] NOT NULL DEFAULT '{}',
    evidence                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                    TEXT,
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (operation_mode IN ('approval_queue', 'batch_approval', 'pressure_test', 'smoke')),
    CHECK (approval_decision IN ('approve', 'reject', 'hold')),
    CHECK (notification_policy IN ('dedupe_digest', 'critical_only', 'none')),
    CHECK (stress_scope IN ('full_market', 'active_sources', 'smoke')),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'skipped')),
    CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CHECK (lookback_hours > 0),
    CHECK (max_controls > 0),
    CHECK (candidate_count >= 0),
    CHECK (eligible_count >= 0),
    CHECK (approved_count >= 0),
    CHECK (rejected_count >= 0),
    CHECK (held_count >= 0),
    CHECK (skipped_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (high_risk_count >= 0),
    CHECK (overdue_count >= 0),
    CHECK (blocked_receipt_count >= 0),
    CHECK (notification_group_count >= 0),
    CHECK (deduped_notification_count >= 0),
    CHECK (suppressed_notification_count >= 0),
    CHECK (critical_notification_count >= 0),
    CHECK (stress_dataset_count >= 0),
    CHECK (stress_source_count >= 0),
    CHECK (stress_scenario_count >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_operation_item (
    item_id                         BIGSERIAL PRIMARY KEY,
    batch_id                        BIGINT NOT NULL REFERENCES qmeta.source_route_incident_operation_batch(batch_id) ON DELETE CASCADE,
    batch_code                      VARCHAR(180) NOT NULL,
    control_id                      BIGINT REFERENCES qmeta.source_route_incident_control(control_id) ON DELETE SET NULL,
    approval_id                     BIGINT REFERENCES qmeta.automation_approval(approval_id) ON DELETE SET NULL,
    control_code                    VARCHAR(280),
    approval_code                   VARCHAR(260),
    incident_action_code            VARCHAR(280),
    dataset_code                    VARCHAR(128),
    source_code                     VARCHAR(128),
    source_signal_type              VARCHAR(64),
    safety_level                    VARCHAR(24),
    control_stage_before            VARCHAR(32),
    control_stage_after             VARCHAR(32),
    approval_status_before          VARCHAR(24),
    approval_status_after           VARCHAR(24),
    receipt_status                  VARCHAR(32),
    rollback_status                 VARCHAR(32),
    operation_decision              VARCHAR(16) NOT NULL DEFAULT 'hold',
    operation_status                VARCHAR(24) NOT NULL DEFAULT 'preview',
    notification_group_key          VARCHAR(260),
    suppress_notification           BOOLEAN NOT NULL DEFAULT FALSE,
    priority_score                  NUMERIC(10, 2) NOT NULL DEFAULT 0,
    reason                          TEXT,
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (batch_id, control_id),
    CHECK (operation_decision IN ('approve', 'reject', 'hold', 'skip')),
    CHECK (operation_status IN ('preview', 'applied', 'skipped', 'failed')),
    CHECK (priority_score >= 0)
);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_operation_batch_lookup
    ON qmeta.source_route_incident_operation_batch(started_at DESC, status, approval_decision);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_operation_batch_pressure
    ON qmeta.source_route_incident_operation_batch(stress_scope, stress_scenario_count, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_operation_item_queue
    ON qmeta.source_route_incident_operation_item(batch_code, operation_status, operation_decision, priority_score DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_operation_item_control
    ON qmeta.source_route_incident_operation_item(control_code, approval_code, created_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'beta6_route_incident_operations_30m', 'route_incident_operations', 1800, 300, 300, 120,
    '{"beta6_route_lookback_hours":24,"beta6_route_max_controls":100,"beta6_route_approval_decision":"hold","beta6_route_apply_decisions":false,"beta6_route_requested_by":"beta6","beta6_route_environment":"local","beta6_route_notification_policy":"dedupe_digest","beta6_route_stress_scope":"full_market","beta6_route_notify_wecom":false,"beta6_route_allow_wecom_external":false}'::jsonb,
    '{"owner":"beta6","purpose":"build route incident approval queue batches, dedupe notification digests and full-market pressure-test evidence"}'::jsonb
)
ON CONFLICT (schedule_code) DO UPDATE SET
    task_name = EXCLUDED.task_name,
    frequency_seconds = EXCLUDED.frequency_seconds,
    max_runtime_seconds = EXCLUDED.max_runtime_seconds,
    lock_timeout_seconds = EXCLUDED.lock_timeout_seconds,
    retry_backoff_seconds = EXCLUDED.retry_backoff_seconds,
    task_args = EXCLUDED.task_args,
    details = EXCLUDED.details,
    updated_at = now();
