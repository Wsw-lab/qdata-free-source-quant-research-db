-- Omicron-5: authorized primary vendor procurement, contract and entitlement readiness.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review'
    ));

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

INSERT INTO qmeta.dataset_catalog (
    dataset_code, dataset_name, asset_type, frequency, storage_layer, pit_required, description, is_active
)
SELECT
    seed.dataset_code,
    seed.dataset_name,
    seed.asset_type,
    seed.frequency,
    seed.storage_layer,
    seed.pit_required,
    seed.description,
    TRUE
FROM (
    VALUES
        ('daily_bar', 'A-share daily bar', 'stock', 'daily', 'clickhouse', FALSE, 'Daily OHLCV market bars for quantitative research and production routing'),
        ('security_master', 'Security master', 'stock', 'daily', 'postgresql', TRUE, 'A-share instrument identity, listing status and name history'),
        ('trading_calendar', 'Trading calendar', 'market', 'daily', 'postgresql', FALSE, 'Exchange trading day and session calendar'),
        ('adjustment_factor', 'Adjustment factor', 'stock', 'daily', 'postgresql', TRUE, 'Forward/backward adjustment factors for price normalization'),
        ('limit_price_daily', 'Daily limit price', 'stock', 'daily', 'postgresql', FALSE, 'Daily limit-up and limit-down price constraints'),
        ('financial_metric_pit', 'PIT financial metric', 'stock', 'quarterly', 'postgresql', TRUE, 'Point-in-time financial metrics with announce and ingest time'),
        ('financial_statement_pit', 'PIT financial statement', 'stock', 'quarterly', 'postgresql', TRUE, 'Point-in-time financial statements with announce and ingest time')
) AS seed(dataset_code, dataset_name, asset_type, frequency, storage_layer, pit_required, description)
ON CONFLICT (dataset_code) DO UPDATE SET
    dataset_name = COALESCE(qmeta.dataset_catalog.dataset_name, EXCLUDED.dataset_name),
    asset_type = COALESCE(qmeta.dataset_catalog.asset_type, EXCLUDED.asset_type),
    frequency = COALESCE(qmeta.dataset_catalog.frequency, EXCLUDED.frequency),
    storage_layer = COALESCE(qmeta.dataset_catalog.storage_layer, EXCLUDED.storage_layer),
    pit_required = qmeta.dataset_catalog.pit_required OR EXCLUDED.pit_required,
    description = COALESCE(qmeta.dataset_catalog.description, EXCLUDED.description),
    is_active = TRUE,
    updated_at = now();

