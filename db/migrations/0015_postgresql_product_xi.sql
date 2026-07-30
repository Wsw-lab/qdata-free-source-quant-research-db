-- A 股量化数据平台 Xi：数据产品目录、计费价格表、订阅和预算告警

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

CREATE TABLE IF NOT EXISTS qmeta.data_product (
    product_id          BIGSERIAL PRIMARY KEY,
    product_code        VARCHAR(128) NOT NULL UNIQUE,
    product_name        VARCHAR(160) NOT NULL,
    product_type        VARCHAR(32) NOT NULL DEFAULT 'dataset_bundle',
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    billing_unit        VARCHAR(32) NOT NULL DEFAULT 'cost_unit',
    update_frequency    VARCHAR(64),
    sla_level           VARCHAR(64),
    license_scope       TEXT,
    owner               VARCHAR(128),
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (product_type IN ('dataset_bundle', 'api_bundle', 'export', 'package')),
    CHECK (status IN ('active', 'testing', 'paused', 'retired')),
    CHECK (billing_unit IN ('request', 'row', 'cost_unit', 'export', 'month'))
);

CREATE INDEX IF NOT EXISTS idx_data_product_status_type
    ON qmeta.data_product(status, product_type, product_code);

CREATE TABLE IF NOT EXISTS qmeta.data_product_dataset (
    product_id          BIGINT NOT NULL REFERENCES qmeta.data_product(product_id) ON DELETE CASCADE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    access_level        VARCHAR(32) NOT NULL DEFAULT 'read',
    is_required         BOOLEAN NOT NULL DEFAULT TRUE,
    field_allowlist     TEXT[] NOT NULL DEFAULT '{}',
    field_denylist      TEXT[] NOT NULL DEFAULT '{}',
    row_filter          JSONB NOT NULL DEFAULT '{}'::jsonb,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, dataset_id),
    CHECK (access_level IN ('read', 'write', 'admin'))
);

CREATE INDEX IF NOT EXISTS idx_data_product_dataset_dataset
    ON qmeta.data_product_dataset(dataset_id, product_id);

CREATE TABLE IF NOT EXISTS qmeta.data_product_api (
    product_id          BIGINT NOT NULL REFERENCES qmeta.data_product(product_id) ON DELETE CASCADE,
    api_name            VARCHAR(128) NOT NULL,
    required_scope      VARCHAR(64) NOT NULL DEFAULT 'read',
    is_billable         BOOLEAN NOT NULL DEFAULT TRUE,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, api_name)
);

CREATE INDEX IF NOT EXISTS idx_data_product_api_name
    ON qmeta.data_product_api(api_name, is_billable);

