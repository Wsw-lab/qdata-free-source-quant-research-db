-- Pi-5: authorized primary vendor production promotion guardrail.

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
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review'
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
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review'
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
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_primary_promotion_run (
    promotion_id                    BIGSERIAL PRIMARY KEY,
    promotion_code                  VARCHAR(180) NOT NULL UNIQUE,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    as_of_date                      DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                    VARCHAR(128) NOT NULL DEFAULT 'pi5',
    trigger_mode                    VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                     VARCHAR(32) NOT NULL DEFAULT 'local',
    promotion_scope                 VARCHAR(32) NOT NULL DEFAULT 'full_market',
    status                          VARCHAR(32) NOT NULL DEFAULT 'blocked',
    apply_mode                      VARCHAR(32) NOT NULL DEFAULT 'review_only',
    routing_change_allowed          BOOLEAN NOT NULL DEFAULT FALSE,
    routing_change_applied          BOOLEAN NOT NULL DEFAULT FALSE,
    dataset_count                   INTEGER NOT NULL DEFAULT 0,
    approved_dataset_count          INTEGER NOT NULL DEFAULT 0,
    pending_dataset_count           INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count           INTEGER NOT NULL DEFAULT 0,
    applied_dataset_count           INTEGER NOT NULL DEFAULT 0,
    canary_ready_count              INTEGER NOT NULL DEFAULT 0,
    full_market_ready_count         INTEGER NOT NULL DEFAULT 0,
    signoff_ready_count             INTEGER NOT NULL DEFAULT 0,
    required_windows                INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    require_full_market             BOOLEAN NOT NULL DEFAULT TRUE,
    require_signoff                 BOOLEAN NOT NULL DEFAULT TRUE,
    target_priority                 INTEGER NOT NULL DEFAULT 0,
    current_primary_source_codes    TEXT[] NOT NULL DEFAULT '{}',
    promotion_score                 NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    required_actions                TEXT[] NOT NULL DEFAULT '{}',
    request_payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    started_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                     TIMESTAMPTZ,
    duration_ms                     INTEGER,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (promotion_scope IN ('canary', 'full_market')),
    CHECK (status IN ('blocked', 'canary_required', 'full_market_required', 'pending_signoff', 'approved_for_primary', 'applied')),
    CHECK (apply_mode IN ('review_only', 'dry_run', 'apply')),
    CHECK (dataset_count >= 0),
    CHECK (approved_dataset_count >= 0),
    CHECK (pending_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (applied_dataset_count >= 0),
    CHECK (canary_ready_count >= 0),
    CHECK (full_market_ready_count >= 0),
    CHECK (signoff_ready_count >= 0),
    CHECK (array_length(required_windows, 1) IS NOT NULL),
    CHECK (target_priority >= 0),
    CHECK (promotion_score >= 0 AND promotion_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_promotion_run_lookup
    ON qmeta.vendor_primary_promotion_run(source_id, as_of_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_promotion_run_status
    ON qmeta.vendor_primary_promotion_run(status, promotion_scope, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_primary_promotion_dataset_result (
    result_id                       BIGSERIAL PRIMARY KEY,
    result_code                     VARCHAR(180) NOT NULL UNIQUE,
    promotion_id                    BIGINT NOT NULL REFERENCES qmeta.vendor_primary_promotion_run(promotion_id) ON DELETE CASCADE,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                      BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    procurement_snapshot_id         BIGINT REFERENCES qmeta.vendor_procurement_readiness_snapshot(snapshot_id) ON DELETE SET NULL,
    procurement_snapshot_code       VARCHAR(180),
    readiness_review_id             BIGINT REFERENCES qmeta.vendor_readiness_review(review_id) ON DELETE SET NULL,
    readiness_review_code           VARCHAR(180),
    canary_pilot_id                 BIGINT REFERENCES qmeta.vendor_live_pilot_run(pilot_id) ON DELETE SET NULL,
    canary_pilot_code               VARCHAR(180),
    full_market_pilot_id            BIGINT REFERENCES qmeta.vendor_live_pilot_run(pilot_id) ON DELETE SET NULL,
    full_market_pilot_code          VARCHAR(180),
    current_priority_id             BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    current_primary_source_code     VARCHAR(64),
    current_priority                INTEGER,
    target_priority                 INTEGER NOT NULL DEFAULT 0,
    status                          VARCHAR(32) NOT NULL DEFAULT 'blocked',
    promotion_role                  VARCHAR(32) NOT NULL DEFAULT 'blocked',
    routing_change_allowed          BOOLEAN NOT NULL DEFAULT FALSE,
    routing_change_applied          BOOLEAN NOT NULL DEFAULT FALSE,
    procurement_status              VARCHAR(32),
    procurement_role                VARCHAR(32),
    readiness_status                VARCHAR(32),
    readiness_recommendation        VARCHAR(32),
    readiness_recommended_role      VARCHAR(32),
    canary_status                   VARCHAR(32),
    canary_signoff_status           VARCHAR(32),
    canary_recommendation           VARCHAR(32),
    canary_risk_level               VARCHAR(16),
    full_market_status              VARCHAR(32),
    full_market_signoff_status      VARCHAR(32),
    full_market_recommendation      VARCHAR(32),
    full_market_risk_level          VARCHAR(16),
    promotion_score                 NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    required_actions                TEXT[] NOT NULL DEFAULT '{}',
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('blocked', 'canary_required', 'full_market_required', 'pending_signoff', 'approved_for_primary', 'applied')),
    CHECK (promotion_role IN ('blocked', 'validator', 'backup', 'primary')),
    CHECK (target_priority >= 0),
    CHECK (current_priority IS NULL OR current_priority >= 0),
    CHECK (promotion_score >= 0 AND promotion_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_promotion_result_lookup
    ON qmeta.vendor_primary_promotion_dataset_result(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_promotion_result_evidence
    ON qmeta.vendor_primary_promotion_dataset_result(procurement_snapshot_id, readiness_review_id, canary_pilot_id, full_market_pilot_id);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'pi5_vendor_primary_promotion_6h', 'vendor_primary_promotion_review', 21600, 600, 600, 300,
    '{"pi5_promotion_scope":"full_market","pi5_require_full_market":true,"pi5_require_signoff":true,"pi5_apply_routing":false,"pi5_target_priority":0}'::jsonb,
    '{"owner":"pi5","purpose":"review authorized vendor evidence before primary-source routing promotion; default is review-only"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
