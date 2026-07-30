-- A 股量化数据平台 Chi：多租户权限边界、项目治理视图和治理动作

CREATE TABLE IF NOT EXISTS qmeta.access_decision_audit (
    access_decision_id      BIGSERIAL PRIMARY KEY,
    decision_code           VARCHAR(220) NOT NULL UNIQUE,
    request_id              VARCHAR(128),
    token_id                BIGINT REFERENCES qmeta.api_token(token_id) ON DELETE SET NULL,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id) ON DELETE SET NULL,
    project_id              BIGINT REFERENCES qmeta.project(project_id) ON DELETE SET NULL,
    principal_id            BIGINT REFERENCES qmeta.principal(principal_id) ON DELETE SET NULL,
    dataset_id              BIGINT REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE SET NULL,
    access_id               BIGINT REFERENCES qmeta.dataset_access_policy(access_id) ON DELETE SET NULL,
    api_name                VARCHAR(128) NOT NULL DEFAULT 'manual',
    dataset_code            VARCHAR(128) NOT NULL,
    decision                VARCHAR(16) NOT NULL,
    required_access_level   VARCHAR(32) NOT NULL DEFAULT 'read',
    effective_access_level  VARCHAR(32),
    effective_scope         VARCHAR(32) NOT NULL DEFAULT 'none',
    requested_fields        TEXT[] NOT NULL DEFAULT '{}',
    denied_fields           TEXT[] NOT NULL DEFAULT '{}',
    reason                  TEXT,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    evaluated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decision IN ('allow', 'deny')),
    CHECK (required_access_level IN ('read', 'write', 'admin')),
    CHECK (effective_access_level IS NULL OR effective_access_level IN ('read', 'write', 'admin')),
    CHECK (effective_scope IN ('principal', 'project', 'tenant', 'compat', 'none'))
);

CREATE INDEX IF NOT EXISTS idx_access_decision_audit_project_time
    ON qmeta.access_decision_audit(project_id, evaluated_at DESC, decision);

CREATE INDEX IF NOT EXISTS idx_access_decision_audit_dataset_time
    ON qmeta.access_decision_audit(dataset_code, evaluated_at DESC, decision);

CREATE INDEX IF NOT EXISTS idx_access_decision_audit_token_time
    ON qmeta.access_decision_audit(token_id, evaluated_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.project_governance_snapshot (
    snapshot_id                 BIGSERIAL PRIMARY KEY,
    snapshot_code               VARCHAR(220) NOT NULL UNIQUE,
    snapshot_date               DATE NOT NULL,
    tenant_id                   BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id) ON DELETE CASCADE,
    project_id                  BIGINT NOT NULL REFERENCES qmeta.project(project_id) ON DELETE CASCADE,
    status                      VARCHAR(24) NOT NULL DEFAULT 'healthy',
    active_principal_count      INTEGER NOT NULL DEFAULT 0,
    active_token_count          INTEGER NOT NULL DEFAULT 0,
    dataset_policy_count        INTEGER NOT NULL DEFAULT 0,
    request_count_7d            BIGINT NOT NULL DEFAULT 0,
    failed_count_7d             BIGINT NOT NULL DEFAULT 0,
    error_rate_7d               NUMERIC(12, 8) NOT NULL DEFAULT 0,
    cost_units_7d               NUMERIC(24, 8) NOT NULL DEFAULT 0,
    denied_access_7d_count      BIGINT NOT NULL DEFAULT 0,
    budget_status               VARCHAR(24),
    budget_usage_pct            NUMERIC(12, 8),
    open_budget_alert_count     INTEGER NOT NULL DEFAULT 0,
    unpaid_invoice_count        INTEGER NOT NULL DEFAULT 0,
    overdue_invoice_count       INTEGER NOT NULL DEFAULT 0,
    open_governance_action_count INTEGER NOT NULL DEFAULT 0,
    risk_score                  NUMERIC(8, 4) NOT NULL DEFAULT 0,
    recommended_action          VARCHAR(64) NOT NULL DEFAULT 'monitor',
    details                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snapshot_date, project_id),
    CHECK (status IN ('healthy', 'warning', 'critical', 'paused')),
    CHECK (risk_score >= 0)
);

CREATE INDEX IF NOT EXISTS idx_project_governance_snapshot_status
    ON qmeta.project_governance_snapshot(snapshot_date DESC, status, risk_score DESC);

CREATE INDEX IF NOT EXISTS idx_project_governance_snapshot_project
    ON qmeta.project_governance_snapshot(project_id, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS qmeta.governance_action (
    action_id               BIGSERIAL PRIMARY KEY,
    action_code             VARCHAR(240) NOT NULL UNIQUE,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id) ON DELETE SET NULL,
    project_id              BIGINT REFERENCES qmeta.project(project_id) ON DELETE SET NULL,
    principal_id            BIGINT REFERENCES qmeta.principal(principal_id) ON DELETE SET NULL,
    token_id                BIGINT REFERENCES qmeta.api_token(token_id) ON DELETE SET NULL,
    dataset_id              BIGINT REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE SET NULL,
    snapshot_id             BIGINT REFERENCES qmeta.project_governance_snapshot(snapshot_id) ON DELETE SET NULL,
    action_type             VARCHAR(64) NOT NULL,
    severity                VARCHAR(24) NOT NULL DEFAULT 'medium',
    status                  VARCHAR(24) NOT NULL DEFAULT 'open',
    owner                   VARCHAR(128),
    reason                  TEXT NOT NULL,
    due_at                  TIMESTAMPTZ,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (action_type IN ('review_access_policy', 'review_budget', 'rotate_token', 'pause_project', 'contact_owner', 'monitor')),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'in_progress', 'done', 'dismissed'))
);

CREATE INDEX IF NOT EXISTS idx_governance_action_status
    ON qmeta.governance_action(status, severity, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_governance_action_project
    ON qmeta.governance_action(project_id, status, updated_at DESC);
