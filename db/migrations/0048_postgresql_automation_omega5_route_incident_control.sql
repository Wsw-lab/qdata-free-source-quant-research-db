-- Omega-5: route incident approval, notification, execution and rollback control loop.

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
        'route_incident_control'
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
        'route_incident_control'
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
        'route_incident_control'
    ));

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_control (
    control_id                  BIGSERIAL PRIMARY KEY,
    control_code                VARCHAR(280) NOT NULL UNIQUE,
    incident_action_id          BIGINT NOT NULL REFERENCES qmeta.source_route_incident_action(incident_action_id) ON DELETE CASCADE,
    automation_action_id        BIGINT NOT NULL REFERENCES qmeta.automation_action(automation_action_id) ON DELETE CASCADE,
    approval_id                 BIGINT REFERENCES qmeta.automation_approval(approval_id) ON DELETE SET NULL,
    dispatch_id                 BIGINT REFERENCES qmeta.automation_external_dispatch(dispatch_id) ON DELETE SET NULL,
    attempt_id                  BIGINT REFERENCES qmeta.automation_execution_attempt(attempt_id) ON DELETE SET NULL,
    receipt_id                  BIGINT REFERENCES qmeta.automation_live_provider_receipt(receipt_id) ON DELETE SET NULL,
    rollback_id                 BIGINT REFERENCES qmeta.automation_rollback(rollback_id) ON DELETE SET NULL,
    control_stage               VARCHAR(32) NOT NULL DEFAULT 'planned',
    approval_status             VARCHAR(24),
    dispatch_status             VARCHAR(32),
    attempt_status              VARCHAR(32),
    receipt_status              VARCHAR(32),
    rollback_status             VARCHAR(32),
    owner                       VARCHAR(128),
    requested_by                VARCHAR(128) NOT NULL DEFAULT 'omega5',
    approved_by                 VARCHAR(128),
    executed_by                 VARCHAR(128),
    requires_wecom              BOOLEAN NOT NULL DEFAULT TRUE,
    approval_required           BOOLEAN NOT NULL DEFAULT TRUE,
    execution_mode              VARCHAR(32) NOT NULL DEFAULT 'review_only',
    notification_channel        VARCHAR(128) NOT NULL DEFAULT 'delta2-wecom-live-profile',
    control_reason              TEXT NOT NULL,
    planned_control             JSONB NOT NULL DEFAULT '{}'::jsonb,
    executed_control            JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollback_evidence           JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message               TEXT,
    closed_at                   TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (incident_action_id),
    CHECK (control_stage IN (
        'planned',
        'approval_requested',
        'notification_recorded',
        'approved',
        'executed',
        'rollback_planned',
        'closed',
        'blocked',
        'failed',
        'skipped'
    )),
    CHECK (approval_status IS NULL OR approval_status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
    CHECK (dispatch_status IS NULL OR dispatch_status IN ('planned', 'sent', 'acknowledged', 'failed', 'retry_scheduled', 'dead_letter', 'recovered', 'suppressed')),
    CHECK (attempt_status IS NULL OR attempt_status IN ('queued', 'running', 'success', 'failed', 'skipped', 'approval_required', 'retry_scheduled')),
    CHECK (receipt_status IS NULL OR receipt_status IN ('planned', 'success', 'failed', 'blocked', 'skipped')),
    CHECK (rollback_status IS NULL OR rollback_status IN ('planned', 'success', 'failed', 'skipped')),
    CHECK (execution_mode IN ('review_only', 'dry_run', 'execute'))
);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_control_stage
    ON qmeta.source_route_incident_control(control_stage, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_control_action
    ON qmeta.source_route_incident_control(automation_action_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_control_approval
    ON qmeta.source_route_incident_control(approval_status, dispatch_status, attempt_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_control_details
    ON qmeta.source_route_incident_control USING GIN(details);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'omega5_route_incident_control_15m', 'route_incident_control', 900, 300, 300, 120,
    '{"omega5_route_lookback_hours":24,"omega5_route_max_controls":50,"omega5_route_execution_mode":"review_only","omega5_route_auto_approve":false,"omega5_route_requested_by":"omega5","omega5_route_approval_sla_hours":4,"omega5_route_notify_wecom":true,"omega5_route_allow_wecom_external":false,"omega5_route_create_rollback":true}'::jsonb,
    '{"owner":"omega5","purpose":"connect Psi-5 route incident actions to approval, WeCom notification receipts, execution attempts and rollback plans"}'::jsonb
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
