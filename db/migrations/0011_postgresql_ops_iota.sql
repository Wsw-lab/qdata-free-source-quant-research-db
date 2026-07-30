-- A 股量化数据平台 Iota：生产通知、租户权限、用量计量和供应商压测调度

CREATE TABLE IF NOT EXISTS qmeta.tenant (
    tenant_id           BIGSERIAL PRIMARY KEY,
    tenant_code         VARCHAR(96) NOT NULL UNIQUE,
    tenant_name         VARCHAR(128) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    owner               VARCHAR(128),
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE TABLE IF NOT EXISTS qmeta.project (
    project_id          BIGSERIAL PRIMARY KEY,
    tenant_id           BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    project_code        VARCHAR(96) NOT NULL,
    project_name        VARCHAR(128) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    owner               VARCHAR(128),
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, project_code),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE TABLE IF NOT EXISTS qmeta.principal (
    principal_id        BIGSERIAL PRIMARY KEY,
    tenant_id           BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    principal_code      VARCHAR(128) NOT NULL,
    principal_name      VARCHAR(128) NOT NULL,
    principal_type      VARCHAR(32) NOT NULL DEFAULT 'service_account',
    email               VARCHAR(256),
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, principal_code),
    CHECK (principal_type IN ('user', 'service_account')),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE TABLE IF NOT EXISTS qmeta.project_member (
    member_id           BIGSERIAL PRIMARY KEY,
    project_id          BIGINT NOT NULL REFERENCES qmeta.project(project_id),
    principal_id        BIGINT NOT NULL REFERENCES qmeta.principal(principal_id),
    role                VARCHAR(32) NOT NULL DEFAULT 'viewer',
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, principal_id),
    CHECK (role IN ('owner', 'admin', 'researcher', 'viewer', 'service')),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE TABLE IF NOT EXISTS qmeta.dataset_access_policy (
    access_id           BIGSERIAL PRIMARY KEY,
    tenant_id           BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    principal_id        BIGINT REFERENCES qmeta.principal(principal_id),
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    access_level        VARCHAR(32) NOT NULL DEFAULT 'read',
    field_allowlist     TEXT[] NOT NULL DEFAULT '{}',
    field_denylist      TEXT[] NOT NULL DEFAULT '{}',
    row_filter          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (access_level IN ('read', 'write', 'admin')),
    CHECK (status IN ('active', 'paused', 'retired')),
    CHECK (tenant_id IS NOT NULL OR project_id IS NOT NULL OR principal_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_dataset_access_policy_lookup
    ON qmeta.dataset_access_policy(dataset_id, status, tenant_id, project_id, principal_id);

ALTER TABLE qmeta.api_token
    ADD COLUMN IF NOT EXISTS tenant_id BIGINT REFERENCES qmeta.tenant(tenant_id),
    ADD COLUMN IF NOT EXISTS project_id BIGINT REFERENCES qmeta.project(project_id),
    ADD COLUMN IF NOT EXISTS principal_id BIGINT REFERENCES qmeta.principal(principal_id),
    ADD COLUMN IF NOT EXISTS cost_center VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_api_token_tenant_project
    ON qmeta.api_token(tenant_id, project_id, principal_id, is_active);

ALTER TABLE qmeta.api_request_audit
    ADD COLUMN IF NOT EXISTS tenant_id BIGINT REFERENCES qmeta.tenant(tenant_id),
    ADD COLUMN IF NOT EXISTS project_id BIGINT REFERENCES qmeta.project(project_id),
    ADD COLUMN IF NOT EXISTS principal_id BIGINT REFERENCES qmeta.principal(principal_id),
    ADD COLUMN IF NOT EXISTS cost_units NUMERIC(18, 6);

CREATE INDEX IF NOT EXISTS idx_api_request_audit_project_time
    ON qmeta.api_request_audit(project_id, started_at DESC, api_name);

CREATE TABLE IF NOT EXISTS qmeta.api_usage_daily (
    usage_id            BIGSERIAL PRIMARY KEY,
    usage_date          DATE NOT NULL,
    tenant_id           BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    principal_id        BIGINT REFERENCES qmeta.principal(principal_id),
    token_id            BIGINT REFERENCES qmeta.api_token(token_id),
    api_name            VARCHAR(128) NOT NULL,
    request_count       BIGINT NOT NULL DEFAULT 0,
    failed_count        BIGINT NOT NULL DEFAULT 0,
    row_count           BIGINT NOT NULL DEFAULT 0,
    duration_ms         BIGINT NOT NULL DEFAULT 0,
    cost_units          NUMERIC(18, 6) NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (usage_date, tenant_id, project_id, principal_id, token_id, api_name),
    CHECK (request_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (row_count >= 0),
    CHECK (duration_ms >= 0),
    CHECK (cost_units >= 0)
);

CREATE INDEX IF NOT EXISTS idx_api_usage_daily_project_date
    ON qmeta.api_usage_daily(project_id, usage_date DESC, cost_units DESC);

CREATE TABLE IF NOT EXISTS qmeta.notification_channel (
    channel_id          BIGSERIAL PRIMARY KEY,
    channel_code        VARCHAR(128) NOT NULL UNIQUE,
    channel_name        VARCHAR(128) NOT NULL,
    channel_type        VARCHAR(32) NOT NULL,
    endpoint            TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    min_severity        VARCHAR(24) NOT NULL DEFAULT 'low',
    config              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (channel_type IN ('stdout', 'webhook', 'email', 'feishu')),
    CHECK (min_severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE TABLE IF NOT EXISTS qmeta.alert_notification_delivery (
    delivery_id         BIGSERIAL PRIMARY KEY,
    alert_id            BIGINT NOT NULL REFERENCES qmeta.alert_event(alert_id),
    channel_id          BIGINT NOT NULL REFERENCES qmeta.notification_channel(channel_id),
    delivery_key        VARCHAR(256) NOT NULL UNIQUE,
    status              VARCHAR(24) NOT NULL DEFAULT 'pending',
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    last_attempt_at     TIMESTAMPTZ,
    delivered_at        TIMESTAMPTZ,
    response_summary    TEXT,
    error_message       TEXT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    CHECK (attempt_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_alert_notification_delivery_status
    ON qmeta.alert_notification_delivery(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_benchmark_schedule (
    schedule_id         BIGSERIAL PRIMARY KEY,
    schedule_code       VARCHAR(160) NOT NULL UNIQUE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    target_trade_days   INTEGER,
    shard_size          INTEGER NOT NULL DEFAULT 500,
    max_symbols         INTEGER,
    cadence             VARCHAR(32) NOT NULL DEFAULT 'manual',
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    last_suite_id       BIGINT REFERENCES qmeta.provider_benchmark_suite_run(suite_id),
    last_run_at         TIMESTAMPTZ,
    next_run_at         TIMESTAMPTZ,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (target_trade_days IS NULL OR target_trade_days > 0),
    CHECK (shard_size > 0),
    CHECK (max_symbols IS NULL OR max_symbols > 0),
    CHECK (cadence IN ('manual', 'daily', 'weekly', 'monthly')),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_benchmark_schedule_due
    ON qmeta.vendor_benchmark_schedule(status, next_run_at, cadence);
