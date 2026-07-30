-- A 股量化数据平台 Kappa-5：免费源可靠性评分和自动降级快照

CREATE TABLE IF NOT EXISTS qmeta.free_source_reliability_snapshot (
    snapshot_id                       BIGSERIAL PRIMARY KEY,
    snapshot_code                     VARCHAR(180) NOT NULL UNIQUE,
    source_id                         BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                        BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    as_of_date                        DATE NOT NULL,
    lookback_hours                    INTEGER NOT NULL DEFAULT 24,
    status                            VARCHAR(32) NOT NULL DEFAULT 'no_data',
    recommended_role                  VARCHAR(32) NOT NULL DEFAULT 'research_only',
    reliability_score                 NUMERIC(8, 4) NOT NULL DEFAULT 0.0000,
    success_rate                      NUMERIC(10, 6),
    coverage_rate                     NUMERIC(10, 6),
    conflict_rate_bps                 NUMERIC(18, 6),
    observation_count                 INTEGER NOT NULL DEFAULT 0,
    success_count                     INTEGER NOT NULL DEFAULT 0,
    warning_count                     INTEGER NOT NULL DEFAULT 0,
    failed_count                      INTEGER NOT NULL DEFAULT 0,
    blocked_count                     INTEGER NOT NULL DEFAULT 0,
    consecutive_failure_count         INTEGER NOT NULL DEFAULT 0,
    license_status                    VARCHAR(32) NOT NULL DEFAULT 'unknown',
    commercial_clearance              VARCHAR(32) NOT NULL DEFAULT 'blocked',
    last_success_at                   TIMESTAMPTZ,
    last_failure_at                   TIMESTAMPTZ,
    degradation_reasons               TEXT[] NOT NULL DEFAULT '{}',
    recovery_actions                  TEXT[] NOT NULL DEFAULT '{}',
    evidence                          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (lookback_hours > 0),
    CHECK (status IN ('no_data', 'ready', 'watch', 'degraded', 'rejected')),
    CHECK (recommended_role IN ('validator', 'backup', 'research_only', 'degraded', 'reject')),
    CHECK (reliability_score >= 0 AND reliability_score <= 100),
    CHECK (success_rate IS NULL OR (success_rate >= 0 AND success_rate <= 1)),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate_bps IS NULL OR conflict_rate_bps >= 0),
    CHECK (observation_count >= 0),
    CHECK (success_count >= 0),
    CHECK (warning_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (blocked_count >= 0),
    CHECK (consecutive_failure_count >= 0),
    CHECK (license_status IN ('unknown', 'local_smoke', 'official_public', 'research_only', 'review_required', 'blocked')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked'))
);

CREATE INDEX IF NOT EXISTS idx_free_source_reliability_lookup
    ON qmeta.free_source_reliability_snapshot(as_of_date DESC, status, reliability_score DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_reliability_source_dataset
    ON qmeta.free_source_reliability_snapshot(source_id, dataset_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_reliability_role
    ON qmeta.free_source_reliability_snapshot(recommended_role, status, reliability_score DESC);
