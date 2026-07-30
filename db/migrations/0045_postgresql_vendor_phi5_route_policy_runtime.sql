-- Phi-5: active route-weight policy runtime routing and decision audit.

INSERT INTO qmeta.source_system (
    source_code, source_name, source_type, license_scope, update_frequency, latency_level, owner, is_active
)
VALUES
    ('csv', 'Local CSV Provider', 'internal', 'local deterministic fallback', 'daily', 'L4', 'platform-data', TRUE),
    ('csv_mirror', 'Local CSV Mirror Provider', 'internal', 'local deterministic fallback mirror', 'daily', 'L4', 'platform-data', TRUE),
    ('akshare', 'AkShare Free Adapter', 'vendor', 'research or validation only unless separately cleared', 'daily', 'L3', 'platform-data', TRUE),
    ('baostock', 'BaoStock Free Adapter', 'vendor', 'research or validation only unless separately cleared', 'daily', 'L3', 'platform-data', TRUE),
    ('tushare_free', 'Tushare Free Adapter', 'vendor', 'research or validation only unless separately cleared', 'daily', 'L3', 'platform-data', TRUE),
    ('commercial_http', 'Commercial HTTP Vendor Alias', 'vendor', 'commercial contract required; token value comes from environment', 'daily', 'L3', 'platform-data', TRUE)
ON CONFLICT (source_code) DO UPDATE SET
    source_name = EXCLUDED.source_name,
    source_type = EXCLUDED.source_type,
    license_scope = EXCLUDED.license_scope,
    update_frequency = EXCLUDED.update_frequency,
    latency_level = EXCLUDED.latency_level,
    owner = EXCLUDED.owner,
    is_active = TRUE,
    updated_at = now();

CREATE TABLE IF NOT EXISTS qmeta.source_route_decision_audit (
    decision_id                            BIGSERIAL PRIMARY KEY,
    decision_code                          VARCHAR(180) NOT NULL UNIQUE,
    policy_id                              BIGINT REFERENCES qmeta.source_route_weight_policy(policy_id) ON DELETE SET NULL,
    dataset_id                             BIGINT REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE SET NULL,
    requested_source_id                    BIGINT REFERENCES qmeta.source_system(source_id) ON DELETE SET NULL,
    selected_source_id                     BIGINT REFERENCES qmeta.source_system(source_id) ON DELETE SET NULL,
    final_source_id                        BIGINT REFERENCES qmeta.source_system(source_id) ON DELETE SET NULL,
    primary_source_id                      BIGINT REFERENCES qmeta.source_system(source_id) ON DELETE SET NULL,
    backup_source_id                       BIGINT REFERENCES qmeta.source_system(source_id) ON DELETE SET NULL,
    request_id                             VARCHAR(128),
    request_key                            VARCHAR(256),
    decision_context                       VARCHAR(32) NOT NULL DEFAULT 'sync',
    route_mode                             VARCHAR(32) NOT NULL DEFAULT 'default',
    decision_status                        VARCHAR(32) NOT NULL DEFAULT 'selected',
    selected_role                          VARCHAR(32) NOT NULL DEFAULT 'requested',
    effective_date                         DATE,
    primary_weight_pct                     NUMERIC(8, 4) NOT NULL DEFAULT 0,
    backup_weight_pct                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    free_source_weight_pct                 NUMERIC(8, 4) NOT NULL DEFAULT 0,
    selected_weight_pct                    NUMERIC(8, 4) NOT NULL DEFAULT 100,
    deterministic_bucket                   NUMERIC(8, 4) NOT NULL DEFAULT 0,
    fallback_attempted                     BOOLEAN NOT NULL DEFAULT FALSE,
    fallback_applied                       BOOLEAN NOT NULL DEFAULT FALSE,
    candidate_sources                      TEXT[] NOT NULL DEFAULT '{}',
    attempt_sources                        TEXT[] NOT NULL DEFAULT '{}',
    fallback_reason                        TEXT,
    row_count                              BIGINT,
    duration_ms                            BIGINT,
    error_message                          TEXT,
    details                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                            TIMESTAMPTZ,
    created_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decision_context IN ('sync', 'api', 'worker', 'smoke')),
    CHECK (route_mode IN ('default', 'policy_weighted', 'manual_override', 'fallback')),
    CHECK (decision_status IN ('selected', 'success', 'fallback_success', 'fallback_failed', 'failed', 'skipped')),
    CHECK (selected_role IN ('requested', 'primary', 'backup', 'free_source', 'fallback')),
    CHECK (primary_weight_pct >= 0 AND primary_weight_pct <= 100),
    CHECK (backup_weight_pct >= 0 AND backup_weight_pct <= 100),
    CHECK (free_source_weight_pct >= 0 AND free_source_weight_pct <= 100),
    CHECK (selected_weight_pct >= 0 AND selected_weight_pct <= 100),
    CHECK (deterministic_bucket >= 0 AND deterministic_bucket < 100),
    CHECK (row_count IS NULL OR row_count >= 0),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_source_route_decision_audit_lookup
    ON qmeta.source_route_decision_audit(dataset_id, decision_context, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_decision_audit_policy
    ON qmeta.source_route_decision_audit(policy_id, started_at DESC, decision_status);

CREATE INDEX IF NOT EXISTS idx_source_route_decision_audit_final_source
    ON qmeta.source_route_decision_audit(final_source_id, started_at DESC, fallback_applied);
