-- Psi-5: source-route incident automation from Chi-5 circuit and probe signals.

ALTER TABLE qmeta.automation_action
    DROP CONSTRAINT IF EXISTS automation_action_source_type_check;

ALTER TABLE qmeta.automation_action
    ADD CONSTRAINT automation_action_source_type_check
    CHECK (source_type IN (
        'phi_decision',
        'chi_governance_action',
        'manual',
        'route_circuit_breaker',
        'route_recovery_probe',
        'route_health_snapshot'
    ));

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
        'route_incident_automation'
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
        'route_incident_automation'
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
        'route_incident_automation'
    ));

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_action (
    incident_action_id              BIGSERIAL PRIMARY KEY,
    incident_action_code            VARCHAR(260) NOT NULL UNIQUE,
    automation_run_id               BIGINT REFERENCES qmeta.automation_run(automation_run_id) ON DELETE SET NULL,
    automation_action_id            BIGINT REFERENCES qmeta.automation_action(automation_action_id) ON DELETE SET NULL,
    idempotency_key                 VARCHAR(260) NOT NULL UNIQUE,
    source_signal_type              VARCHAR(32) NOT NULL,
    breaker_id                      BIGINT REFERENCES qmeta.source_route_circuit_breaker(breaker_id) ON DELETE SET NULL,
    snapshot_id                     BIGINT REFERENCES qmeta.source_route_health_snapshot(snapshot_id) ON DELETE SET NULL,
    probe_id                        BIGINT REFERENCES qmeta.source_route_recovery_probe(probe_id) ON DELETE SET NULL,
    dataset_id                      BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE CASCADE,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id) ON DELETE CASCADE,
    action_type                     VARCHAR(64) NOT NULL,
    safety_level                    VARCHAR(24) NOT NULL DEFAULT 'medium',
    execution_mode                  VARCHAR(24) NOT NULL DEFAULT 'dry_run',
    status                          VARCHAR(32) NOT NULL DEFAULT 'planned',
    approval_required               BOOLEAN NOT NULL DEFAULT FALSE,
    owner                           VARCHAR(128),
    reason                          TEXT NOT NULL,
    planned_effect                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    executed_effect                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollback_hint                   TEXT,
    route_status                    VARCHAR(32),
    circuit_status                  VARCHAR(32),
    probe_status                    VARCHAR(32),
    open_until                      TIMESTAMPTZ,
    success_rate                    NUMERIC(8, 4),
    failure_rate                    NUMERIC(8, 4),
    fallback_rate                   NUMERIC(8, 4),
    empty_rate                      NUMERIC(8, 4),
    latency_p95_ms                  NUMERIC(14, 4),
    health_issues                   TEXT[] NOT NULL DEFAULT '{}',
    details                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_signal_type IN ('circuit_open', 'recovery_failed', 'recovered', 'health_degraded')),
    CHECK (action_type IN (
        'repair_data_quality',
        'degrade_vendor',
        'pause_product',
        'freeze_budget',
        'escalate_commercial',
        'review_access_policy',
        'review_budget',
        'rotate_token',
        'contact_owner',
        'notify_owner',
        'monitor'
    )),
    CHECK (safety_level IN ('low', 'medium', 'high', 'critical')),
    CHECK (execution_mode IN ('dry_run', 'execute')),
    CHECK (status IN ('planned', 'approval_required', 'success', 'failed', 'skipped')),
    CHECK (success_rate IS NULL OR (success_rate >= 0 AND success_rate <= 1)),
    CHECK (failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)),
    CHECK (fallback_rate IS NULL OR (fallback_rate >= 0 AND fallback_rate <= 1)),
    CHECK (empty_rate IS NULL OR (empty_rate >= 0 AND empty_rate <= 1)),
    CHECK (latency_p95_ms IS NULL OR latency_p95_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_action_lookup
    ON qmeta.source_route_incident_action(dataset_id, source_id, source_signal_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_action_status
    ON qmeta.source_route_incident_action(status, safety_level, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_action_automation
    ON qmeta.source_route_incident_action(automation_run_id, automation_action_id);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'psi5_route_incident_automation_15m', 'route_incident_automation', 900, 300, 300, 120,
    '{"psi5_route_lookback_hours":24,"psi5_route_max_actions":50,"psi5_route_execution_mode":"execute","psi5_route_approve_high_risk":false,"psi5_route_owner":"platform-ops","psi5_route_include_recovered":true}'::jsonb,
    '{"owner":"psi5","purpose":"turn Chi-5 route circuit/probe signals into approval-aware automation actions and notification-ready incident records"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
