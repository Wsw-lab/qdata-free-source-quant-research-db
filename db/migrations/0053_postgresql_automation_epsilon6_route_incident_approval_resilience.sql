-- Epsilon-6: concurrency, immutable audit and recovery for route incident approvals.

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
        'route_incident_operations',
        'route_incident_approval_governance',
        'route_incident_approval_resilience'
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
        'route_incident_operations',
        'route_incident_approval_governance',
        'route_incident_approval_resilience'
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
        'route_incident_operations',
        'route_incident_approval_governance',
        'route_incident_approval_resilience'
    ));

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_lock_event (
    lock_event_id              BIGSERIAL PRIMARY KEY,
    lock_event_code            VARCHAR(180) NOT NULL UNIQUE,
    lock_scope                 VARCHAR(320) NOT NULL,
    lock_key                   BIGINT NOT NULL,
    provider_code              VARCHAR(32) NOT NULL DEFAULT 'wecom',
    nonce                      VARCHAR(160),
    request_hash               VARCHAR(96),
    callback_code              VARCHAR(180),
    command_code               VARCHAR(180),
    control_code               VARCHAR(280),
    approval_code              VARCHAR(260),
    batch_code                 VARCHAR(180),
    requested_by               VARCHAR(128),
    signer_code                VARCHAR(128),
    lock_status                VARCHAR(24) NOT NULL DEFAULT 'acquired',
    wait_ms                    INTEGER NOT NULL DEFAULT 0,
    held_ms                    INTEGER,
    concurrency_token          VARCHAR(96) NOT NULL,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    started_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                TIMESTAMPTZ,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (provider_code IN ('wecom', 'admin', 'worker', 'smoke')),
    CHECK (lock_status IN ('acquired', 'busy', 'released', 'failed')),
    CHECK (wait_ms >= 0),
    CHECK (held_ms IS NULL OR held_ms >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_state_transition (
    transition_id              BIGSERIAL PRIMARY KEY,
    transition_code            VARCHAR(180) NOT NULL UNIQUE,
    callback_id                BIGINT REFERENCES qmeta.source_route_incident_approval_callback(callback_id) ON DELETE SET NULL,
    command_id                 BIGINT REFERENCES qmeta.source_route_incident_approval_command(command_id) ON DELETE SET NULL,
    callback_code              VARCHAR(180),
    command_code               VARCHAR(180),
    control_code               VARCHAR(280),
    approval_code              VARCHAR(260),
    batch_code                 VARCHAR(180),
    requested_by               VARCHAR(128),
    signer_code                VARCHAR(128),
    requested_decision         VARCHAR(16),
    approval_status_before     VARCHAR(32),
    control_stage_before       VARCHAR(32),
    approval_status_after      VARCHAR(32),
    control_stage_after        VARCHAR(32),
    transition_status          VARCHAR(24) NOT NULL DEFAULT 'allowed',
    reason_code                VARCHAR(48) NOT NULL DEFAULT 'valid_pending_transition',
    state_version              INTEGER NOT NULL DEFAULT 1,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    observed_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (requested_decision IS NULL OR requested_decision IN ('approve', 'reject', 'hold')),
    CHECK (transition_status IN ('allowed', 'applied', 'blocked', 'noop', 'failed')),
    CHECK (reason_code IN (
        'valid_pending_transition',
        'hold_keeps_pending',
        'target_missing',
        'invalid_terminal_state',
        'governance_denied',
        'replay_rejected',
        'signature_rejected',
        'delta6_failed',
        'status_mismatch',
        'lock_busy',
        'audit_only'
    )),
    CHECK (state_version > 0)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_audit_hash (
    audit_hash_id              BIGSERIAL PRIMARY KEY,
    audit_hash_code            VARCHAR(180) NOT NULL UNIQUE,
    chain_scope                VARCHAR(320) NOT NULL,
    sequence_no                BIGINT NOT NULL,
    entity_type                VARCHAR(48) NOT NULL,
    entity_code                VARCHAR(220) NOT NULL,
    entity_id                  BIGINT,
    event_time                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    previous_hash              VARCHAR(96) NOT NULL,
    payload_hash               VARCHAR(96) NOT NULL,
    entry_hash                 VARCHAR(96) NOT NULL UNIQUE,
    canonical_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    verification_status        VARCHAR(24) NOT NULL DEFAULT 'chained',
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chain_scope, sequence_no),
    UNIQUE (entity_type, entity_code),
    CHECK (sequence_no > 0),
    CHECK (entity_type IN ('callback', 'command', 'signature', 'escalation', 'state_transition', 'lock_event', 'sla_action', 'recovery_drill')),
    CHECK (verification_status IN ('chained', 'verified', 'duplicate', 'broken'))
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_sla_action (
    sla_action_id              BIGSERIAL PRIMARY KEY,
    sla_action_code            VARCHAR(180) NOT NULL UNIQUE,
    escalation_id              BIGINT REFERENCES qmeta.source_route_incident_approval_escalation(escalation_id) ON DELETE SET NULL,
    escalation_code            VARCHAR(180),
    command_code               VARCHAR(180),
    control_code               VARCHAR(280),
    approval_code              VARCHAR(260),
    reason_code                VARCHAR(48) NOT NULL,
    action_type                VARCHAR(48) NOT NULL,
    action_status              VARCHAR(24) NOT NULL DEFAULT 'planned',
    severity                   VARCHAR(24) NOT NULL DEFAULT 'high',
    owner_principal_code       VARCHAR(128) NOT NULL DEFAULT 'platform-ops',
    due_at                     TIMESTAMPTZ,
    generated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_at                TIMESTAMPTZ,
    external_side_effect       BOOLEAN NOT NULL DEFAULT FALSE,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (escalation_code, action_type),
    CHECK (reason_code IN ('approval_timeout', 'quorum_stalled', 'policy_denied', 'missing_binding', 'invalid_signature', 'replay_rejected', 'cancel_requested')),
    CHECK (action_type IN ('notify_owner', 'escalate_risk_admin', 'pause_route_recovery', 'cancel_stale', 'suppress_replay', 'retry_callback_probe', 'restore_from_audit')),
    CHECK (action_status IN ('planned', 'suppressed', 'executed', 'failed', 'resolved')),
    CHECK (severity IN ('medium', 'high', 'critical'))
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_recovery_drill (
    drill_id                   BIGSERIAL PRIMARY KEY,
    drill_code                 VARCHAR(180) NOT NULL UNIQUE,
    drill_type                 VARCHAR(48) NOT NULL DEFAULT 'full',
    status                     VARCHAR(24) NOT NULL DEFAULT 'success',
    requested_by               VARCHAR(128) NOT NULL DEFAULT 'epsilon6',
    trigger_mode               VARCHAR(32) NOT NULL DEFAULT 'manual',
    target_control_code        VARCHAR(280),
    check_count                INTEGER NOT NULL DEFAULT 0,
    passed_count               INTEGER NOT NULL DEFAULT 0,
    failed_count               INTEGER NOT NULL DEFAULT 0,
    recovered_count            INTEGER NOT NULL DEFAULT 0,
    started_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                TIMESTAMPTZ,
    duration_ms                INTEGER,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (drill_type IN ('db_reconnect', 'webhook_replay', 'hash_chain_verify', 'lock_contention', 'state_machine_restore', 'full')),
    CHECK (status IN ('success', 'warning', 'failed')),
    CHECK (trigger_mode IN ('manual', 'smoke', 'worker')),
    CHECK (check_count >= 0),
    CHECK (passed_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (recovered_count >= 0),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_lock_event_lookup
    ON qmeta.source_route_incident_approval_lock_event(lock_scope, lock_status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_lock_event_target
    ON qmeta.source_route_incident_approval_lock_event(control_code, approval_code, batch_code, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_transition_lookup
    ON qmeta.source_route_incident_approval_state_transition(control_code, approval_code, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_transition_status
    ON qmeta.source_route_incident_approval_state_transition(transition_status, reason_code, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_audit_chain_lookup
    ON qmeta.source_route_incident_approval_audit_hash(chain_scope, sequence_no DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_audit_entity
    ON qmeta.source_route_incident_approval_audit_hash(entity_type, entity_code);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_sla_action_lookup
    ON qmeta.source_route_incident_approval_sla_action(action_status, severity, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_sla_action_target
    ON qmeta.source_route_incident_approval_sla_action(command_code, control_code, approval_code, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_recovery_drill_lookup
    ON qmeta.source_route_incident_approval_recovery_drill(status, drill_type, started_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'epsilon6_route_incident_approval_resilience_15m', 'route_incident_approval_resilience', 900, 300, 300, 120,
    '{"epsilon6_sla_automation":true,"epsilon6_hash_verify":true,"epsilon6_recovery_drill":"hash_chain_verify","epsilon6_requested_by":"epsilon6","epsilon6_environment":"local"}'::jsonb,
    '{"owner":"epsilon6","purpose":"enforce route approval concurrency evidence, immutable audit hash verification, SLA actions and recovery drills"}'::jsonb
)
ON CONFLICT (schedule_code) DO UPDATE SET
    task_name = EXCLUDED.task_name,
    frequency_seconds = EXCLUDED.frequency_seconds,
    max_runtime_seconds = EXCLUDED.max_runtime_seconds,
    lock_timeout_seconds = EXCLUDED.lock_timeout_seconds,
    retry_backoff_seconds = EXCLUDED.retry_backoff_seconds,
    task_args = EXCLUDED.task_args,
    details = EXCLUDED.details,
    status = 'active',
    updated_at = now();
