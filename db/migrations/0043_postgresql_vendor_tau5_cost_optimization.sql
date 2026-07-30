-- Tau-5: primary vendor cost optimization, route weight planning and budget stress.

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
        'vendor_cost_optimizer'
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
        'vendor_cost_optimizer'
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
        'vendor_cost_optimizer'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_cost_optimization_snapshot (
    optimization_id                         BIGSERIAL PRIMARY KEY,
    optimization_code                       VARCHAR(180) NOT NULL UNIQUE,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id                       BIGINT REFERENCES qmeta.source_system(source_id),
    stability_snapshot_id                   BIGINT REFERENCES qmeta.vendor_primary_stability_snapshot(snapshot_id) ON DELETE SET NULL,
    as_of_at                                TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of_date                              DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                            VARCHAR(128) NOT NULL DEFAULT 'tau5',
    trigger_mode                            VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                             VARCHAR(32) NOT NULL DEFAULT 'local',
    optimization_scope                      VARCHAR(32) NOT NULL DEFAULT 'primary_source',
    status                                  VARCHAR(32) NOT NULL DEFAULT 'watch',
    optimization_role                       VARCHAR(32) NOT NULL DEFAULT 'cost_watch',
    lookback_hours                          INTEGER NOT NULL DEFAULT 24,
    forecast_window_days                    INTEGER NOT NULL DEFAULT 30,
    monthly_budget_amount                   NUMERIC(24, 8) NOT NULL DEFAULT 10000,
    max_budget_usage_pct                    NUMERIC(10, 6) NOT NULL DEFAULT 0.850000,
    max_daily_quota_usage_pct               NUMERIC(10, 6) NOT NULL DEFAULT 0.850000,
    max_monthly_quota_usage_pct             NUMERIC(10, 6) NOT NULL DEFAULT 0.850000,
    min_stability_score                     NUMERIC(8, 4) NOT NULL DEFAULT 70,
    cost_safety_margin_pct                  NUMERIC(10, 6) NOT NULL DEFAULT 0.150000,
    default_unit_cost                       NUMERIC(20, 8) NOT NULL DEFAULT 0.01000000,
    stress_multipliers                      JSONB NOT NULL DEFAULT '[1,5,10]'::jsonb,
    dataset_count                           INTEGER NOT NULL DEFAULT 0,
    optimized_dataset_count                 INTEGER NOT NULL DEFAULT 0,
    watch_dataset_count                     INTEGER NOT NULL DEFAULT 0,
    over_budget_dataset_count               INTEGER NOT NULL DEFAULT 0,
    quota_risk_dataset_count                INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count                   INTEGER NOT NULL DEFAULT 0,
    no_primary_dataset_count                INTEGER NOT NULL DEFAULT 0,
    current_request_count                   BIGINT NOT NULL DEFAULT 0,
    forecast_request_count                  BIGINT NOT NULL DEFAULT 0,
    forecast_row_count                      BIGINT NOT NULL DEFAULT 0,
    current_cost_units                      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    forecast_cost_units                     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    monthly_fee                             NUMERIC(24, 8) NOT NULL DEFAULT 0,
    projected_monthly_cost                  NUMERIC(24, 8) NOT NULL DEFAULT 0,
    projected_budget_usage_pct              NUMERIC(12, 8) NOT NULL DEFAULT 0,
    daily_quota                             BIGINT NOT NULL DEFAULT 0,
    monthly_quota                           BIGINT NOT NULL DEFAULT 0,
    projected_daily_request_count           BIGINT NOT NULL DEFAULT 0,
    projected_monthly_request_count         BIGINT NOT NULL DEFAULT 0,
    projected_daily_quota_usage_pct         NUMERIC(12, 8) NOT NULL DEFAULT 0,
    projected_monthly_quota_usage_pct       NUMERIC(12, 8) NOT NULL DEFAULT 0,
    quota_exhaustion_days                   NUMERIC(12, 4),
    recommended_primary_weight_pct          NUMERIC(8, 4) NOT NULL DEFAULT 0,
    recommended_backup_weight_pct           NUMERIC(8, 4) NOT NULL DEFAULT 100,
    recommended_free_source_weight_pct      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    optimization_score                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
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
    CHECK (optimization_scope IN ('primary_source', 'all_datasets', 'full_market')),
    CHECK (status IN ('optimized', 'watch', 'over_budget', 'quota_risk', 'blocked', 'no_primary_promotion')),
    CHECK (optimization_role IN ('primary_mix', 'cost_watch', 'budget_guard', 'blocked', 'watch')),
    CHECK (lookback_hours > 0),
    CHECK (forecast_window_days > 0),
    CHECK (monthly_budget_amount > 0),
    CHECK (max_budget_usage_pct >= 0 AND max_budget_usage_pct <= 10),
    CHECK (max_daily_quota_usage_pct >= 0 AND max_daily_quota_usage_pct <= 10),
    CHECK (max_monthly_quota_usage_pct >= 0 AND max_monthly_quota_usage_pct <= 10),
    CHECK (min_stability_score >= 0 AND min_stability_score <= 100),
    CHECK (cost_safety_margin_pct >= 0 AND cost_safety_margin_pct <= 1),
    CHECK (default_unit_cost >= 0),
    CHECK (dataset_count >= 0),
    CHECK (optimized_dataset_count >= 0),
    CHECK (watch_dataset_count >= 0),
    CHECK (over_budget_dataset_count >= 0),
    CHECK (quota_risk_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (no_primary_dataset_count >= 0),
    CHECK (current_request_count >= 0),
    CHECK (forecast_request_count >= 0),
    CHECK (forecast_row_count >= 0),
    CHECK (current_cost_units >= 0),
    CHECK (forecast_cost_units >= 0),
    CHECK (monthly_fee >= 0),
    CHECK (projected_monthly_cost >= 0),
    CHECK (daily_quota >= 0),
    CHECK (monthly_quota >= 0),
    CHECK (projected_daily_request_count >= 0),
    CHECK (projected_monthly_request_count >= 0),
    CHECK (quota_exhaustion_days IS NULL OR quota_exhaustion_days >= 0),
    CHECK (recommended_primary_weight_pct >= 0 AND recommended_primary_weight_pct <= 100),
    CHECK (recommended_backup_weight_pct >= 0 AND recommended_backup_weight_pct <= 100),
    CHECK (recommended_free_source_weight_pct >= 0 AND recommended_free_source_weight_pct <= 100),
    CHECK (optimization_score >= 0 AND optimization_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_cost_optimization_lookup
    ON qmeta.vendor_cost_optimization_snapshot(source_id, as_of_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_cost_optimization_status
    ON qmeta.vendor_cost_optimization_snapshot(status, optimization_role, as_of_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_cost_optimization_stability
    ON qmeta.vendor_cost_optimization_snapshot(stability_snapshot_id, as_of_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_route_weight_plan (
    plan_id                                 BIGSERIAL PRIMARY KEY,
    plan_code                               VARCHAR(180) NOT NULL UNIQUE,
    optimization_id                         BIGINT NOT NULL REFERENCES qmeta.vendor_cost_optimization_snapshot(optimization_id) ON DELETE CASCADE,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                              BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id                       BIGINT REFERENCES qmeta.source_system(source_id),
    backup_source_id                        BIGINT REFERENCES qmeta.source_system(source_id),
    current_priority_id                     BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    stability_snapshot_id                   BIGINT REFERENCES qmeta.vendor_primary_stability_snapshot(snapshot_id) ON DELETE SET NULL,
    as_of_date                              DATE NOT NULL DEFAULT CURRENT_DATE,
    status                                  VARCHAR(32) NOT NULL DEFAULT 'watch',
    plan_role                               VARCHAR(32) NOT NULL DEFAULT 'watch',
    current_primary_source_code             VARCHAR(64),
    current_priority                        INTEGER,
    is_primary_route                        BOOLEAN NOT NULL DEFAULT FALSE,
    stability_status                        VARCHAR(32),
    stability_score                         NUMERIC(8, 4) NOT NULL DEFAULT 0,
    contract_status                         VARCHAR(32),
    entitlement_status                      VARCHAR(32),
    production_use_allowed                  BOOLEAN NOT NULL DEFAULT FALSE,
    billing_model                           VARCHAR(32),
    billing_currency                        VARCHAR(16) NOT NULL DEFAULT 'CNY',
    unit_cost                               NUMERIC(20, 8) NOT NULL DEFAULT 0,
    monthly_fee_allocated                   NUMERIC(24, 8) NOT NULL DEFAULT 0,
    current_request_count                   BIGINT NOT NULL DEFAULT 0,
    forecast_request_count                  BIGINT NOT NULL DEFAULT 0,
    forecast_row_count                      BIGINT NOT NULL DEFAULT 0,
    current_cost_units                      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    forecast_cost_units                     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    allocated_budget_amount                 NUMERIC(24, 8) NOT NULL DEFAULT 0,
    projected_budget_usage_pct              NUMERIC(12, 8) NOT NULL DEFAULT 0,
    daily_quota                             BIGINT NOT NULL DEFAULT 0,
    monthly_quota                           BIGINT NOT NULL DEFAULT 0,
    projected_daily_request_count           BIGINT NOT NULL DEFAULT 0,
    projected_monthly_request_count         BIGINT NOT NULL DEFAULT 0,
    projected_daily_quota_usage_pct         NUMERIC(12, 8) NOT NULL DEFAULT 0,
    projected_monthly_quota_usage_pct       NUMERIC(12, 8) NOT NULL DEFAULT 0,
    quota_exhaustion_days                   NUMERIC(12, 4),
    recommended_primary_weight_pct          NUMERIC(8, 4) NOT NULL DEFAULT 0,
    recommended_backup_weight_pct           NUMERIC(8, 4) NOT NULL DEFAULT 100,
    recommended_free_source_weight_pct      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    routing_change_allowed                  BOOLEAN NOT NULL DEFAULT FALSE,
    optimization_score                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                         TEXT[] NOT NULL DEFAULT '{}',
    required_actions                        TEXT[] NOT NULL DEFAULT '{}',
    evidence                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                           TEXT,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('optimized', 'watch', 'over_budget', 'quota_risk', 'blocked', 'no_primary_promotion')),
    CHECK (plan_role IN ('primary', 'backup_mix', 'validator_only', 'blocked', 'watch')),
    CHECK (current_priority IS NULL OR current_priority >= 0),
    CHECK (stability_score >= 0 AND stability_score <= 100),
    CHECK (unit_cost >= 0),
    CHECK (monthly_fee_allocated >= 0),
    CHECK (current_request_count >= 0),
    CHECK (forecast_request_count >= 0),
    CHECK (forecast_row_count >= 0),
    CHECK (current_cost_units >= 0),
    CHECK (forecast_cost_units >= 0),
    CHECK (allocated_budget_amount >= 0),
    CHECK (daily_quota >= 0),
    CHECK (monthly_quota >= 0),
    CHECK (projected_daily_request_count >= 0),
    CHECK (projected_monthly_request_count >= 0),
    CHECK (quota_exhaustion_days IS NULL OR quota_exhaustion_days >= 0),
    CHECK (recommended_primary_weight_pct >= 0 AND recommended_primary_weight_pct <= 100),
    CHECK (recommended_backup_weight_pct >= 0 AND recommended_backup_weight_pct <= 100),
    CHECK (recommended_free_source_weight_pct >= 0 AND recommended_free_source_weight_pct <= 100),
    CHECK (optimization_score >= 0 AND optimization_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_route_weight_plan_lookup
    ON qmeta.vendor_route_weight_plan(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_route_weight_plan_optimization
    ON qmeta.vendor_route_weight_plan(optimization_id, status, plan_id DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_route_weight_plan_weight
    ON qmeta.vendor_route_weight_plan(plan_role, recommended_primary_weight_pct DESC, projected_budget_usage_pct DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_budget_stress_dataset_snapshot (
    stress_id                               BIGSERIAL PRIMARY KEY,
    stress_code                             VARCHAR(180) NOT NULL UNIQUE,
    optimization_id                         BIGINT NOT NULL REFERENCES qmeta.vendor_cost_optimization_snapshot(optimization_id) ON DELETE CASCADE,
    plan_id                                 BIGINT REFERENCES qmeta.vendor_route_weight_plan(plan_id) ON DELETE CASCADE,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                              BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    as_of_date                              DATE NOT NULL DEFAULT CURRENT_DATE,
    stress_multiplier                       NUMERIC(12, 4) NOT NULL DEFAULT 1,
    status                                  VARCHAR(32) NOT NULL DEFAULT 'watch',
    forecast_request_count                  BIGINT NOT NULL DEFAULT 0,
    forecast_cost_units                     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    projected_budget_usage_pct              NUMERIC(12, 8) NOT NULL DEFAULT 0,
    projected_daily_request_count           BIGINT NOT NULL DEFAULT 0,
    projected_monthly_request_count         BIGINT NOT NULL DEFAULT 0,
    projected_daily_quota_usage_pct         NUMERIC(12, 8) NOT NULL DEFAULT 0,
    projected_monthly_quota_usage_pct       NUMERIC(12, 8) NOT NULL DEFAULT 0,
    quota_exhaustion_days                   NUMERIC(12, 4),
    recommended_action                      VARCHAR(64) NOT NULL DEFAULT 'review',
    blocking_issues                         TEXT[] NOT NULL DEFAULT '{}',
    required_actions                        TEXT[] NOT NULL DEFAULT '{}',
    evidence                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                           TEXT,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (stress_multiplier > 0),
    CHECK (status IN ('optimized', 'watch', 'over_budget', 'quota_risk', 'blocked', 'no_primary_promotion')),
    CHECK (forecast_request_count >= 0),
    CHECK (forecast_cost_units >= 0),
    CHECK (projected_daily_request_count >= 0),
    CHECK (projected_monthly_request_count >= 0),
    CHECK (quota_exhaustion_days IS NULL OR quota_exhaustion_days >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_budget_stress_dataset_lookup
    ON qmeta.vendor_budget_stress_dataset_snapshot(source_id, dataset_id, stress_multiplier, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_budget_stress_dataset_optimization
    ON qmeta.vendor_budget_stress_dataset_snapshot(optimization_id, status, stress_id DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'tau5_vendor_cost_optimizer_6h', 'vendor_cost_optimizer', 21600, 600, 600, 300,
    '{"tau5_optimization_scope":"primary_source","tau5_lookback_hours":24,"tau5_forecast_window_days":30,"tau5_monthly_budget_amount":10000,"tau5_max_budget_usage_pct":0.85,"tau5_max_daily_quota_usage_pct":0.85,"tau5_max_monthly_quota_usage_pct":0.85,"tau5_min_stability_score":70,"tau5_cost_safety_margin_pct":0.15,"tau5_default_unit_cost":0.01,"tau5_stress_multipliers":[1,5,10]}'::jsonb,
    '{"owner":"tau5","purpose":"optimize primary vendor cost, route weights, quota pressure and budget stress after Sigma-5 stability checks"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
