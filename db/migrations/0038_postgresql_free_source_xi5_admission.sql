-- Xi-5: free source admission matrix for licensing, redistribution and production-role control.

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
        'free_source_admission_review'
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
        'free_source_admission_review'
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
        'free_source_admission_review'
    ));

CREATE TABLE IF NOT EXISTS qmeta.free_source_admission_profile (
    profile_id                    BIGSERIAL PRIMARY KEY,
    source_id                     BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    profile_code                  VARCHAR(180) NOT NULL UNIQUE,
    provider_name                 VARCHAR(128) NOT NULL,
    license_type                  VARCHAR(32) NOT NULL DEFAULT 'unknown',
    license_status                VARCHAR(32) NOT NULL DEFAULT 'unknown',
    commercial_clearance          VARCHAR(32) NOT NULL DEFAULT 'blocked',
    redistribution_allowed        VARCHAR(16) NOT NULL DEFAULT 'unknown',
    contract_status               VARCHAR(32) NOT NULL DEFAULT 'none',
    contract_ref                  VARCHAR(180),
    terms_review_status           VARCHAR(32) NOT NULL DEFAULT 'missing',
    api_terms_url                 TEXT,
    rate_limit_per_min            INTEGER,
    daily_quota                   INTEGER,
    max_allowed_role              VARCHAR(32) NOT NULL DEFAULT 'research_only',
    status                        VARCHAR(32) NOT NULL DEFAULT 'active',
    reviewed_by                   VARCHAR(128),
    reviewed_at                   TIMESTAMPTZ,
    expires_at                    TIMESTAMPTZ,
    evidence                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id),
    CHECK (license_type IN ('unknown', 'local_fixture', 'open_source', 'official_public', 'exchange_public', 'announcement_public', 'free_tier', 'paid_contract')),
    CHECK (license_status IN ('unknown', 'local_smoke', 'official_public', 'research_only', 'review_required', 'blocked', 'contracted', 'approved')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (contract_status IN ('none', 'draft', 'active', 'expired', 'terminated')),
    CHECK (terms_review_status IN ('missing', 'pending', 'approved', 'rejected', 'expired')),
    CHECK (max_allowed_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (status IN ('active', 'inactive', 'expired', 'blocked')),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_profile_source
    ON qmeta.free_source_admission_profile(source_id, status);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_profile_clearance
    ON qmeta.free_source_admission_profile(commercial_clearance, redistribution_allowed, contract_status, terms_review_status);

CREATE TABLE IF NOT EXISTS qmeta.free_source_admission_snapshot (
    admission_id                  BIGSERIAL PRIMARY KEY,
    snapshot_code                 VARCHAR(180) NOT NULL UNIQUE,
    source_id                     BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                    BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    profile_id                    BIGINT REFERENCES qmeta.free_source_admission_profile(profile_id) ON DELETE SET NULL,
    reliability_snapshot_id       BIGINT REFERENCES qmeta.free_source_reliability_snapshot(snapshot_id) ON DELETE SET NULL,
    as_of_date                    DATE NOT NULL,
    requested_by                  VARCHAR(128) NOT NULL DEFAULT 'xi5',
    trigger_mode                  VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                   VARCHAR(32) NOT NULL DEFAULT 'local',
    status                        VARCHAR(32) NOT NULL DEFAULT 'no_data',
    admission_role                VARCHAR(32) NOT NULL DEFAULT 'blocked',
    max_allowed_role              VARCHAR(32) NOT NULL DEFAULT 'research_only',
    license_type                  VARCHAR(32) NOT NULL DEFAULT 'unknown',
    license_status                VARCHAR(32) NOT NULL DEFAULT 'unknown',
    commercial_clearance          VARCHAR(32) NOT NULL DEFAULT 'blocked',
    redistribution_allowed        VARCHAR(16) NOT NULL DEFAULT 'unknown',
    contract_status               VARCHAR(32) NOT NULL DEFAULT 'none',
    contract_ref                  VARCHAR(180),
    terms_review_status           VARCHAR(32) NOT NULL DEFAULT 'missing',
    api_terms_url                 TEXT,
    rate_limit_per_min            INTEGER,
    daily_quota                   INTEGER,
    reliability_status            VARCHAR(32) NOT NULL DEFAULT 'no_data',
    reliability_score             NUMERIC(8, 4) NOT NULL DEFAULT 0,
    success_rate                  NUMERIC(10, 6),
    coverage_rate                 NUMERIC(10, 6),
    conflict_rate_bps             NUMERIC(18, 6),
    observation_count             INTEGER NOT NULL DEFAULT 0,
    reliability_snapshot_code     VARCHAR(180),
    latest_fabric_code            VARCHAR(180),
    latest_fabric_status          VARCHAR(32),
    blocking_issues               TEXT[] NOT NULL DEFAULT '{}',
    required_actions              TEXT[] NOT NULL DEFAULT '{}',
    evidence                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                 TEXT,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('approved', 'conditional', 'review_required', 'blocked', 'no_data')),
    CHECK (admission_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (max_allowed_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (license_type IN ('unknown', 'local_fixture', 'open_source', 'official_public', 'exchange_public', 'announcement_public', 'free_tier', 'paid_contract')),
    CHECK (license_status IN ('unknown', 'local_smoke', 'official_public', 'research_only', 'review_required', 'blocked', 'contracted', 'approved')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (contract_status IN ('none', 'draft', 'active', 'expired', 'terminated')),
    CHECK (terms_review_status IN ('missing', 'pending', 'approved', 'rejected', 'expired')),
    CHECK (reliability_status IN ('no_data', 'ready', 'watch', 'degraded', 'rejected')),
    CHECK (reliability_score >= 0 AND reliability_score <= 100),
    CHECK (success_rate IS NULL OR (success_rate >= 0 AND success_rate <= 1)),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate_bps IS NULL OR conflict_rate_bps >= 0),
    CHECK (observation_count >= 0),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_snapshot_lookup
    ON qmeta.free_source_admission_snapshot(as_of_date DESC, status, admission_role);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_snapshot_source_dataset
    ON qmeta.free_source_admission_snapshot(source_id, dataset_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_snapshot_license
    ON qmeta.free_source_admission_snapshot(commercial_clearance, redistribution_allowed, contract_status, terms_review_status, as_of_date DESC);

INSERT INTO qmeta.free_source_admission_profile (
    source_id, profile_code, provider_name, license_type, license_status,
    commercial_clearance, redistribution_allowed, contract_status, terms_review_status,
    max_allowed_role, evidence, updated_at
)
SELECT
    ss.source_id,
    'xi5-profile-' || ss.source_code,
    seed.provider_name,
    seed.license_type,
    seed.license_status,
    seed.commercial_clearance,
    seed.redistribution_allowed,
    seed.contract_status,
    seed.terms_review_status,
    seed.max_allowed_role,
    jsonb_build_object('seeded_by', '0038', 'policy_note', seed.policy_note),
    now()
FROM (
    VALUES
        ('csv', 'csv', 'local_fixture', 'local_smoke', 'blocked', 'no', 'none', 'missing', 'validator', 'local fixture can validate pipelines but cannot serve production clients'),
        ('csv_mirror', 'csv_mirror', 'local_fixture', 'local_smoke', 'blocked', 'no', 'none', 'missing', 'validator', 'local mirror fixture can validate deterministic comparisons only'),
        ('akshare', 'akshare', 'open_source', 'research_only', 'blocked', 'no', 'none', 'pending', 'validator', 'public web aggregation requires upstream commercial-use review'),
        ('baostock', 'baostock', 'open_source', 'research_only', 'blocked', 'no', 'none', 'pending', 'validator', 'free research source requires redistribution and commercial-use review'),
        ('tushare_free', 'tushare_free', 'free_tier', 'review_required', 'blocked', 'unknown', 'none', 'pending', 'validator', 'free quota tier requires points, frequency and commercial terms review'),
        ('cninfo_public', 'cninfo_public', 'announcement_public', 'review_required', 'review_required', 'unknown', 'none', 'pending', 'backup', 'public announcement source requires cache and redistribution review'),
        ('sse_public', 'sse_public', 'exchange_public', 'official_public', 'review_required', 'unknown', 'none', 'pending', 'backup', 'official exchange public pages require reuse and caching terms review'),
        ('szse_public', 'szse_public', 'exchange_public', 'official_public', 'review_required', 'unknown', 'none', 'pending', 'backup', 'official exchange public pages require reuse and caching terms review'),
        ('nbs_public', 'nbs_public', 'official_public', 'official_public', 'review_required', 'unknown', 'none', 'pending', 'backup', 'official public macro source requires terms and attribution review')
) AS seed(source_code, provider_name, license_type, license_status, commercial_clearance, redistribution_allowed, contract_status, terms_review_status, max_allowed_role, policy_note)
JOIN qmeta.source_system ss ON ss.source_code = seed.source_code
ON CONFLICT (source_id) DO UPDATE SET
    provider_name = EXCLUDED.provider_name,
    license_type = EXCLUDED.license_type,
    license_status = EXCLUDED.license_status,
    commercial_clearance = EXCLUDED.commercial_clearance,
    redistribution_allowed = EXCLUDED.redistribution_allowed,
    contract_status = EXCLUDED.contract_status,
    terms_review_status = EXCLUDED.terms_review_status,
    max_allowed_role = EXCLUDED.max_allowed_role,
    evidence = qmeta.free_source_admission_profile.evidence || EXCLUDED.evidence,
    updated_at = now();

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'xi_free_source_admission_review_6h', 'free_source_admission_review', 21600, 600, 600, 300,
    '{"xi5_lookback_days":30,"xi5_min_validator_score":55,"xi5_min_backup_score":75,"xi5_min_primary_score":90,"xi5_min_coverage_rate":0.95,"xi5_max_conflict_rate_bps":5}'::jsonb,
    '{"owner":"xi5","purpose":"review free-source licensing, redistribution, contract, quota and reliability evidence before any production role"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
