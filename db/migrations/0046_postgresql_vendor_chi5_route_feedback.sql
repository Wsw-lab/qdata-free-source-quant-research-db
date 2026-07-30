-- Chi-5: source-route feedback health, circuit breakers and recovery probes.

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
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer',
        'vendor_route_weight_executor',
        'source_route_feedback_monitor'
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
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer',
        'vendor_route_weight_executor',
        'source_route_feedback_monitor'
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
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer',
        'vendor_route_weight_executor',
        'source_route_feedback_monitor'
    ));

CREATE TABLE IF NOT EXISTS qmeta.source_route_health_snapshot (
    snapshot_id                     BIGSERIAL PRIMARY KEY,
    snapshot_code                   VARCHAR(180) NOT NULL UNIQUE,
    dataset_id                      BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE CASCADE,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id) ON DELETE CASCADE,
    requested_by                    VARCHAR(128) NOT NULL DEFAULT 'chi5',
    trigger_mode                    VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                     VARCHAR(32) NOT NULL DEFAULT 'local',
    as_of_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    lookback_hours                  INTEGER NOT NULL DEFAULT 24,
    status                          VARCHAR(32) NOT NULL DEFAULT 'healthy',
    previous_circuit_status         VARCHAR(32),
    circuit_status                  VARCHAR(32) NOT NULL DEFAULT 'closed',
    circuit_action                  VARCHAR(64) NOT NULL DEFAULT 'none',
    request_count                   INTEGER NOT NULL DEFAULT 0,
    selected_count                  INTEGER NOT NULL DEFAULT 0,
    final_count                     INTEGER NOT NULL DEFAULT 0,
    success_count                   INTEGER NOT NULL DEFAULT 0,
    failed_count                    INTEGER NOT NULL DEFAULT 0,
    fallback_count                  INTEGER NOT NULL DEFAULT 0,
    empty_count                     INTEGER NOT NULL DEFAULT 0,
    success_rate                    NUMERIC(8, 4) NOT NULL DEFAULT 0,
    failure_rate                    NUMERIC(8, 4) NOT NULL DEFAULT 0,
    fallback_rate                   NUMERIC(8, 4) NOT NULL DEFAULT 0,
    empty_rate                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    latency_p95_ms                  NUMERIC(14, 4) NOT NULL DEFAULT 0,
    min_request_count               INTEGER NOT NULL DEFAULT 1,
    min_success_rate                NUMERIC(8, 4) NOT NULL DEFAULT 0.9500,
    max_failure_rate                NUMERIC(8, 4) NOT NULL DEFAULT 0.1000,
    max_fallback_rate               NUMERIC(8, 4) NOT NULL DEFAULT 0.2000,
    max_empty_rate                  NUMERIC(8, 4) NOT NULL DEFAULT 0.2000,
    max_latency_p95_ms              NUMERIC(14, 4) NOT NULL DEFAULT 2000,
    open_until                      TIMESTAMPTZ,
    health_issues                   TEXT[] NOT NULL DEFAULT '{}',
    runbook_actions                 TEXT[] NOT NULL DEFAULT '{}',
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('healthy', 'warning', 'degraded', 'circuit_open', 'no_data', 'failed', 'skipped')),
    CHECK (previous_circuit_status IS NULL OR previous_circuit_status IN ('closed', 'open', 'half_open', 'disabled')),
    CHECK (circuit_status IN ('closed', 'open', 'half_open', 'disabled')),
    CHECK (circuit_action IN ('none', 'open_circuit', 'keep_open', 'half_open_probe', 'close_circuit', 'skip_disabled')),
    CHECK (lookback_hours > 0),
    CHECK (request_count >= 0),
    CHECK (selected_count >= 0),
    CHECK (final_count >= 0),
    CHECK (success_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (fallback_count >= 0),
    CHECK (empty_count >= 0),
    CHECK (success_rate >= 0 AND success_rate <= 1),
    CHECK (failure_rate >= 0 AND failure_rate <= 1),
    CHECK (fallback_rate >= 0 AND fallback_rate <= 1),
    CHECK (empty_rate >= 0 AND empty_rate <= 1),
    CHECK (latency_p95_ms >= 0),
    CHECK (min_request_count >= 0),
    CHECK (min_success_rate >= 0 AND min_success_rate <= 1),
    CHECK (max_failure_rate >= 0 AND max_failure_rate <= 1),
    CHECK (max_fallback_rate >= 0 AND max_fallback_rate <= 1),
    CHECK (max_empty_rate >= 0 AND max_empty_rate <= 1),
    CHECK (max_latency_p95_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_source_route_health_lookup
    ON qmeta.source_route_health_snapshot(dataset_id, source_id, as_of_at DESC, status);

CREATE INDEX IF NOT EXISTS idx_source_route_health_status
    ON qmeta.source_route_health_snapshot(status, circuit_status, as_of_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.source_route_circuit_breaker (
    breaker_id                      BIGSERIAL PRIMARY KEY,
    breaker_code                    VARCHAR(180) NOT NULL UNIQUE,
    dataset_id                      BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE CASCADE,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id) ON DELETE CASCADE,
    status                          VARCHAR(32) NOT NULL DEFAULT 'closed',
    opened_at                       TIMESTAMPTZ,
    half_open_at                    TIMESTAMPTZ,
    closed_at                       TIMESTAMPTZ,
    open_until                      TIMESTAMPTZ,
    last_snapshot_id                BIGINT REFERENCES qmeta.source_route_health_snapshot(snapshot_id) ON DELETE SET NULL,
    last_probe_id                   BIGINT,
    open_reason                     TEXT,
    failure_rate                    NUMERIC(8, 4) NOT NULL DEFAULT 0,
    fallback_rate                   NUMERIC(8, 4) NOT NULL DEFAULT 0,
    empty_rate                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    latency_p95_ms                  NUMERIC(14, 4) NOT NULL DEFAULT 0,
    health_issues                   TEXT[] NOT NULL DEFAULT '{}',
    details                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, source_id),
    CHECK (status IN ('closed', 'open', 'half_open', 'disabled')),
    CHECK (failure_rate >= 0 AND failure_rate <= 1),
    CHECK (fallback_rate >= 0 AND fallback_rate <= 1),
    CHECK (empty_rate >= 0 AND empty_rate <= 1),
    CHECK (latency_p95_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_source_route_circuit_breaker_lookup
    ON qmeta.source_route_circuit_breaker(dataset_id, source_id, status, open_until);

CREATE TABLE IF NOT EXISTS qmeta.source_route_recovery_probe (
    probe_id                        BIGSERIAL PRIMARY KEY,
    probe_code                      VARCHAR(180) NOT NULL UNIQUE,
    breaker_id                      BIGINT REFERENCES qmeta.source_route_circuit_breaker(breaker_id) ON DELETE SET NULL,
    snapshot_id                     BIGINT REFERENCES qmeta.source_route_health_snapshot(snapshot_id) ON DELETE SET NULL,
    dataset_id                      BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE CASCADE,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id) ON DELETE CASCADE,
    requested_by                    VARCHAR(128) NOT NULL DEFAULT 'chi5',
    trigger_mode                    VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                     VARCHAR(32) NOT NULL DEFAULT 'local',
    status                          VARCHAR(32) NOT NULL DEFAULT 'planned',
    probe_started_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    probe_finished_at               TIMESTAMPTZ,
    observed_request_count          INTEGER NOT NULL DEFAULT 0,
    observed_success_count          INTEGER NOT NULL DEFAULT 0,
    observed_failed_count           INTEGER NOT NULL DEFAULT 0,
    observed_success_rate           NUMERIC(8, 4) NOT NULL DEFAULT 0,
    required_success_rate           NUMERIC(8, 4) NOT NULL DEFAULT 1,
    decision_summary                VARCHAR(128) NOT NULL DEFAULT 'pending',
    details                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('planned', 'probed', 'recovered', 'failed', 'skipped')),
    CHECK (observed_request_count >= 0),
    CHECK (observed_success_count >= 0),
    CHECK (observed_failed_count >= 0),
    CHECK (observed_success_rate >= 0 AND observed_success_rate <= 1),
    CHECK (required_success_rate >= 0 AND required_success_rate <= 1)
);

CREATE INDEX IF NOT EXISTS idx_source_route_recovery_probe_lookup
    ON qmeta.source_route_recovery_probe(dataset_id, source_id, probe_started_at DESC, status);

ALTER TABLE qmeta.source_route_circuit_breaker
    DROP CONSTRAINT IF EXISTS source_route_circuit_breaker_last_probe_fk;

ALTER TABLE qmeta.source_route_circuit_breaker
    ADD CONSTRAINT source_route_circuit_breaker_last_probe_fk
    FOREIGN KEY (last_probe_id) REFERENCES qmeta.source_route_recovery_probe(probe_id) ON DELETE SET NULL;

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'chi5_source_route_feedback_15m', 'source_route_feedback_monitor', 900, 300, 300, 120,
    '{"chi5_lookback_hours":24,"chi5_min_request_count":1,"chi5_min_success_rate":0.95,"chi5_max_failure_rate":0.1,"chi5_max_fallback_rate":0.2,"chi5_max_empty_rate":0.2,"chi5_max_latency_p95_ms":2000,"chi5_circuit_open_minutes":30,"chi5_recovery_probe_min_success_rate":1.0}'::jsonb,
    '{"owner":"chi5","purpose":"aggregate Phi-5 route decisions into route health, circuit-breaker and recovery-probe state"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
