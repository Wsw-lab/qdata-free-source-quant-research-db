-- Delta-6: production governance for route incident approvals.

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
        'route_incident_approval_governance'
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
        'route_incident_approval_governance'
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
        'route_incident_approval_governance'
    ));

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_role_binding (
    binding_id                  BIGSERIAL PRIMARY KEY,
    binding_code                VARCHAR(180) NOT NULL UNIQUE,
    principal_code              VARCHAR(128) NOT NULL,
    role_code                   VARCHAR(64) NOT NULL,
    dataset_code                VARCHAR(128) NOT NULL DEFAULT '*',
    source_code                 VARCHAR(128) NOT NULL DEFAULT '*',
    safety_level                VARCHAR(24) NOT NULL DEFAULT '*',
    status                      VARCHAR(24) NOT NULL DEFAULT 'active',
    effective_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at                  TIMESTAMPTZ,
    created_by                  VARCHAR(128) NOT NULL DEFAULT 'delta6',
    revoked_by                  VARCHAR(128),
    revoked_at                  TIMESTAMPTZ,
    details                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (role_code IN ('route_requester', 'route_approver', 'route_risk_admin', 'route_audit_viewer')),
    CHECK (status IN ('active', 'revoked', 'expired')),
    CHECK (expires_at IS NULL OR expires_at > effective_at)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_policy (
    policy_id                   BIGSERIAL PRIMARY KEY,
    policy_code                 VARCHAR(180) NOT NULL UNIQUE,
    dataset_code                VARCHAR(128) NOT NULL DEFAULT '*',
    source_code                 VARCHAR(128) NOT NULL DEFAULT '*',
    safety_level                VARCHAR(24) NOT NULL DEFAULT '*',
    status                      VARCHAR(24) NOT NULL DEFAULT 'active',
    min_approvals               INTEGER NOT NULL DEFAULT 2,
    require_distinct_requester  BOOLEAN NOT NULL DEFAULT TRUE,
    require_risk_admin_for_high BOOLEAN NOT NULL DEFAULT FALSE,
    require_wecom_signature     BOOLEAN NOT NULL DEFAULT TRUE,
    timeout_minutes             INTEGER NOT NULL DEFAULT 240,
    replay_window_minutes       INTEGER NOT NULL DEFAULT 1440,
    max_clock_skew_seconds      INTEGER NOT NULL DEFAULT 300,
    escalation_principal_code   VARCHAR(128) NOT NULL DEFAULT 'platform-ops',
    created_by                  VARCHAR(128) NOT NULL DEFAULT 'delta6',
    details                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('active', 'inactive')),
    CHECK (min_approvals BETWEEN 1 AND 5),
    CHECK (timeout_minutes > 0),
    CHECK (replay_window_minutes > 0),
    CHECK (max_clock_skew_seconds >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_callback (
    callback_id                 BIGSERIAL PRIMARY KEY,
    callback_code               VARCHAR(180) NOT NULL UNIQUE,
    provider_code               VARCHAR(32) NOT NULL DEFAULT 'wecom',
    nonce                       VARCHAR(160) NOT NULL,
    timestamp_seconds           BIGINT NOT NULL,
    request_hash                VARCHAR(96) NOT NULL,
    signature_digest            VARCHAR(96),
    signature_status            VARCHAR(32) NOT NULL DEFAULT 'verified',
    governance_status           VARCHAR(32) NOT NULL DEFAULT 'accepted',
    policy_id                   BIGINT REFERENCES qmeta.source_route_incident_approval_policy(policy_id) ON DELETE SET NULL,
    policy_code                 VARCHAR(180),
    binding_id                  BIGINT REFERENCES qmeta.source_route_incident_approval_role_binding(binding_id) ON DELETE SET NULL,
    binding_code                VARCHAR(180),
    command_id                  BIGINT REFERENCES qmeta.source_route_incident_approval_command(command_id) ON DELETE SET NULL,
    command_code                VARCHAR(180),
    idempotency_key             VARCHAR(220),
    control_code                VARCHAR(280),
    approval_code               VARCHAR(260),
    batch_code                  VARCHAR(180),
    decision                    VARCHAR(16),
    requested_by                VARCHAR(128),
    signer_code                 VARCHAR(128),
    required_approvals          INTEGER NOT NULL DEFAULT 1,
    replay_count                INTEGER NOT NULL DEFAULT 0,
    received_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at                TIMESTAMPTZ,
    duration_ms                 INTEGER,
    raw_payload_redacted        JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message               TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_code, nonce),
    CHECK (provider_code IN ('wecom')),
    CHECK (signature_status IN ('verified', 'replay_rejected', 'invalid_signature', 'timestamp_skew', 'missing_signature', 'payload_invalid')),
    CHECK (governance_status IN ('accepted', 'pending_quorum', 'applied', 'held', 'rejected', 'denied', 'replay_rejected', 'invalid_signature', 'payload_invalid', 'failed')),
    CHECK (decision IS NULL OR decision IN ('approve', 'reject', 'hold')),
    CHECK (required_approvals BETWEEN 1 AND 5),
    CHECK (replay_count >= 0),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_escalation (
    escalation_id               BIGSERIAL PRIMARY KEY,
    escalation_code             VARCHAR(180) NOT NULL UNIQUE,
    callback_id                 BIGINT REFERENCES qmeta.source_route_incident_approval_callback(callback_id) ON DELETE SET NULL,
    command_id                  BIGINT REFERENCES qmeta.source_route_incident_approval_command(command_id) ON DELETE SET NULL,
    command_code                VARCHAR(180),
    control_code                VARCHAR(280),
    approval_code               VARCHAR(260),
    reason_code                 VARCHAR(48) NOT NULL,
    status                      VARCHAR(24) NOT NULL DEFAULT 'open',
    severity                    VARCHAR(24) NOT NULL DEFAULT 'high',
    owner_principal_code        VARCHAR(128) NOT NULL DEFAULT 'platform-ops',
    due_at                      TIMESTAMPTZ,
    acknowledged_by             VARCHAR(128),
    acknowledged_at             TIMESTAMPTZ,
    resolved_by                 VARCHAR(128),
    resolved_at                 TIMESTAMPTZ,
    evidence                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message               TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (reason_code IN ('approval_timeout', 'quorum_stalled', 'policy_denied', 'missing_binding', 'invalid_signature', 'replay_rejected', 'cancel_requested')),
    CHECK (status IN ('open', 'acknowledged', 'resolved', 'suppressed')),
    CHECK (severity IN ('medium', 'high', 'critical'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_source_route_approval_role_active_scope
    ON qmeta.source_route_incident_approval_role_binding(
        principal_code, role_code, dataset_code, source_code, safety_level
    )
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_source_route_approval_role_lookup
    ON qmeta.source_route_incident_approval_role_binding(principal_code, role_code, status, effective_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_policy_scope
    ON qmeta.source_route_incident_approval_policy(dataset_code, source_code, safety_level, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_callback_lookup
    ON qmeta.source_route_incident_approval_callback(received_at DESC, governance_status, signature_status);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_callback_target
    ON qmeta.source_route_incident_approval_callback(control_code, approval_code, batch_code, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_callback_signer
    ON qmeta.source_route_incident_approval_callback(signer_code, decision, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_escalation_lookup
    ON qmeta.source_route_incident_approval_escalation(status, severity, reason_code, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_escalation_target
    ON qmeta.source_route_incident_approval_escalation(command_code, control_code, approval_code, created_at DESC);

INSERT INTO qmeta.source_route_incident_approval_policy (
    policy_code, dataset_code, source_code, safety_level, min_approvals,
    require_distinct_requester, require_risk_admin_for_high,
    require_wecom_signature, timeout_minutes, replay_window_minutes,
    max_clock_skew_seconds, escalation_principal_code, details
) VALUES (
    'delta6-default-route-approval-policy', '*', '*', '*', 2,
    TRUE, FALSE, TRUE, 240, 1440, 300, 'platform-ops',
    '{"owner":"delta6","purpose":"default production guardrail for route incident approval callbacks"}'::jsonb
)
ON CONFLICT (policy_code) DO UPDATE SET
    status = 'active',
    min_approvals = EXCLUDED.min_approvals,
    require_distinct_requester = EXCLUDED.require_distinct_requester,
    require_risk_admin_for_high = EXCLUDED.require_risk_admin_for_high,
    require_wecom_signature = EXCLUDED.require_wecom_signature,
    timeout_minutes = EXCLUDED.timeout_minutes,
    replay_window_minutes = EXCLUDED.replay_window_minutes,
    max_clock_skew_seconds = EXCLUDED.max_clock_skew_seconds,
    escalation_principal_code = EXCLUDED.escalation_principal_code,
    details = EXCLUDED.details,
    updated_at = now();

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'delta6_route_incident_approval_governance_15m', 'route_incident_approval_governance', 900, 300, 300, 120,
    '{"delta6_route_timeout_scan":true,"delta6_route_default_timeout_minutes":240,"delta6_route_requested_by":"delta6","delta6_route_environment":"local"}'::jsonb,
    '{"owner":"delta6","purpose":"scan pending Gamma-6 route approval commands, enforce callback governance evidence and open timeout escalations"}'::jsonb
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
