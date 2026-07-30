-- A 股量化数据平台 Eta：真实第二数据源接入、压测和供应商评分

CREATE TABLE IF NOT EXISTS qmeta.vendor_integration_profile (
    profile_id              BIGSERIAL PRIMARY KEY,
    source_id               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    provider_name           VARCHAR(64) NOT NULL,
    auth_mode               VARCHAR(32) NOT NULL DEFAULT 'none',
    endpoint_base           TEXT,
    enabled_datasets        TEXT[] NOT NULL DEFAULT '{}',
    rate_limit_per_min      INTEGER,
    retry_limit             INTEGER NOT NULL DEFAULT 2,
    timeout_ms              INTEGER NOT NULL DEFAULT 30000,
    license_scope           TEXT,
    redistribution_allowed  BOOLEAN,
    commercial_contract_ref VARCHAR(128),
    status                  VARCHAR(24) NOT NULL DEFAULT 'testing',
    owner                   VARCHAR(128),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, provider_name),
    CHECK (auth_mode IN ('none', 'bearer', 'header', 'query', 'basic')),
    CHECK (status IN ('testing', 'active', 'paused', 'retired')),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (retry_limit >= 0),
    CHECK (timeout_ms > 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_profile_status_provider
    ON qmeta.vendor_integration_profile(status, provider_name, source_id);

CREATE TABLE IF NOT EXISTS qmeta.provider_error_event (
    error_id            BIGSERIAL PRIMARY KEY,
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    dataset_id          BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    provider_name       VARCHAR(64) NOT NULL,
    trade_date          DATE,
    symbol              VARCHAR(32),
    error_stage         VARCHAR(64) NOT NULL,
    error_type          VARCHAR(64) NOT NULL,
    retryable           BOOLEAN NOT NULL DEFAULT FALSE,
    attempt             INTEGER,
    error_message       TEXT NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (error_stage IN ('auth', 'rate_limit', 'request', 'parse', 'normalize', 'load', 'compare', 'benchmark')),
    CHECK (error_type IN ('auth', 'rate_limit', 'timeout', 'network', 'server', 'client', 'schema', 'empty', 'unknown')),
    CHECK (attempt IS NULL OR attempt >= 0)
);

CREATE INDEX IF NOT EXISTS idx_provider_error_event_source_date
    ON qmeta.provider_error_event(provider_name, trade_date DESC, error_type);

CREATE TABLE IF NOT EXISTS qmeta.provider_benchmark_run (
    benchmark_id        BIGSERIAL PRIMARY KEY,
    benchmark_code      VARCHAR(160) NOT NULL UNIQUE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    symbol_count        BIGINT NOT NULL DEFAULT 0,
    date_count          BIGINT NOT NULL DEFAULT 0,
    primary_row_count   BIGINT NOT NULL DEFAULT 0,
    secondary_row_count BIGINT NOT NULL DEFAULT 0,
    matched_count       BIGINT NOT NULL DEFAULT 0,
    conflict_count      BIGINT NOT NULL DEFAULT 0,
    request_count       BIGINT NOT NULL DEFAULT 0,
    failure_count       BIGINT NOT NULL DEFAULT 0,
    coverage_rate       NUMERIC(12, 8),
    conflict_rate       NUMERIC(12, 8),
    failure_rate        NUMERIC(12, 8),
    total_duration_ms   BIGINT,
    p50_latency_ms      NUMERIC(18, 4),
    p95_latency_ms      NUMERIC(18, 4),
    rows_per_second     NUMERIC(18, 4),
    status              VARCHAR(24) NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (symbol_count >= 0),
    CHECK (date_count >= 0),
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

CREATE INDEX IF NOT EXISTS idx_provider_benchmark_run_dataset_date
    ON qmeta.provider_benchmark_run(dataset_id, end_date DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.vendor_quality_score_daily (
    score_id            BIGSERIAL PRIMARY KEY,
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    score_date          DATE NOT NULL,
    benchmark_id        BIGINT REFERENCES qmeta.provider_benchmark_run(benchmark_id),
    coverage_rate       NUMERIC(12, 8),
    conflict_rate       NUMERIC(12, 8),
    failure_rate        NUMERIC(12, 8),
    latency_ms          NUMERIC(18, 4),
    coverage_score      NUMERIC(8, 4),
    conflict_score      NUMERIC(8, 4),
    stability_score     NUMERIC(8, 4),
    latency_score       NUMERIC(8, 4),
    cost_score          NUMERIC(8, 4),
    license_risk_score  NUMERIC(8, 4),
    total_score         NUMERIC(8, 4),
    rating              VARCHAR(16) NOT NULL DEFAULT 'unknown',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, dataset_id, score_date),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate IS NULL OR (conflict_rate >= 0 AND conflict_rate <= 1)),
    CHECK (failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)),
    CHECK (rating IN ('A', 'B', 'C', 'D', 'unknown'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_quality_score_daily_dataset_score
    ON qmeta.vendor_quality_score_daily(dataset_id, score_date DESC, total_score DESC);
