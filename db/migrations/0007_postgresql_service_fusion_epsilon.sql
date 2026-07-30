-- A 股量化数据平台 Epsilon：多源融合、REST 服务、权限审计

CREATE TABLE IF NOT EXISTS qmeta.source_priority (
    priority_id         BIGSERIAL PRIMARY KEY,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    priority            INTEGER NOT NULL,
    is_fallback         BOOLEAN NOT NULL DEFAULT TRUE,
    effective_date      DATE NOT NULL DEFAULT DATE '1900-01-01',
    end_date            DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, source_id, effective_date),
    CHECK (priority >= 0),
    CHECK (end_date IS NULL OR end_date >= effective_date)
);

CREATE INDEX IF NOT EXISTS idx_source_priority_dataset_effective
    ON qmeta.source_priority(dataset_id, effective_date DESC, priority);

CREATE TABLE IF NOT EXISTS qmeta.data_conflict_daily (
    conflict_id         BIGSERIAL PRIMARY KEY,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    security_id         BIGINT REFERENCES qmeta.security_master(security_id),
    symbol              VARCHAR(32) NOT NULL,
    trade_date          DATE NOT NULL,
    field_name          VARCHAR(96) NOT NULL,
    primary_value       TEXT,
    secondary_value     TEXT,
    absolute_diff       NUMERIC(28, 12),
    relative_diff       NUMERIC(28, 12),
    severity            VARCHAR(24) NOT NULL DEFAULT 'low',
    status              VARCHAR(24) NOT NULL DEFAULT 'open',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, primary_source_id, secondary_source_id, symbol, trade_date, field_name),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'accepted', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS idx_data_conflict_daily_date_status
    ON qmeta.data_conflict_daily(trade_date DESC, status, severity);

CREATE INDEX IF NOT EXISTS idx_data_conflict_daily_dataset_date
    ON qmeta.data_conflict_daily(dataset_id, trade_date DESC, severity);

CREATE TABLE IF NOT EXISTS qmeta.api_token (
    token_id            BIGSERIAL PRIMARY KEY,
    token_hash          VARCHAR(128) NOT NULL UNIQUE,
    token_name          VARCHAR(128) NOT NULL,
    owner               VARCHAR(128),
    scopes              TEXT[] NOT NULL DEFAULT '{}',
    quota_per_min       INTEGER NOT NULL DEFAULT 120,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at        TIMESTAMPTZ,
    CHECK (quota_per_min > 0)
);

CREATE INDEX IF NOT EXISTS idx_api_token_active_owner
    ON qmeta.api_token(is_active, owner);

CREATE TABLE IF NOT EXISTS qmeta.api_request_audit (
    api_audit_id        BIGSERIAL PRIMARY KEY,
    token_id            BIGINT REFERENCES qmeta.api_token(token_id),
    api_name            VARCHAR(128) NOT NULL,
    request_id          VARCHAR(128),
    request_summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_format     VARCHAR(24) NOT NULL DEFAULT 'json',
    status              VARCHAR(24) NOT NULL,
    row_count           BIGINT,
    error_message       TEXT,
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    client_ip           INET,
    user_agent          TEXT,
    CHECK (status IN ('success', 'failed', 'partial_success')),
    CHECK (response_format IN ('json', 'csv', 'arrow'))
);

CREATE INDEX IF NOT EXISTS idx_api_request_audit_token_time
    ON qmeta.api_request_audit(token_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_request_audit_api_time
    ON qmeta.api_request_audit(api_name, started_at DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.multi_source_quality_daily (
    quality_id          BIGSERIAL PRIMARY KEY,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    trade_date          DATE NOT NULL,
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_count       BIGINT NOT NULL DEFAULT 0,
    secondary_count     BIGINT NOT NULL DEFAULT 0,
    matched_count       BIGINT NOT NULL DEFAULT 0,
    conflict_count      BIGINT NOT NULL DEFAULT 0,
    coverage_rate       NUMERIC(12, 8),
    conflict_rate       NUMERIC(12, 8),
    status              VARCHAR(24) NOT NULL DEFAULT 'pass',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, trade_date, primary_source_id, secondary_source_id),
    CHECK (primary_count >= 0),
    CHECK (secondary_count >= 0),
    CHECK (matched_count >= 0),
    CHECK (conflict_count >= 0),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate IS NULL OR (conflict_rate >= 0 AND conflict_rate <= 1)),
    CHECK (status IN ('pass', 'warning', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_multi_source_quality_daily_date_status
    ON qmeta.multi_source_quality_daily(trade_date DESC, status, conflict_rate DESC);
