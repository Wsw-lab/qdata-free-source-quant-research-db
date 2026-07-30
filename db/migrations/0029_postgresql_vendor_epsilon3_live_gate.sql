-- A 股量化数据平台 Epsilon-3：真实供应商 live token 压测门禁

CREATE TABLE IF NOT EXISTS qmeta.vendor_live_gate_run (
    gate_id                  BIGSERIAL PRIMARY KEY,
    gate_code                VARCHAR(180) NOT NULL UNIQUE,
    dataset_id               BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id                BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id        BIGINT REFERENCES qmeta.source_system(source_id),
    profile_id               BIGINT REFERENCES qmeta.vendor_integration_profile(profile_id) ON DELETE SET NULL,
    review_id                BIGINT REFERENCES qmeta.vendor_readiness_review(review_id) ON DELETE SET NULL,
    requested_by             VARCHAR(128) NOT NULL DEFAULT 'epsilon3',
    trigger_mode             VARCHAR(32) NOT NULL DEFAULT 'manual',
    run_mode                 VARCHAR(32) NOT NULL DEFAULT 'blocked',
    status                   VARCHAR(32) NOT NULL DEFAULT 'planned',
    start_date               DATE NOT NULL,
    end_date                 DATE NOT NULL,
    required_windows         INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    executed_windows         INTEGER[] NOT NULL DEFAULT '{}',
    shard_size               INTEGER NOT NULL DEFAULT 500,
    max_symbols              INTEGER,
    symbol_count             BIGINT,
    allow_live               BOOLEAN NOT NULL DEFAULT FALSE,
    require_live             BOOLEAN NOT NULL DEFAULT FALSE,
    require_active_profile   BOOLEAN NOT NULL DEFAULT TRUE,
    require_contract         BOOLEAN NOT NULL DEFAULT TRUE,
    run_benchmarks           BOOLEAN NOT NULL DEFAULT FALSE,
    live_base_url_env        VARCHAR(128) NOT NULL DEFAULT 'QDATA_VENDOR_BASE_URL',
    live_token_env           VARCHAR(128) NOT NULL DEFAULT 'QDATA_VENDOR_TOKEN',
    live_base_url_present    BOOLEAN NOT NULL DEFAULT FALSE,
    live_token_present       BOOLEAN NOT NULL DEFAULT FALSE,
    profile_status           VARCHAR(24),
    runtime_mode             VARCHAR(32) NOT NULL DEFAULT 'unknown',
    review_code              VARCHAR(180),
    readiness_status         VARCHAR(24),
    recommendation           VARCHAR(32),
    recommended_role         VARCHAR(32),
    suite_ids                BIGINT[] NOT NULL DEFAULT '{}',
    suite_codes              TEXT[] NOT NULL DEFAULT '{}',
    blocking_issues          TEXT[] NOT NULL DEFAULT '{}',
    next_actions             TEXT[] NOT NULL DEFAULT '{}',
    request_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message            TEXT,
    started_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at              TIMESTAMPTZ,
    duration_ms              INTEGER,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (array_length(required_windows, 1) IS NOT NULL),
    CHECK (shard_size > 0),
    CHECK (max_symbols IS NULL OR max_symbols > 0),
    CHECK (symbol_count IS NULL OR symbol_count >= 0),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (run_mode IN ('blocked', 'plan', 'live')),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (runtime_mode IN ('live', 'fixture', 'offline', 'unknown'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_live_gate_run_lookup
    ON qmeta.vendor_live_gate_run(dataset_id, source_id, started_at DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_live_gate_run_status
    ON qmeta.vendor_live_gate_run(status, run_mode, started_at DESC);

INSERT INTO qmeta.source_system (
    source_code, source_name, source_type, license_scope, update_frequency, latency_level, owner, is_active
) VALUES (
    'vendor_http',
    'Commercial HTTP Vendor',
    'vendor',
    'commercial contract required; token value comes from environment',
    'daily',
    'L3',
    'platform-data',
    TRUE
)
ON CONFLICT (source_code) DO UPDATE SET
    source_name = EXCLUDED.source_name,
    source_type = EXCLUDED.source_type,
    license_scope = EXCLUDED.license_scope,
    update_frequency = EXCLUDED.update_frequency,
    latency_level = EXCLUDED.latency_level,
    owner = EXCLUDED.owner,
    is_active = TRUE,
    updated_at = now();

INSERT INTO qmeta.vendor_integration_profile (
    source_id, provider_name, auth_mode, endpoint_base, enabled_datasets,
    rate_limit_per_min, retry_limit, timeout_ms, license_scope,
    redistribution_allowed, commercial_contract_ref, status, owner, details
)
SELECT
    ss.source_id,
    'vendor_http',
    'bearer',
    NULL,
    ARRAY['daily_bar', 'adjustment_factor', 'limit_price_daily', 'security_master']::text[],
    120,
    2,
    30000,
    'commercial contract required; live token must be provided by QDATA_VENDOR_TOKEN',
    NULL,
    NULL,
    'testing',
    'platform-data',
    '{
      "source":"epsilon3",
      "endpoint_env_var":"QDATA_VENDOR_BASE_URL",
      "token_env_var":"QDATA_VENDOR_TOKEN",
      "daily_path_env_var":"QDATA_VENDOR_DAILY_PATH",
      "token_storage":"env_var_only"
    }'::jsonb
FROM qmeta.source_system ss
WHERE ss.source_code = 'vendor_http'
ON CONFLICT (source_id, provider_name) DO UPDATE SET
    auth_mode = CASE
        WHEN qmeta.vendor_integration_profile.auth_mode = 'none' THEN EXCLUDED.auth_mode
        ELSE qmeta.vendor_integration_profile.auth_mode
    END,
    endpoint_base = COALESCE(qmeta.vendor_integration_profile.endpoint_base, EXCLUDED.endpoint_base),
    enabled_datasets = CASE
        WHEN qmeta.vendor_integration_profile.enabled_datasets = '{}'::text[] THEN EXCLUDED.enabled_datasets
        ELSE qmeta.vendor_integration_profile.enabled_datasets
    END,
    rate_limit_per_min = COALESCE(qmeta.vendor_integration_profile.rate_limit_per_min, EXCLUDED.rate_limit_per_min),
    retry_limit = qmeta.vendor_integration_profile.retry_limit,
    timeout_ms = qmeta.vendor_integration_profile.timeout_ms,
    license_scope = COALESCE(qmeta.vendor_integration_profile.license_scope, EXCLUDED.license_scope),
    owner = COALESCE(qmeta.vendor_integration_profile.owner, EXCLUDED.owner),
    details = qmeta.vendor_integration_profile.details || EXCLUDED.details,
    updated_at = now();