CREATE TABLE IF NOT EXISTS qmeta.vendor_contract_profile (
    contract_id                    BIGSERIAL PRIMARY KEY,
    contract_code                  VARCHAR(180) NOT NULL UNIQUE,
    source_id                      BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    profile_id                     BIGINT REFERENCES qmeta.vendor_integration_profile(profile_id) ON DELETE SET NULL,
    provider_name                  VARCHAR(128) NOT NULL,
    vendor_account_code            VARCHAR(128),
    procurement_status             VARCHAR(32) NOT NULL DEFAULT 'review_required',
    contract_status                VARCHAR(32) NOT NULL DEFAULT 'draft',
    commercial_clearance           VARCHAR(32) NOT NULL DEFAULT 'review_required',
    redistribution_allowed         VARCHAR(16) NOT NULL DEFAULT 'unknown',
    production_use_allowed         BOOLEAN NOT NULL DEFAULT FALSE,
    contract_ref                   VARCHAR(180),
    contract_owner                 VARCHAR(128),
    legal_owner                    VARCHAR(128),
    business_owner                 VARCHAR(128),
    contract_start_date            DATE,
    contract_end_date              DATE,
    sla_tier                       VARCHAR(32) NOT NULL DEFAULT 'unknown',
    sla_uptime_pct                 NUMERIC(6, 3),
    support_sla_hours              INTEGER,
    rate_limit_per_min             INTEGER,
    daily_quota                    BIGINT,
    monthly_quota                  BIGINT,
    billing_model                  VARCHAR(32) NOT NULL DEFAULT 'unknown',
    billing_currency               VARCHAR(16) NOT NULL DEFAULT 'CNY',
    monthly_fee                    NUMERIC(20, 6),
    unit_cost                      NUMERIC(20, 8),
    data_scope                     TEXT[] NOT NULL DEFAULT '{}',
    status                         VARCHAR(32) NOT NULL DEFAULT 'active',
    reviewed_by                    VARCHAR(128),
    reviewed_at                    TIMESTAMPTZ,
    next_review_at                 TIMESTAMPTZ,
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (procurement_status IN ('draft', 'review_required', 'active', 'suspended', 'expired', 'terminated', 'blocked')),
    CHECK (contract_status IN ('none', 'draft', 'active', 'expired', 'terminated')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (sla_tier IN ('unknown', 'bronze', 'silver', 'gold', 'platinum', 'enterprise')),
    CHECK (billing_model IN ('unknown', 'free_trial', 'fixed', 'usage', 'tiered', 'enterprise')),
    CHECK (status IN ('active', 'inactive', 'expired', 'blocked')),
    CHECK (contract_end_date IS NULL OR contract_start_date IS NULL OR contract_end_date >= contract_start_date),
    CHECK (sla_uptime_pct IS NULL OR (sla_uptime_pct >= 0 AND sla_uptime_pct <= 100)),
    CHECK (support_sla_hours IS NULL OR support_sla_hours >= 0),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0),
    CHECK (monthly_quota IS NULL OR monthly_quota > 0),
    CHECK (monthly_fee IS NULL OR monthly_fee >= 0),
    CHECK (unit_cost IS NULL OR unit_cost >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_profile_source
    ON qmeta.vendor_contract_profile(source_id, status, procurement_status);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_profile_contract_status
    ON qmeta.vendor_contract_profile(contract_status, commercial_clearance, redistribution_allowed, production_use_allowed);

CREATE TABLE IF NOT EXISTS qmeta.vendor_contract_dataset_entitlement (
    entitlement_id                 BIGSERIAL PRIMARY KEY,
    entitlement_code               VARCHAR(180) NOT NULL UNIQUE,
    contract_id                    BIGINT NOT NULL REFERENCES qmeta.vendor_contract_profile(contract_id) ON DELETE CASCADE,
    source_id                      BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                     BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    entitlement_status             VARCHAR(32) NOT NULL DEFAULT 'review_required',
    allowed_role                   VARCHAR(32) NOT NULL DEFAULT 'validator',
    commercial_use_allowed         BOOLEAN NOT NULL DEFAULT FALSE,
    redistribution_allowed         VARCHAR(16) NOT NULL DEFAULT 'unknown',
    production_use_allowed         BOOLEAN NOT NULL DEFAULT FALSE,
    delivery_mode                  VARCHAR(32) NOT NULL DEFAULT 'api',
    frequency                      VARCHAR(32),
    latency_level                  VARCHAR(16),
    endpoint_path                  VARCHAR(256),
    schema_status                  VARCHAR(32) NOT NULL DEFAULT 'pending',
    field_mapping_status           VARCHAR(32) NOT NULL DEFAULT 'pending',
    rate_limit_per_min             INTEGER,
    daily_quota                    BIGINT,
    max_delay_minutes              INTEGER,
    sla_uptime_pct                 NUMERIC(6, 3),
    effective_from                 DATE,
    effective_to                   DATE,
    blocking_issues                TEXT[] NOT NULL DEFAULT '{}',
    required_actions               TEXT[] NOT NULL DEFAULT '{}',
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                         VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contract_id, dataset_id),
    CHECK (entitlement_status IN ('active', 'review_required', 'blocked', 'expired', 'suspended')),
    CHECK (allowed_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (delivery_mode IN ('api', 'file', 'sftp', 'websocket', 'manual', 'unknown')),
    CHECK (latency_level IS NULL OR latency_level IN ('L0', 'L1', 'L2', 'L3', 'L4')),
    CHECK (schema_status IN ('missing', 'pending', 'mapped', 'validated', 'rejected')),
    CHECK (field_mapping_status IN ('missing', 'pending', 'mapped', 'validated', 'rejected')),
    CHECK (status IN ('active', 'inactive', 'expired', 'blocked')),
    CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0),
    CHECK (max_delay_minutes IS NULL OR max_delay_minutes >= 0),
    CHECK (sla_uptime_pct IS NULL OR (sla_uptime_pct >= 0 AND sla_uptime_pct <= 100))
);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_entitlement_dataset
    ON qmeta.vendor_contract_dataset_entitlement(source_id, dataset_id, entitlement_status, allowed_role);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_entitlement_rights
    ON qmeta.vendor_contract_dataset_entitlement(commercial_use_allowed, redistribution_allowed, production_use_allowed, schema_status);

CREATE TABLE IF NOT EXISTS qmeta.vendor_procurement_readiness_snapshot (
    snapshot_id                    BIGSERIAL PRIMARY KEY,
    snapshot_code                  VARCHAR(180) NOT NULL UNIQUE,
    source_id                      BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                     BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    contract_id                    BIGINT REFERENCES qmeta.vendor_contract_profile(contract_id) ON DELETE SET NULL,
    entitlement_id                 BIGINT REFERENCES qmeta.vendor_contract_dataset_entitlement(entitlement_id) ON DELETE SET NULL,
    profile_id                     BIGINT REFERENCES qmeta.vendor_integration_profile(profile_id) ON DELETE SET NULL,
    as_of_date                     DATE NOT NULL,
    requested_by                   VARCHAR(128) NOT NULL DEFAULT 'omicron5',
    trigger_mode                   VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                    VARCHAR(32) NOT NULL DEFAULT 'local',
    status                         VARCHAR(32) NOT NULL DEFAULT 'no_contract',
    procurement_role               VARCHAR(32) NOT NULL DEFAULT 'blocked',
    readiness_score                NUMERIC(8, 4) NOT NULL DEFAULT 0,
    procurement_status             VARCHAR(32) NOT NULL DEFAULT 'review_required',
    contract_status                VARCHAR(32) NOT NULL DEFAULT 'none',
    commercial_clearance           VARCHAR(32) NOT NULL DEFAULT 'review_required',
    redistribution_allowed         VARCHAR(16) NOT NULL DEFAULT 'unknown',
    contract_production_use_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    entitlement_status             VARCHAR(32) NOT NULL DEFAULT 'review_required',
    entitlement_allowed_role       VARCHAR(32) NOT NULL DEFAULT 'validator',
    entitlement_commercial_use_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    entitlement_redistribution_allowed VARCHAR(16) NOT NULL DEFAULT 'unknown',
    entitlement_production_use_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    contract_ref                   VARCHAR(180),
    contract_end_date              DATE,
    next_review_at                 TIMESTAMPTZ,
    rate_limit_per_min             INTEGER,
    daily_quota                    BIGINT,
    monthly_quota                  BIGINT,
    sla_uptime_pct                 NUMERIC(6, 3),
    max_delay_minutes              INTEGER,
    vendor_profile_status          VARCHAR(32),
    pi_readiness_status            VARCHAR(32),
    pi_recommendation              VARCHAR(32),
    live_gate_status               VARCHAR(32),
    onboarding_status              VARCHAR(32),
    live_closure_status            VARCHAR(32),
    live_pilot_status              VARCHAR(32),
    latest_review_code             VARCHAR(180),
    latest_gate_code               VARCHAR(180),
    latest_onboarding_code         VARCHAR(180),
    latest_closure_code            VARCHAR(180),
    latest_pilot_code              VARCHAR(180),
    blocking_issues                TEXT[] NOT NULL DEFAULT '{}',
    required_actions               TEXT[] NOT NULL DEFAULT '{}',
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                  TEXT,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('ready', 'conditional', 'review_required', 'blocked', 'no_contract')),
    CHECK (procurement_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (readiness_score >= 0 AND readiness_score <= 100),
    CHECK (procurement_status IN ('draft', 'review_required', 'active', 'suspended', 'expired', 'terminated', 'blocked')),
    CHECK (contract_status IN ('none', 'draft', 'active', 'expired', 'terminated')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (entitlement_status IN ('active', 'review_required', 'blocked', 'expired', 'suspended')),
    CHECK (entitlement_allowed_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (entitlement_redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0),
    CHECK (monthly_quota IS NULL OR monthly_quota > 0),
    CHECK (sla_uptime_pct IS NULL OR (sla_uptime_pct >= 0 AND sla_uptime_pct <= 100)),
    CHECK (max_delay_minutes IS NULL OR max_delay_minutes >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_procurement_readiness_lookup
    ON qmeta.vendor_procurement_readiness_snapshot(as_of_date DESC, status, procurement_role);

CREATE INDEX IF NOT EXISTS idx_vendor_procurement_readiness_source_dataset
    ON qmeta.vendor_procurement_readiness_snapshot(source_id, dataset_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_procurement_readiness_contract
    ON qmeta.vendor_procurement_readiness_snapshot(contract_status, commercial_clearance, redistribution_allowed, entitlement_status, as_of_date DESC);

INSERT INTO qmeta.vendor_contract_profile (
    contract_code, source_id, profile_id, provider_name, procurement_status,
    contract_status, commercial_clearance, redistribution_allowed,
    production_use_allowed, contract_owner, legal_owner, business_owner,
    sla_tier, rate_limit_per_min, data_scope, evidence, updated_at
)
SELECT
    'omicron5-contract-vendor_http-draft',
    ss.source_id,
    vip.profile_id,
    'Commercial HTTP Vendor',
    'review_required',
    'draft',
    'review_required',
    'unknown',
    FALSE,
    'platform-data',
    'legal',
    'quant-business',
    'unknown',
    COALESCE(vip.rate_limit_per_min, 120),
    ARRAY['daily_bar', 'security_master', 'trading_calendar', 'adjustment_factor', 'limit_price_daily', 'financial_metric_pit', 'financial_statement_pit']::text[],
    '{"seeded_by":"0039","policy_note":"template only; cannot become primary until active contract, redistribution rights, production use, SLA, quota and dataset entitlement are recorded"}'::jsonb,
    now()
FROM qmeta.source_system ss
LEFT JOIN qmeta.vendor_integration_profile vip ON vip.source_id = ss.source_id AND vip.provider_name = 'vendor_http'
WHERE ss.source_code = 'vendor_http'
ON CONFLICT (contract_code) DO UPDATE SET
    profile_id = COALESCE(qmeta.vendor_contract_profile.profile_id, EXCLUDED.profile_id),
    provider_name = COALESCE(qmeta.vendor_contract_profile.provider_name, EXCLUDED.provider_name),
    rate_limit_per_min = COALESCE(qmeta.vendor_contract_profile.rate_limit_per_min, EXCLUDED.rate_limit_per_min),
    data_scope = CASE
        WHEN qmeta.vendor_contract_profile.data_scope = '{}'::text[] THEN EXCLUDED.data_scope
        ELSE qmeta.vendor_contract_profile.data_scope
    END,
    evidence = qmeta.vendor_contract_profile.evidence || EXCLUDED.evidence,
    updated_at = now();

INSERT INTO qmeta.vendor_contract_dataset_entitlement (
    entitlement_code, contract_id, source_id, dataset_id, entitlement_status,
    allowed_role, commercial_use_allowed, redistribution_allowed,
    production_use_allowed, delivery_mode, frequency, latency_level,
    endpoint_path, schema_status, field_mapping_status, rate_limit_per_min,
    max_delay_minutes, blocking_issues, required_actions, evidence, updated_at
)
SELECT
    'omicron5-entitlement-vendor_http-' || dc.dataset_code,
    vcp.contract_id,
    vcp.source_id,
    dc.dataset_id,
    'review_required',
    'primary_candidate',
    FALSE,
    'unknown',
    FALSE,
    seed.delivery_mode,
    dc.frequency,
    'L3',
    seed.endpoint_path,
    'pending',
    'pending',
    COALESCE(vcp.rate_limit_per_min, 120),
    seed.max_delay_minutes,
    ARRAY[
        'contract_not_active',
        'commercial_use_not_cleared',
        'redistribution_unknown',
        'production_use_not_allowed',
        'dataset_schema_not_validated'
    ]::text[],
    ARRAY[
        'Attach signed master data contract and mark contract_status=active.',
        'Record commercial use, redistribution/cache and production-use rights for this dataset.',
        'Record production quota, rate limit and SLA before any primary routing.',
        'Validate endpoint schema and field mapping with Eta-3/Theta-3 evidence.'
    ]::text[],
    jsonb_build_object('seeded_by', '0039', 'dataset_code', dc.dataset_code, 'policy_note', 'desired primary scope template; blocked until rights are active'),
    now()
FROM (
    VALUES
        ('daily_bar', 'api', '/daily', 1440),
        ('security_master', 'api', '/securities', 1440),
        ('trading_calendar', 'api', '/trading-calendar', 1440),
        ('adjustment_factor', 'api', '/adjustment-factor', 1440),
        ('limit_price_daily', 'api', '/limit-price', 1440),
        ('financial_metric_pit', 'api', '/financial-metrics', 10080),
        ('financial_statement_pit', 'api', '/financial-statements', 10080)
) AS seed(dataset_code, delivery_mode, endpoint_path, max_delay_minutes)
JOIN qmeta.dataset_catalog dc ON dc.dataset_code = seed.dataset_code
JOIN qmeta.vendor_contract_profile vcp ON vcp.contract_code = 'omicron5-contract-vendor_http-draft'
ON CONFLICT (entitlement_code) DO UPDATE SET
    frequency = COALESCE(qmeta.vendor_contract_dataset_entitlement.frequency, EXCLUDED.frequency),
    endpoint_path = COALESCE(qmeta.vendor_contract_dataset_entitlement.endpoint_path, EXCLUDED.endpoint_path),
    max_delay_minutes = COALESCE(qmeta.vendor_contract_dataset_entitlement.max_delay_minutes, EXCLUDED.max_delay_minutes),
    evidence = qmeta.vendor_contract_dataset_entitlement.evidence || EXCLUDED.evidence,
    updated_at = now();

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'omicron5_vendor_contract_readiness_6h', 'vendor_contract_readiness_review', 21600, 600, 600, 300,
    '{"omicron5_min_sla_uptime_pct":99.5,"omicron5_min_rate_limit_per_min":60,"omicron5_require_live_evidence":false}'::jsonb,
    '{"owner":"omicron5","purpose":"review authorized vendor contract, dataset entitlements, SLA, quota and live evidence before primary-source procurement"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
