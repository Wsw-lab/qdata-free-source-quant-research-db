-- A 股量化数据平台 Pi：真实供应商全市场压测上线复核

CREATE TABLE IF NOT EXISTS qmeta.vendor_readiness_review (
    review_id                 BIGSERIAL PRIMARY KEY,
    review_code               VARCHAR(180) NOT NULL UNIQUE,
    dataset_id                BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id                 BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id         BIGINT REFERENCES qmeta.source_system(source_id),
    review_date               DATE NOT NULL DEFAULT CURRENT_DATE,
    required_windows          INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    suite_count               INTEGER NOT NULL DEFAULT 0,
    passed_window_count       INTEGER NOT NULL DEFAULT 0,
    warning_window_count      INTEGER NOT NULL DEFAULT 0,
    failed_window_count       INTEGER NOT NULL DEFAULT 0,
    missing_window_count      INTEGER NOT NULL DEFAULT 0,
    status                    VARCHAR(24) NOT NULL DEFAULT 'incomplete',
    recommendation            VARCHAR(32) NOT NULL DEFAULT 'watch',
    recommended_role          VARCHAR(32) NOT NULL DEFAULT 'research_only',
    min_coverage_rate         NUMERIC(12, 8) NOT NULL DEFAULT 0.95000000,
    max_conflict_rate         NUMERIC(12, 8) NOT NULL DEFAULT 0.00500000,
    max_failure_rate          NUMERIC(12, 8) NOT NULL DEFAULT 0.01000000,
    max_p95_latency_ms        NUMERIC(18, 4) NOT NULL DEFAULT 5000,
    min_rows_per_second       NUMERIC(18, 4) NOT NULL DEFAULT 0,
    observed_min_coverage_rate NUMERIC(12, 8),
    observed_max_conflict_rate NUMERIC(12, 8),
    observed_max_failure_rate  NUMERIC(12, 8),
    observed_max_p95_latency_ms NUMERIC(18, 4),
    observed_min_rows_per_second NUMERIC(18, 4),
    profile_status            VARCHAR(24),
    runtime_mode              VARCHAR(32) NOT NULL DEFAULT 'unknown',
    blocking_issues           TEXT[] NOT NULL DEFAULT '{}',
    next_actions              TEXT[] NOT NULL DEFAULT '{}',
    details                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (array_length(required_windows, 1) IS NOT NULL),
    CHECK (suite_count >= 0),
    CHECK (passed_window_count >= 0),
    CHECK (warning_window_count >= 0),
    CHECK (failed_window_count >= 0),
    CHECK (missing_window_count >= 0),
    CHECK (status IN ('ready', 'watch', 'rejected', 'incomplete')),
    CHECK (recommendation IN ('approve_primary', 'approve_backup', 'watch', 'reject')),
    CHECK (recommended_role IN ('primary', 'backup', 'research_only', 'none')),
    CHECK (min_coverage_rate >= 0 AND min_coverage_rate <= 1),
    CHECK (max_conflict_rate >= 0 AND max_conflict_rate <= 1),
    CHECK (max_failure_rate >= 0 AND max_failure_rate <= 1),
    CHECK (max_p95_latency_ms >= 0),
    CHECK (min_rows_per_second >= 0),
    CHECK (runtime_mode IN ('live', 'fixture', 'offline', 'unknown'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_readiness_review_lookup
    ON qmeta.vendor_readiness_review(dataset_id, source_id, review_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_readiness_review_recommendation
    ON qmeta.vendor_readiness_review(recommendation, recommended_role, review_date DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_readiness_window (
    window_id          BIGSERIAL PRIMARY KEY,
    review_id          BIGINT NOT NULL REFERENCES qmeta.vendor_readiness_review(review_id) ON DELETE CASCADE,
    window_days        INTEGER NOT NULL,
    suite_id           BIGINT REFERENCES qmeta.provider_benchmark_suite_run(suite_id) ON DELETE SET NULL,
    status             VARCHAR(24) NOT NULL DEFAULT 'missing',
    coverage_rate      NUMERIC(12, 8),
    conflict_rate      NUMERIC(12, 8),
    failure_rate       NUMERIC(12, 8),
    p95_latency_ms     NUMERIC(18, 4),
    rows_per_second    NUMERIC(18, 4),
    symbol_count       BIGINT NOT NULL DEFAULT 0,
    benchmark_count    BIGINT NOT NULL DEFAULT 0,
    blocking_issues    TEXT[] NOT NULL DEFAULT '{}',
    details            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (review_id, window_days),
    CHECK (window_days > 0),
    CHECK (status IN ('pass', 'warning', 'failed', 'missing')),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate IS NULL OR (conflict_rate >= 0 AND conflict_rate <= 1)),
    CHECK (failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)),
    CHECK (p95_latency_ms IS NULL OR p95_latency_ms >= 0),
    CHECK (rows_per_second IS NULL OR rows_per_second >= 0),
    CHECK (symbol_count >= 0),
    CHECK (benchmark_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_readiness_window_status
    ON qmeta.vendor_readiness_window(review_id, status, window_days);

CREATE INDEX IF NOT EXISTS idx_vendor_readiness_window_suite
    ON qmeta.vendor_readiness_window(suite_id);
