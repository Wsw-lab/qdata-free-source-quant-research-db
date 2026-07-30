-- Eta-6: real vendor production primary-source closure.
-- This stage summarizes profile/env, contract entitlement, live pilot,
-- primary promotion, stability, cost and route execution evidence into a
-- single production go/no-go audit trail.

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
        'vendor_production_source_closure',
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
        'vendor_production_source_closure',
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
        'vendor_production_source_closure',
        'source_route_feedback_monitor',
        'route_incident_automation',
        'route_incident_control',
        'route_incident_control_health',
        'route_incident_operations',
        'route_incident_approval_governance',
        'route_incident_approval_resilience',
        'route_incident_approval_release'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_production_source_run (
    production_id                         BIGSERIAL PRIMARY KEY,
    production_code                       VARCHAR(180) NOT NULL UNIQUE,
    source_id                             BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id                     BIGINT REFERENCES qmeta.source_system(source_id),
    as_of_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of_date                            DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                          VARCHAR(128) NOT NULL DEFAULT 'eta6',
    trigger_mode                          VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                           VARCHAR(32) NOT NULL DEFAULT 'local',
    closure_scope                         VARCHAR(32) NOT NULL DEFAULT 'production_primary',
    closure_mode                          VARCHAR(32) NOT NULL DEFAULT 'review_only',
    status                                VARCHAR(32) NOT NULL DEFAULT 'blocked',
    production_role                       VARCHAR(32) NOT NULL DEFAULT 'blocked',
    dataset_count                         INTEGER NOT NULL DEFAULT 0,
    authorized_dataset_count              INTEGER NOT NULL DEFAULT 0,
    live_ready_dataset_count              INTEGER NOT NULL DEFAULT 0,
    pilot_ready_dataset_count             INTEGER NOT NULL DEFAULT 0,
    promoted_dataset_count                INTEGER NOT NULL DEFAULT 0,
    stable_dataset_count                  INTEGER NOT NULL DEFAULT 0,
    optimized_dataset_count               INTEGER NOT NULL DEFAULT 0,
    route_ready_dataset_count             INTEGER NOT NULL DEFAULT 0,
    production_ready_dataset_count        INTEGER NOT NULL DEFAULT 0,
    applied_dataset_count                 INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count                 INTEGER NOT NULL DEFAULT 0,
    require_real_vendor_env               BOOLEAN NOT NULL DEFAULT TRUE,
    live_base_url_present                 BOOLEAN NOT NULL DEFAULT FALSE,
    live_token_present                    BOOLEAN NOT NULL DEFAULT FALSE,
    token_digest                          VARCHAR(96),
    external_probe_allowed                BOOLEAN NOT NULL DEFAULT FALSE,
    routing_change_allowed                BOOLEAN NOT NULL DEFAULT FALSE,
    routing_change_applied                BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_guard_armed                  BOOLEAN NOT NULL DEFAULT FALSE,
    production_score                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                       TEXT[] NOT NULL DEFAULT '{}',
    required_actions                      TEXT[] NOT NULL DEFAULT '{}',
    request_payload                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                              JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                         TEXT,
    started_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                           TIMESTAMPTZ,
    duration_ms                           INTEGER,
    created_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api', 'worker')),
    CHECK (environment IN ('local', 'staging', 'production')),
    CHECK (closure_scope IN ('production_primary', 'canary', 'full_market')),
    CHECK (closure_mode IN ('review_only', 'dry_run', 'apply')),
    CHECK (status IN ('blocked', 'review_required', 'ready_for_pilot', 'ready_for_primary', 'ready_for_rollout', 'production_ready', 'applied', 'monitoring', 'rollback_required', 'failed')),
    CHECK (production_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate', 'primary')),
    CHECK (dataset_count >= 0),
    CHECK (authorized_dataset_count >= 0),
    CHECK (live_ready_dataset_count >= 0),
    CHECK (pilot_ready_dataset_count >= 0),
    CHECK (promoted_dataset_count >= 0),
    CHECK (stable_dataset_count >= 0),
    CHECK (optimized_dataset_count >= 0),
    CHECK (route_ready_dataset_count >= 0),
    CHECK (production_ready_dataset_count >= 0),
    CHECK (applied_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (production_score >= 0 AND production_score <= 100),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_production_source_run_lookup
    ON qmeta.vendor_production_source_run(source_id, as_of_at DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_production_source_run_status
    ON qmeta.vendor_production_source_run(status, production_role, environment, as_of_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_production_source_dataset_check (
    dataset_check_id                     BIGSERIAL PRIMARY KEY,
    dataset_check_code                   VARCHAR(180) NOT NULL UNIQUE,
    production_id                        BIGINT NOT NULL REFERENCES qmeta.vendor_production_source_run(production_id) ON DELETE CASCADE,
    source_id                            BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                           BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id                    BIGINT REFERENCES qmeta.source_system(source_id),
    contract_id                          BIGINT REFERENCES qmeta.vendor_contract_profile(contract_id) ON DELETE SET NULL,
    entitlement_id                       BIGINT REFERENCES qmeta.vendor_contract_dataset_entitlement(entitlement_id) ON DELETE SET NULL,
    procurement_snapshot_id              BIGINT REFERENCES qmeta.vendor_procurement_readiness_snapshot(snapshot_id) ON DELETE SET NULL,
    canary_pilot_id                      BIGINT REFERENCES qmeta.vendor_live_pilot_run(pilot_id) ON DELETE SET NULL,
    full_market_pilot_id                 BIGINT REFERENCES qmeta.vendor_live_pilot_run(pilot_id) ON DELETE SET NULL,
    promotion_id                         BIGINT REFERENCES qmeta.vendor_primary_promotion_run(promotion_id) ON DELETE SET NULL,
    promotion_result_id                  BIGINT REFERENCES qmeta.vendor_primary_promotion_dataset_result(result_id) ON DELETE SET NULL,
    stability_snapshot_id                BIGINT REFERENCES qmeta.vendor_primary_stability_snapshot(snapshot_id) ON DELETE SET NULL,
    stability_dataset_snapshot_id        BIGINT REFERENCES qmeta.vendor_primary_stability_dataset_snapshot(dataset_snapshot_id) ON DELETE SET NULL,
    optimization_id                      BIGINT REFERENCES qmeta.vendor_cost_optimization_snapshot(optimization_id) ON DELETE SET NULL,
    route_plan_id                        BIGINT REFERENCES qmeta.vendor_route_weight_plan(plan_id) ON DELETE SET NULL,
    route_execution_id                   BIGINT REFERENCES qmeta.vendor_route_weight_execution_run(execution_id) ON DELETE SET NULL,
    route_execution_dataset_id           BIGINT REFERENCES qmeta.vendor_route_weight_execution_dataset(execution_dataset_id) ON DELETE SET NULL,
    as_of_date                           DATE NOT NULL DEFAULT CURRENT_DATE,
    status                               VARCHAR(32) NOT NULL DEFAULT 'blocked',
    production_role                      VARCHAR(32) NOT NULL DEFAULT 'blocked',
    contract_status                      VARCHAR(32),
    entitlement_status                   VARCHAR(32),
    allowed_role                         VARCHAR(32),
    procurement_status                   VARCHAR(32),
    procurement_role                     VARCHAR(32),
    canary_status                        VARCHAR(32),
    canary_signoff_status                VARCHAR(32),
    full_market_status                   VARCHAR(32),
    full_market_signoff_status           VARCHAR(32),
    promotion_status                     VARCHAR(32),
    promotion_result_status              VARCHAR(32),
    stability_status                     VARCHAR(32),
    stability_score                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    optimization_status                  VARCHAR(32),
    route_plan_status                    VARCHAR(32),
    route_execution_status               VARCHAR(32),
    route_policy_status                  VARCHAR(32),
    current_primary_source_code          VARCHAR(64),
    is_primary_route                     BOOLEAN NOT NULL DEFAULT FALSE,
    recommended_primary_weight_pct       NUMERIC(8, 4) NOT NULL DEFAULT 0,
    applied_primary_weight_pct           NUMERIC(8, 4) NOT NULL DEFAULT 0,
    production_score                     NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                      TEXT[] NOT NULL DEFAULT '{}',
    required_actions                     TEXT[] NOT NULL DEFAULT '{}',
    evidence                             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                        TEXT,
    created_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('blocked', 'review_required', 'ready_for_pilot', 'ready_for_primary', 'ready_for_rollout', 'production_ready', 'applied', 'monitoring', 'rollback_required', 'failed')),
    CHECK (production_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate', 'primary')),
    CHECK (stability_score >= 0 AND stability_score <= 100),
    CHECK (recommended_primary_weight_pct >= 0 AND recommended_primary_weight_pct <= 100),
    CHECK (applied_primary_weight_pct >= 0 AND applied_primary_weight_pct <= 100),
    CHECK (production_score >= 0 AND production_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_production_source_dataset_lookup
    ON qmeta.vendor_production_source_dataset_check(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_production_source_dataset_run
    ON qmeta.vendor_production_source_dataset_check(production_id, status, dataset_check_id DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_production_source_decision (
    decision_id                          BIGSERIAL PRIMARY KEY,
    decision_code                        VARCHAR(180) NOT NULL UNIQUE,
    production_id                        BIGINT NOT NULL REFERENCES qmeta.vendor_production_source_run(production_id) ON DELETE CASCADE,
    dataset_check_id                     BIGINT REFERENCES qmeta.vendor_production_source_dataset_check(dataset_check_id) ON DELETE CASCADE,
    source_id                            BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                           BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    decision_type                        VARCHAR(48) NOT NULL,
    status                               VARCHAR(24) NOT NULL DEFAULT 'blocked',
    severity                             VARCHAR(24) NOT NULL DEFAULT 'warning',
    decision_summary                     VARCHAR(360),
    blocking_issues                      TEXT[] NOT NULL DEFAULT '{}',
    required_actions                     TEXT[] NOT NULL DEFAULT '{}',
    evidence                             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                        TEXT,
    created_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decision_type IN ('profile_env', 'contract_entitlement', 'live_pilot', 'primary_promotion', 'stability', 'cost_quota', 'route_execution', 'rollback_guard', 'final_decision')),
    CHECK (status IN ('passed', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (severity IN ('info', 'warning', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_production_source_decision_run
    ON qmeta.vendor_production_source_decision(production_id, decision_type, status, decision_id DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_production_source_decision_dataset
    ON qmeta.vendor_production_source_decision(source_id, dataset_id, decision_type, created_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'eta6_vendor_production_source_closure_30m', 'vendor_production_source_closure', 1800, 900, 900, 300,
    '{"eta6_closure_scope":"production_primary","eta6_closure_mode":"review_only","eta6_require_real_vendor_env":true,"eta6_external_probe_allowed":false}'::jsonb,
    '{"owner":"eta6","purpose":"summarize authorized real-vendor production primary-source go/no-go evidence; default is review-only and token-safe"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
