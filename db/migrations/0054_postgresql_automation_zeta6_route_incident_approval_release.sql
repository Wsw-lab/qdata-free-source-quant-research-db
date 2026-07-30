-- Zeta-6: cross-environment release gate, secret rotation evidence and audit export
-- for route incident approval callbacks.

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
        'route_incident_approval_resilience',
        'route_incident_approval_release'
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
        'route_incident_approval_resilience',
        'route_incident_approval_release'
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
        'route_incident_approval_resilience',
        'route_incident_approval_release'
    ));

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_release_preflight (
    preflight_id                       BIGSERIAL PRIMARY KEY,
    preflight_code                     VARCHAR(180) NOT NULL UNIQUE,
    environment                        VARCHAR(32) NOT NULL DEFAULT 'local',
    status                             VARCHAR(24) NOT NULL DEFAULT 'success',
    release_version                    VARCHAR(128) NOT NULL DEFAULT 'zeta6-local',
    requested_by                       VARCHAR(128) NOT NULL DEFAULT 'zeta6',
    trigger_mode                       VARCHAR(32) NOT NULL DEFAULT 'manual',
    check_count                        INTEGER NOT NULL DEFAULT 0,
    passed_count                       INTEGER NOT NULL DEFAULT 0,
    warning_count                      INTEGER NOT NULL DEFAULT 0,
    failed_count                       INTEGER NOT NULL DEFAULT 0,
    dual_secret_enabled                BOOLEAN NOT NULL DEFAULT FALSE,
    audit_broken_count                 INTEGER NOT NULL DEFAULT 0,
    latest_recovery_drill_status       VARCHAR(24),
    checks                             JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                           JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                      TEXT,
    started_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                        TIMESTAMPTZ,
    duration_ms                        INTEGER,
    created_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (environment IN ('local', 'staging', 'production')),
    CHECK (status IN ('success', 'warning', 'failed', 'skipped')),
    CHECK (trigger_mode IN ('manual', 'worker', 'smoke', 'release')),
    CHECK (check_count >= 0),
    CHECK (passed_count >= 0),
    CHECK (warning_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (audit_broken_count >= 0),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_secret_rotation (
    rotation_id                        BIGSERIAL PRIMARY KEY,
    rotation_code                      VARCHAR(180) NOT NULL UNIQUE,
    environment                        VARCHAR(32) NOT NULL DEFAULT 'local',
    rotation_phase                     VARCHAR(32) NOT NULL DEFAULT 'current_only',
    status                             VARCHAR(24) NOT NULL DEFAULT 'success',
    active_secret_label                VARCHAR(32) NOT NULL DEFAULT 'current',
    accepted_secret_labels             TEXT[] NOT NULL DEFAULT '{}',
    verified_secret_label              VARCHAR(32),
    timestamp_seconds                  BIGINT,
    nonce                              VARCHAR(160),
    request_hash                       VARCHAR(96),
    signature_digest                   VARCHAR(96),
    max_clock_skew_seconds             INTEGER NOT NULL DEFAULT 300,
    evidence                           JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                      TEXT,
    observed_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (environment IN ('local', 'staging', 'production')),
    CHECK (rotation_phase IN ('current_only', 'dual_accept', 'next_only', 'drill')),
    CHECK (status IN ('success', 'warning', 'failed')),
    CHECK (active_secret_label IN ('current', 'next', 'none')),
    CHECK (verified_secret_label IS NULL OR verified_secret_label IN ('current', 'next', 'none')),
    CHECK (max_clock_skew_seconds >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_concurrency_test (
    test_id                            BIGSERIAL PRIMARY KEY,
    test_code                          VARCHAR(180) NOT NULL UNIQUE,
    environment                        VARCHAR(32) NOT NULL DEFAULT 'local',
    status                             VARCHAR(24) NOT NULL DEFAULT 'success',
    target_scope                       VARCHAR(320) NOT NULL,
    callback_count                     INTEGER NOT NULL DEFAULT 0,
    expected_success_count             INTEGER NOT NULL DEFAULT 1,
    success_count                      INTEGER NOT NULL DEFAULT 0,
    locked_count                       INTEGER NOT NULL DEFAULT 0,
    blocked_count                      INTEGER NOT NULL DEFAULT 0,
    replay_rejected_count              INTEGER NOT NULL DEFAULT 0,
    failed_count                       INTEGER NOT NULL DEFAULT 0,
    duration_ms                        INTEGER,
    max_worker_threads                 INTEGER NOT NULL DEFAULT 1,
    evidence                           JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                      TEXT,
    started_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                        TIMESTAMPTZ,
    created_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (environment IN ('local', 'staging', 'production')),
    CHECK (status IN ('success', 'warning', 'failed')),
    CHECK (callback_count >= 0),
    CHECK (expected_success_count >= 0),
    CHECK (success_count >= 0),
    CHECK (locked_count >= 0),
    CHECK (blocked_count >= 0),
    CHECK (replay_rejected_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CHECK (max_worker_threads > 0)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_audit_export (
    export_id                          BIGSERIAL PRIMARY KEY,
    export_code                        VARCHAR(180) NOT NULL UNIQUE,
    environment                        VARCHAR(32) NOT NULL DEFAULT 'local',
    status                             VARCHAR(24) NOT NULL DEFAULT 'success',
    export_format                      VARCHAR(24) NOT NULL DEFAULT 'json',
    chain_scope                        VARCHAR(320),
    control_code                       VARCHAR(280),
    approval_code                      VARCHAR(260),
    batch_code                         VARCHAR(180),
    included_entity_count              INTEGER NOT NULL DEFAULT 0,
    broken_hash_count                  INTEGER NOT NULL DEFAULT 0,
    package_hash                       VARCHAR(96) NOT NULL,
    exported_by                        VARCHAR(128) NOT NULL DEFAULT 'zeta6',
    trigger_mode                       VARCHAR(32) NOT NULL DEFAULT 'manual',
    generated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    evidence                           JSONB NOT NULL DEFAULT '{}'::jsonb,
    export_payload                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                      TEXT,
    created_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (environment IN ('local', 'staging', 'production')),
    CHECK (status IN ('success', 'warning', 'failed')),
    CHECK (export_format IN ('json', 'markdown', 'csv')),
    CHECK (trigger_mode IN ('manual', 'worker', 'smoke', 'release')),
    CHECK (included_entity_count >= 0),
    CHECK (broken_hash_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_release_preflight_lookup
    ON qmeta.source_route_incident_approval_release_preflight(environment, status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_release_preflight_version
    ON qmeta.source_route_incident_approval_release_preflight(release_version, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_secret_rotation_lookup
    ON qmeta.source_route_incident_approval_secret_rotation(environment, rotation_phase, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_secret_rotation_status
    ON qmeta.source_route_incident_approval_secret_rotation(status, verified_secret_label, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_concurrency_lookup
    ON qmeta.source_route_incident_approval_concurrency_test(environment, status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_concurrency_scope
    ON qmeta.source_route_incident_approval_concurrency_test(target_scope, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_audit_export_lookup
    ON qmeta.source_route_incident_approval_audit_export(environment, status, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_approval_audit_export_scope
    ON qmeta.source_route_incident_approval_audit_export(chain_scope, control_code, approval_code, batch_code, generated_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'zeta6_route_incident_approval_release_30m', 'route_incident_approval_release', 1800, 300, 300, 120,
    '{"zeta6_environment":"local","zeta6_release_version":"zeta6-local","zeta6_requested_by":"zeta6","zeta6_require_dual_secret":false,"zeta6_export_audit":true}'::jsonb,
    '{"owner":"zeta6","purpose":"run release preflight, callback secret rotation evidence and audit export for route incident approval"}'::jsonb
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
