-- Upsilon-5: approved route-weight execution, staged rollout and rollback control.

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
        'vendor_route_weight_executor'
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
        'vendor_route_weight_executor'
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
        'vendor_route_weight_executor'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_route_weight_execution_run (
    execution_id                            BIGSERIAL PRIMARY KEY,
    execution_code                          VARCHAR(180) NOT NULL UNIQUE,
    optimization_id                         BIGINT REFERENCES qmeta.vendor_cost_optimization_snapshot(optimization_id) ON DELETE SET NULL,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id                       BIGINT REFERENCES qmeta.source_system(source_id),
    stability_snapshot_id                   BIGINT REFERENCES qmeta.vendor_primary_stability_snapshot(snapshot_id) ON DELETE SET NULL,
    as_of_at                                TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of_date                              DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                            VARCHAR(128) NOT NULL DEFAULT 'upsilon5',
    trigger_mode                            VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                             VARCHAR(32) NOT NULL DEFAULT 'local',
    execution_scope                         VARCHAR(32) NOT NULL DEFAULT 'primary_source',
    execution_mode                          VARCHAR(32) NOT NULL DEFAULT 'review_only',
    approval_policy                         VARCHAR(32) NOT NULL DEFAULT 'manual_required',
    approval_status                         VARCHAR(32) NOT NULL DEFAULT 'pending',
    rollout_policy                          VARCHAR(32) NOT NULL DEFAULT 'gradual',
    status                                  VARCHAR(32) NOT NULL DEFAULT 'pending_approval',
    stage_count                             INTEGER NOT NULL DEFAULT 0,
    current_stage_sequence                  INTEGER NOT NULL DEFAULT 0,
    target_primary_weight_pct               NUMERIC(8, 4) NOT NULL DEFAULT 0,
    target_backup_weight_pct                NUMERIC(8, 4) NOT NULL DEFAULT 100,
    target_free_source_weight_pct           NUMERIC(8, 4) NOT NULL DEFAULT 0,
    applied_primary_weight_pct              NUMERIC(8, 4) NOT NULL DEFAULT 0,
    applied_backup_weight_pct               NUMERIC(8, 4) NOT NULL DEFAULT 100,
    applied_free_source_weight_pct          NUMERIC(8, 4) NOT NULL DEFAULT 0,
    dataset_count                           INTEGER NOT NULL DEFAULT 0,
    pending_approval_dataset_count          INTEGER NOT NULL DEFAULT 0,
    approved_dataset_count                  INTEGER NOT NULL DEFAULT 0,
    staged_dataset_count                    INTEGER NOT NULL DEFAULT 0,
    applied_dataset_count                   INTEGER NOT NULL DEFAULT 0,
    rollback_recommended_count              INTEGER NOT NULL DEFAULT 0,
    rolled_back_dataset_count               INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count                   INTEGER NOT NULL DEFAULT 0,
    no_primary_dataset_count                INTEGER NOT NULL DEFAULT 0,
    routing_change_allowed                  BOOLEAN NOT NULL DEFAULT FALSE,
    routing_change_applied                  BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_allowed                        BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_applied                        BOOLEAN NOT NULL DEFAULT FALSE,
    blocking_issues                         TEXT[] NOT NULL DEFAULT '{}',
    required_actions                        TEXT[] NOT NULL DEFAULT '{}',
    request_payload                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                           TEXT,
    started_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                             TIMESTAMPTZ,
    duration_ms                             INTEGER,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (execution_scope IN ('primary_source', 'all_datasets', 'full_market')),
    CHECK (execution_mode IN ('review_only', 'dry_run', 'apply')),
    CHECK (approval_policy IN ('manual_required', 'auto_if_optimized')),
    CHECK (approval_status IN ('not_required', 'pending', 'approved', 'rejected', 'blocked')),
    CHECK (rollout_policy IN ('review_only', 'canary', 'gradual', 'full')),
    CHECK (status IN ('pending_approval', 'approved', 'staged', 'applied', 'rollback_recommended', 'rolled_back', 'blocked', 'no_primary_promotion', 'review_required')),
    CHECK (stage_count >= 0),
    CHECK (current_stage_sequence >= 0),
    CHECK (target_primary_weight_pct >= 0 AND target_primary_weight_pct <= 100),
    CHECK (target_backup_weight_pct >= 0 AND target_backup_weight_pct <= 100),
    CHECK (target_free_source_weight_pct >= 0 AND target_free_source_weight_pct <= 100),
    CHECK (applied_primary_weight_pct >= 0 AND applied_primary_weight_pct <= 100),
    CHECK (applied_backup_weight_pct >= 0 AND applied_backup_weight_pct <= 100),
    CHECK (applied_free_source_weight_pct >= 0 AND applied_free_source_weight_pct <= 100),
    CHECK (dataset_count >= 0),
    CHECK (pending_approval_dataset_count >= 0),
    CHECK (approved_dataset_count >= 0),
    CHECK (staged_dataset_count >= 0),
    CHECK (applied_dataset_count >= 0),
    CHECK (rollback_recommended_count >= 0),
    CHECK (rolled_back_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (no_primary_dataset_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_route_execution_lookup
    ON qmeta.vendor_route_weight_execution_run(source_id, as_of_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_route_execution_status
    ON qmeta.vendor_route_weight_execution_run(status, approval_status, execution_mode, as_of_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_route_execution_optimization
    ON qmeta.vendor_route_weight_execution_run(optimization_id, as_of_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_route_weight_execution_dataset (
    execution_dataset_id                    BIGSERIAL PRIMARY KEY,
    execution_dataset_code                  VARCHAR(180) NOT NULL UNIQUE,
    execution_id                            BIGINT NOT NULL REFERENCES qmeta.vendor_route_weight_execution_run(execution_id) ON DELETE CASCADE,
    optimization_id                         BIGINT REFERENCES qmeta.vendor_cost_optimization_snapshot(optimization_id) ON DELETE SET NULL,
    plan_id                                 BIGINT REFERENCES qmeta.vendor_route_weight_plan(plan_id) ON DELETE SET NULL,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                              BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id                       BIGINT REFERENCES qmeta.source_system(source_id),
    backup_source_id                        BIGINT REFERENCES qmeta.source_system(source_id),
    current_priority_id                     BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    as_of_date                              DATE NOT NULL DEFAULT CURRENT_DATE,
    status                                  VARCHAR(32) NOT NULL DEFAULT 'pending_approval',
    approval_status                         VARCHAR(32) NOT NULL DEFAULT 'pending',
    rollout_policy                          VARCHAR(32) NOT NULL DEFAULT 'gradual',
    current_stage_sequence                  INTEGER NOT NULL DEFAULT 0,
    stage_count                             INTEGER NOT NULL DEFAULT 0,
    current_primary_source_code             VARCHAR(64),
    current_priority                        INTEGER,
    is_primary_route                        BOOLEAN NOT NULL DEFAULT FALSE,
    tau5_status                             VARCHAR(32),
    tau5_plan_role                          VARCHAR(32),
    stability_status                        VARCHAR(32),
    stability_score                         NUMERIC(8, 4) NOT NULL DEFAULT 0,
    contract_status                         VARCHAR(32),
    entitlement_status                      VARCHAR(32),
    target_primary_weight_pct               NUMERIC(8, 4) NOT NULL DEFAULT 0,
    target_backup_weight_pct                NUMERIC(8, 4) NOT NULL DEFAULT 100,
    target_free_source_weight_pct           NUMERIC(8, 4) NOT NULL DEFAULT 0,
    applied_primary_weight_pct              NUMERIC(8, 4) NOT NULL DEFAULT 0,
    applied_backup_weight_pct               NUMERIC(8, 4) NOT NULL DEFAULT 100,
    applied_free_source_weight_pct          NUMERIC(8, 4) NOT NULL DEFAULT 0,
    projected_budget_usage_pct              NUMERIC(12, 8) NOT NULL DEFAULT 0,
    projected_monthly_quota_usage_pct       NUMERIC(12, 8) NOT NULL DEFAULT 0,
    routing_change_allowed                  BOOLEAN NOT NULL DEFAULT FALSE,
    routing_change_applied                  BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_allowed                        BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_applied                        BOOLEAN NOT NULL DEFAULT FALSE,
    blocking_issues                         TEXT[] NOT NULL DEFAULT '{}',
    required_actions                        TEXT[] NOT NULL DEFAULT '{}',
    evidence                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                           TEXT,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('pending_approval', 'approved', 'staged', 'applied', 'rollback_recommended', 'rolled_back', 'blocked', 'no_primary_promotion', 'review_required')),
    CHECK (approval_status IN ('not_required', 'pending', 'approved', 'rejected', 'blocked')),
    CHECK (rollout_policy IN ('review_only', 'canary', 'gradual', 'full')),
    CHECK (current_stage_sequence >= 0),
    CHECK (stage_count >= 0),
    CHECK (current_priority IS NULL OR current_priority >= 0),
    CHECK (stability_score >= 0 AND stability_score <= 100),
    CHECK (target_primary_weight_pct >= 0 AND target_primary_weight_pct <= 100),
    CHECK (target_backup_weight_pct >= 0 AND target_backup_weight_pct <= 100),
    CHECK (target_free_source_weight_pct >= 0 AND target_free_source_weight_pct <= 100),
    CHECK (applied_primary_weight_pct >= 0 AND applied_primary_weight_pct <= 100),
    CHECK (applied_backup_weight_pct >= 0 AND applied_backup_weight_pct <= 100),
    CHECK (applied_free_source_weight_pct >= 0 AND applied_free_source_weight_pct <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_route_execution_dataset_lookup
    ON qmeta.vendor_route_weight_execution_dataset(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_route_execution_dataset_run
    ON qmeta.vendor_route_weight_execution_dataset(execution_id, status, execution_dataset_id DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_route_weight_rollout_stage (
    stage_id                                BIGSERIAL PRIMARY KEY,
    stage_code                              VARCHAR(180) NOT NULL UNIQUE,
    execution_id                            BIGINT NOT NULL REFERENCES qmeta.vendor_route_weight_execution_run(execution_id) ON DELETE CASCADE,
    execution_dataset_id                    BIGINT REFERENCES qmeta.vendor_route_weight_execution_dataset(execution_dataset_id) ON DELETE CASCADE,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                              BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    as_of_date                              DATE NOT NULL DEFAULT CURRENT_DATE,
    stage_sequence                          INTEGER NOT NULL,
    stage_label                             VARCHAR(64) NOT NULL,
    status                                  VARCHAR(32) NOT NULL DEFAULT 'pending',
    approval_required                       BOOLEAN NOT NULL DEFAULT TRUE,
    approval_status                         VARCHAR(32) NOT NULL DEFAULT 'pending',
    gate_status                             VARCHAR(32) NOT NULL DEFAULT 'pending',
    target_primary_weight_pct               NUMERIC(8, 4) NOT NULL DEFAULT 0,
    target_backup_weight_pct                NUMERIC(8, 4) NOT NULL DEFAULT 100,
    target_free_source_weight_pct           NUMERIC(8, 4) NOT NULL DEFAULT 0,
    routing_change_allowed                  BOOLEAN NOT NULL DEFAULT FALSE,
    routing_change_applied                  BOOLEAN NOT NULL DEFAULT FALSE,
    blocking_issues                         TEXT[] NOT NULL DEFAULT '{}',
    required_actions                        TEXT[] NOT NULL DEFAULT '{}',
    evidence                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                           TEXT,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (stage_sequence > 0),
    CHECK (status IN ('pending', 'ready', 'applied', 'skipped', 'blocked', 'rollback_recommended', 'rolled_back')),
    CHECK (approval_status IN ('not_required', 'pending', 'approved', 'rejected', 'blocked')),
    CHECK (gate_status IN ('pending', 'passed', 'failed', 'blocked')),
    CHECK (target_primary_weight_pct >= 0 AND target_primary_weight_pct <= 100),
    CHECK (target_backup_weight_pct >= 0 AND target_backup_weight_pct <= 100),
    CHECK (target_free_source_weight_pct >= 0 AND target_free_source_weight_pct <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_route_rollout_stage_lookup
    ON qmeta.vendor_route_weight_rollout_stage(execution_id, stage_sequence, status);

CREATE INDEX IF NOT EXISTS idx_vendor_route_rollout_stage_dataset
    ON qmeta.vendor_route_weight_rollout_stage(source_id, dataset_id, stage_sequence, created_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.source_route_weight_policy (
    policy_id                               BIGSERIAL PRIMARY KEY,
    policy_code                             VARCHAR(180) NOT NULL UNIQUE,
    execution_id                            BIGINT REFERENCES qmeta.vendor_route_weight_execution_run(execution_id) ON DELETE SET NULL,
    execution_dataset_id                    BIGINT REFERENCES qmeta.vendor_route_weight_execution_dataset(execution_dataset_id) ON DELETE SET NULL,
    stage_id                                BIGINT REFERENCES qmeta.vendor_route_weight_rollout_stage(stage_id) ON DELETE SET NULL,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                              BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id                       BIGINT REFERENCES qmeta.source_system(source_id),
    backup_source_id                        BIGINT REFERENCES qmeta.source_system(source_id),
    effective_date                          DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date                                DATE,
    policy_status                           VARCHAR(32) NOT NULL DEFAULT 'active',
    execution_mode                          VARCHAR(32) NOT NULL DEFAULT 'apply',
    primary_weight_pct                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    backup_weight_pct                       NUMERIC(8, 4) NOT NULL DEFAULT 100,
    free_source_weight_pct                  NUMERIC(8, 4) NOT NULL DEFAULT 0,
    previous_primary_weight_pct             NUMERIC(8, 4),
    previous_backup_weight_pct              NUMERIC(8, 4),
    previous_free_source_weight_pct         NUMERIC(8, 4),
    created_by                              VARCHAR(128) NOT NULL DEFAULT 'upsilon5',
    evidence                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (policy_status IN ('planned', 'active', 'superseded', 'rolled_back')),
    CHECK (execution_mode IN ('review_only', 'dry_run', 'apply')),
    CHECK (end_date IS NULL OR end_date >= effective_date),
    CHECK (primary_weight_pct >= 0 AND primary_weight_pct <= 100),
    CHECK (backup_weight_pct >= 0 AND backup_weight_pct <= 100),
    CHECK (free_source_weight_pct >= 0 AND free_source_weight_pct <= 100)
);

CREATE INDEX IF NOT EXISTS idx_source_route_weight_policy_lookup
    ON qmeta.source_route_weight_policy(dataset_id, source_id, policy_status, effective_date DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_weight_policy_execution
    ON qmeta.source_route_weight_policy(execution_id, policy_status, policy_id DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'upsilon5_vendor_route_weight_executor_1h', 'vendor_route_weight_executor', 3600, 600, 600, 300,
    '{"upsilon5_execution_scope":"primary_source","upsilon5_execution_mode":"review_only","upsilon5_approval_policy":"manual_required","upsilon5_approval_status":"pending","upsilon5_rollout_policy":"gradual","upsilon5_rollout_stages":[10,30,60,90],"upsilon5_current_stage_sequence":1,"upsilon5_max_initial_primary_weight_pct":10,"upsilon5_allow_over_budget":false,"upsilon5_allow_quota_risk":false,"upsilon5_rollback_requested":false}'::jsonb,
    '{"owner":"upsilon5","purpose":"turn Tau-5 route-weight recommendations into approval-gated staged rollout and rollback-control records"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
