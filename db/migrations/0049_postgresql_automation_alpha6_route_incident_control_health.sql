-- Alpha-6: route incident control health snapshots, SLA guardrails and runbook evidence.

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
        'route_incident_control_health'
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
        'route_incident_control_health'
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
        'route_incident_control_health'
    ));

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_control_health_snapshot (
    snapshot_id                    BIGSERIAL PRIMARY KEY,
    snapshot_code                  VARCHAR(180) NOT NULL UNIQUE,
    requested_by                   VARCHAR(128) NOT NULL DEFAULT 'alpha6',
    trigger_mode                   VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                    VARCHAR(32) NOT NULL DEFAULT 'local',
    status                         VARCHAR(24) NOT NULL DEFAULT 'healthy',
    as_of_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    lookback_hours                 INTEGER NOT NULL DEFAULT 24,
    approval_sla_hours             INTEGER NOT NULL DEFAULT 4,
    max_pending_controls           INTEGER NOT NULL DEFAULT 50,
    max_failed_execution_rate      NUMERIC(8, 4) NOT NULL DEFAULT 0.1000,
    max_blocked_receipt_rate       NUMERIC(8, 4) NOT NULL DEFAULT 0.8000,
    max_stale_minutes              INTEGER NOT NULL DEFAULT 90,
    schedule_code                  VARCHAR(160) NOT NULL DEFAULT 'omega5_route_incident_control_15m',
    control_count                  INTEGER NOT NULL DEFAULT 0,
    pending_control_count          INTEGER NOT NULL DEFAULT 0,
    approval_pending_count         INTEGER NOT NULL DEFAULT 0,
    approval_overdue_count         INTEGER NOT NULL DEFAULT 0,
    notification_blocked_count     INTEGER NOT NULL DEFAULT 0,
    notification_success_count     INTEGER NOT NULL DEFAULT 0,
    blocked_receipt_rate           NUMERIC(8, 4) NOT NULL DEFAULT 0,
    dispatch_failed_count          INTEGER NOT NULL DEFAULT 0,
    execution_count                INTEGER NOT NULL DEFAULT 0,
    executed_count                 INTEGER NOT NULL DEFAULT 0,
    failed_execution_count         INTEGER NOT NULL DEFAULT 0,
    execution_failure_rate         NUMERIC(8, 4) NOT NULL DEFAULT 0,
    rollback_planned_count         INTEGER NOT NULL DEFAULT 0,
    missing_rollback_count         INTEGER NOT NULL DEFAULT 0,
    stale_schedule_count           INTEGER NOT NULL DEFAULT 0,
    recent_worker_run_count        INTEGER NOT NULL DEFAULT 0,
    latest_worker_status           VARCHAR(32),
    latest_schedule_status         VARCHAR(32),
    latest_control_stage           VARCHAR(32),
    health_issues                  TEXT[] NOT NULL DEFAULT '{}',
    runbook_actions                TEXT[] NOT NULL DEFAULT '{}',
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                  TEXT,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('healthy', 'warning', 'critical', 'failed', 'skipped')),
    CHECK (lookback_hours > 0),
    CHECK (approval_sla_hours > 0),
    CHECK (max_pending_controls >= 0),
    CHECK (max_failed_execution_rate >= 0 AND max_failed_execution_rate <= 1),
    CHECK (max_blocked_receipt_rate >= 0 AND max_blocked_receipt_rate <= 1),
    CHECK (max_stale_minutes > 0),
    CHECK (control_count >= 0),
    CHECK (pending_control_count >= 0),
    CHECK (approval_pending_count >= 0),
    CHECK (approval_overdue_count >= 0),
    CHECK (notification_blocked_count >= 0),
    CHECK (notification_success_count >= 0),
    CHECK (blocked_receipt_rate >= 0 AND blocked_receipt_rate <= 1),
    CHECK (dispatch_failed_count >= 0),
    CHECK (execution_count >= 0),
    CHECK (executed_count >= 0),
    CHECK (failed_execution_count >= 0),
    CHECK (execution_failure_rate >= 0 AND execution_failure_rate <= 1),
    CHECK (rollback_planned_count >= 0),
    CHECK (missing_rollback_count >= 0),
    CHECK (stale_schedule_count >= 0),
    CHECK (recent_worker_run_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_control_health_lookup
    ON qmeta.source_route_incident_control_health_snapshot(as_of_at DESC, status);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_control_health_sla
    ON qmeta.source_route_incident_control_health_snapshot(approval_overdue_count, pending_control_count, stale_schedule_count, as_of_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_control_health_schedule
    ON qmeta.source_route_incident_control_health_snapshot(schedule_code, as_of_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'alpha6_route_incident_control_health_15m', 'route_incident_control_health', 900, 300, 300, 120,
    '{"alpha6_route_lookback_hours":24,"alpha6_route_approval_sla_hours":4,"alpha6_route_max_pending_controls":50,"alpha6_route_max_failed_execution_rate":0.1,"alpha6_route_max_blocked_receipt_rate":0.8,"alpha6_route_max_stale_minutes":90,"alpha6_route_requested_by":"alpha6","alpha6_route_environment":"local","alpha6_route_control_schedule_code":"omega5_route_incident_control_15m"}'::jsonb,
    '{"owner":"alpha6","purpose":"snapshot Omega-5 route incident control backlog, approval SLA, WeCom receipt, execution failure, rollback and schedule health"}'::jsonb
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
