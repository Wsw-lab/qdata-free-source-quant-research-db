-- A 股量化数据平台 Theta：真实供应商生产化、全市场压测和上线决策

ALTER TABLE qmeta.sla_policy
    ADD COLUMN IF NOT EXISTS min_vendor_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS max_vendor_conflict_rate NUMERIC(12, 8),
    ADD COLUMN IF NOT EXISTS max_vendor_failure_rate NUMERIC(12, 8),
    ADD COLUMN IF NOT EXISTS max_vendor_latency_ms NUMERIC(18, 4),
    ADD COLUMN IF NOT EXISTS max_provider_error_count BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_sla_policy_theta_vendor_thresholds'
          AND conrelid = 'qmeta.sla_policy'::regclass
    ) THEN
        ALTER TABLE qmeta.sla_policy
            ADD CONSTRAINT chk_sla_policy_theta_vendor_thresholds
            CHECK (
                (min_vendor_score IS NULL OR (min_vendor_score >= 0 AND min_vendor_score <= 100))
                AND (max_vendor_conflict_rate IS NULL OR (max_vendor_conflict_rate >= 0 AND max_vendor_conflict_rate <= 1))
                AND (max_vendor_failure_rate IS NULL OR (max_vendor_failure_rate >= 0 AND max_vendor_failure_rate <= 1))
                AND (max_vendor_latency_ms IS NULL OR max_vendor_latency_ms >= 0)
                AND (max_provider_error_count IS NULL OR max_provider_error_count >= 0)
            );
    END IF;
END $$;

ALTER TABLE qmeta.alert_event
    DROP CONSTRAINT IF EXISTS alert_event_alert_type_check;

ALTER TABLE qmeta.alert_event
    ADD CONSTRAINT alert_event_alert_type_check
    CHECK (alert_type IN (
        'missing_run',
        'pipeline_status',
        'pipeline_late',
        'completeness_below_sla',
        'conflict_rate_above_sla',
        'api_error_rate_above_sla',
        'duration_above_sla',
        'vendor_score_below_sla',
        'vendor_conflict_rate_above_sla',
        'vendor_failure_rate_above_sla',
        'vendor_latency_above_sla',
        'provider_error_count_above_sla',
        'budget_threshold_warning',
        'budget_exceeded',
        'budget_blocked',
        'budget_usage_spike',
        'runtime_metric_warning',
        'runtime_metric_critical',
        'runtime_capacity_warning',
        'runtime_capacity_critical',
        'runtime_daily_degraded',
        'free_source_recovery_required'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_field_mapping (
    mapping_id          BIGSERIAL PRIMARY KEY,
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    external_field      VARCHAR(128) NOT NULL,
    internal_field      VARCHAR(128) NOT NULL,
    transform_rule      VARCHAR(64) NOT NULL DEFAULT 'identity',
    unit_from           VARCHAR(64),
    unit_to             VARCHAR(64),
    is_required         BOOLEAN NOT NULL DEFAULT FALSE,
    priority            INTEGER NOT NULL DEFAULT 100,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, dataset_id, external_field),
    CHECK (status IN ('active', 'testing', 'paused', 'retired')),
    CHECK (priority >= 0),
    CHECK (transform_rule IN (
        'identity',
        'date_yyyymmdd',
        'volume_hand_to_share',
        'amount_thousand_to_yuan',
        'amount_wan_to_yuan',
        'pct_to_ratio',
        'bps_to_ratio'
    ))
);

CREATE INDEX IF NOT EXISTS idx_vendor_field_mapping_lookup
    ON qmeta.vendor_field_mapping(source_id, dataset_id, status, priority);

CREATE TABLE IF NOT EXISTS qmeta.provider_benchmark_suite_run (
    suite_id            BIGSERIAL PRIMARY KEY,
    suite_code          VARCHAR(180) NOT NULL UNIQUE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    target_trade_days   INTEGER,
    shard_size          INTEGER NOT NULL,
    max_symbols         INTEGER,
    symbol_count        BIGINT NOT NULL DEFAULT 0,
    shard_count         BIGINT NOT NULL DEFAULT 0,
    benchmark_count     BIGINT NOT NULL DEFAULT 0,
    primary_row_count   BIGINT NOT NULL DEFAULT 0,
    secondary_row_count BIGINT NOT NULL DEFAULT 0,
    matched_count       BIGINT NOT NULL DEFAULT 0,
    conflict_count      BIGINT NOT NULL DEFAULT 0,
    request_count       BIGINT NOT NULL DEFAULT 0,
    failure_count       BIGINT NOT NULL DEFAULT 0,
    coverage_rate       NUMERIC(12, 8),
    conflict_rate       NUMERIC(12, 8),
    failure_rate        NUMERIC(12, 8),
    p95_latency_ms      NUMERIC(18, 4),
    rows_per_second     NUMERIC(18, 4),
    status              VARCHAR(24) NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (target_trade_days IS NULL OR target_trade_days > 0),
    CHECK (shard_size > 0),
    CHECK (max_symbols IS NULL OR max_symbols > 0),
    CHECK (symbol_count >= 0),
    CHECK (shard_count >= 0),
    CHECK (benchmark_count >= 0),
    CHECK (primary_row_count >= 0),
    CHECK (secondary_row_count >= 0),
    CHECK (matched_count >= 0),
    CHECK (conflict_count >= 0),
    CHECK (request_count >= 0),
    CHECK (failure_count >= 0),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate IS NULL OR (conflict_rate >= 0 AND conflict_rate <= 1)),
    CHECK (failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)),
    CHECK (status IN ('success', 'warning', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_provider_benchmark_suite_run_dataset_date
    ON qmeta.provider_benchmark_suite_run(dataset_id, end_date DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.vendor_decision_report (
    report_id           BIGSERIAL PRIMARY KEY,
    report_code         VARCHAR(180) NOT NULL UNIQUE,
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    score_date          DATE NOT NULL,
    suite_id            BIGINT REFERENCES qmeta.provider_benchmark_suite_run(suite_id),
    total_score         NUMERIC(8, 4),
    rating              VARCHAR(16),
    recommendation      VARCHAR(32) NOT NULL,
    recommended_role    VARCHAR(32) NOT NULL,
    rationale           TEXT NOT NULL,
    blocking_issues     TEXT[] NOT NULL DEFAULT '{}',
    next_actions        TEXT[] NOT NULL DEFAULT '{}',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (recommendation IN ('approve_primary', 'approve_backup', 'watch', 'reject')),
    CHECK (recommended_role IN ('primary', 'backup', 'research_only', 'none')),
    CHECK (rating IS NULL OR rating IN ('A', 'B', 'C', 'D', 'unknown'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_decision_report_dataset_date
    ON qmeta.vendor_decision_report(dataset_id, score_date DESC, recommendation);