CREATE TABLE IF NOT EXISTS qmeta.pricing_plan (
    plan_id             BIGSERIAL PRIMARY KEY,
    plan_code           VARCHAR(128) NOT NULL UNIQUE,
    plan_name           VARCHAR(160) NOT NULL,
    billing_cycle       VARCHAR(32) NOT NULL DEFAULT 'monthly',
    currency            VARCHAR(16) NOT NULL DEFAULT 'CNY',
    base_fee            NUMERIC(24, 8) NOT NULL DEFAULT 0,
    included_cost_units NUMERIC(24, 8) NOT NULL DEFAULT 0,
    included_requests   BIGINT NOT NULL DEFAULT 0,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (billing_cycle IN ('daily', 'monthly', 'annual', 'prepaid', 'usage')),
    CHECK (status IN ('active', 'testing', 'paused', 'retired')),
    CHECK (base_fee >= 0),
    CHECK (included_cost_units >= 0),
    CHECK (included_requests >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.pricing_rule (
    rule_id             BIGSERIAL PRIMARY KEY,
    plan_id             BIGINT NOT NULL REFERENCES qmeta.pricing_plan(plan_id) ON DELETE CASCADE,
    product_id          BIGINT REFERENCES qmeta.data_product(product_id) ON DELETE SET NULL,
    rule_code           VARCHAR(160) NOT NULL UNIQUE,
    metric_name         VARCHAR(32) NOT NULL DEFAULT 'cost_unit',
    api_name            VARCHAR(128),
    unit_price          NUMERIC(24, 10) NOT NULL DEFAULT 0,
    free_quantity       NUMERIC(24, 8) NOT NULL DEFAULT 0,
    tier_start          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    tier_end            NUMERIC(24, 8),
    effective_from      DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_to        DATE,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (metric_name IN ('request', 'row', 'cost_unit', 'export', 'monthly_fee')),
    CHECK (status IN ('active', 'testing', 'paused', 'retired')),
    CHECK (unit_price >= 0),
    CHECK (free_quantity >= 0),
    CHECK (tier_start >= 0),
    CHECK (tier_end IS NULL OR tier_end >= tier_start),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX IF NOT EXISTS idx_pricing_rule_lookup
    ON qmeta.pricing_rule(plan_id, product_id, api_name, metric_name, status, effective_from DESC);

CREATE TABLE IF NOT EXISTS qmeta.product_subscription (
    subscription_id     BIGSERIAL PRIMARY KEY,
    subscription_code   VARCHAR(160) NOT NULL UNIQUE,
    tenant_id           BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    plan_id             BIGINT NOT NULL REFERENCES qmeta.pricing_plan(plan_id),
    product_id          BIGINT NOT NULL REFERENCES qmeta.data_product(product_id),
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    starts_on           DATE NOT NULL DEFAULT CURRENT_DATE,
    ends_on             DATE,
    auto_renew          BOOLEAN NOT NULL DEFAULT TRUE,
    hard_limit_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('active', 'paused', 'cancelled', 'expired')),
    CHECK (ends_on IS NULL OR ends_on >= starts_on)
);

CREATE INDEX IF NOT EXISTS idx_product_subscription_lookup
    ON qmeta.product_subscription(tenant_id, project_id, product_id, status, starts_on, ends_on);

CREATE TABLE IF NOT EXISTS qmeta.budget_policy (
    budget_id           BIGSERIAL PRIMARY KEY,
    budget_code         VARCHAR(160) NOT NULL UNIQUE,
    budget_name         VARCHAR(160) NOT NULL,
    tenant_id           BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    principal_id        BIGINT REFERENCES qmeta.principal(principal_id),
    cost_center         VARCHAR(128),
    plan_id             BIGINT REFERENCES qmeta.pricing_plan(plan_id),
    product_id          BIGINT REFERENCES qmeta.data_product(product_id),
    period              VARCHAR(32) NOT NULL DEFAULT 'monthly',
    budget_amount       NUMERIC(24, 8) NOT NULL,
    currency            VARCHAR(16) NOT NULL DEFAULT 'CNY',
    soft_threshold_pct  NUMERIC(8, 4) NOT NULL DEFAULT 0.7000,
    hard_threshold_pct  NUMERIC(8, 4) NOT NULL DEFAULT 1.0000,
    hard_limit_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    starts_on           DATE NOT NULL DEFAULT CURRENT_DATE,
    ends_on             DATE,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period IN ('daily', 'monthly')),
    CHECK (budget_amount > 0),
    CHECK (soft_threshold_pct >= 0 AND soft_threshold_pct <= 1),
    CHECK (hard_threshold_pct >= 0 AND hard_threshold_pct <= 10),
    CHECK (hard_threshold_pct >= soft_threshold_pct),
    CHECK (status IN ('active', 'paused', 'retired')),
    CHECK (ends_on IS NULL OR ends_on >= starts_on),
    CHECK (tenant_id IS NOT NULL OR project_id IS NOT NULL OR principal_id IS NOT NULL OR cost_center IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_budget_policy_lookup
    ON qmeta.budget_policy(status, tenant_id, project_id, principal_id, cost_center, period);

CREATE TABLE IF NOT EXISTS qmeta.budget_usage_snapshot (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    snapshot_code       VARCHAR(180) NOT NULL UNIQUE,
    budget_id           BIGINT NOT NULL REFERENCES qmeta.budget_policy(budget_id) ON DELETE CASCADE,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    usage_amount        NUMERIC(24, 8) NOT NULL DEFAULT 0,
    budget_amount       NUMERIC(24, 8) NOT NULL,
    usage_pct           NUMERIC(12, 8) NOT NULL DEFAULT 0,
    request_count       BIGINT NOT NULL DEFAULT 0,
    row_count           BIGINT NOT NULL DEFAULT 0,
    cost_units          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    status              VARCHAR(24) NOT NULL DEFAULT 'normal',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (budget_id, period_start, period_end),
    CHECK (period_end >= period_start),
    CHECK (usage_amount >= 0),
    CHECK (budget_amount > 0),
    CHECK (usage_pct >= 0),
    CHECK (request_count >= 0),
    CHECK (row_count >= 0),
    CHECK (cost_units >= 0),
    CHECK (status IN ('normal', 'warning', 'exceeded', 'blocked'))
);

CREATE INDEX IF NOT EXISTS idx_budget_usage_snapshot_status
    ON qmeta.budget_usage_snapshot(status, period_start DESC, usage_amount DESC);

CREATE TABLE IF NOT EXISTS qmeta.budget_alert (
    budget_alert_id     BIGSERIAL PRIMARY KEY,
    alert_key           VARCHAR(256) NOT NULL UNIQUE,
    budget_id           BIGINT NOT NULL REFERENCES qmeta.budget_policy(budget_id) ON DELETE CASCADE,
    snapshot_id         BIGINT REFERENCES qmeta.budget_usage_snapshot(snapshot_id) ON DELETE SET NULL,
    alert_type          VARCHAR(64) NOT NULL,
    severity            VARCHAR(24) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'open',
    threshold_pct       NUMERIC(8, 4),
    usage_pct           NUMERIC(12, 8) NOT NULL DEFAULT 0,
    message             TEXT NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (alert_type IN ('budget_threshold_warning', 'budget_exceeded', 'budget_blocked', 'budget_usage_spike')),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'acknowledged', 'resolved', 'ignored')),
    CHECK (threshold_pct IS NULL OR threshold_pct >= 0),
    CHECK (usage_pct >= 0)
);

CREATE INDEX IF NOT EXISTS idx_budget_alert_status
    ON qmeta.budget_alert(status, severity, last_seen_at DESC);
