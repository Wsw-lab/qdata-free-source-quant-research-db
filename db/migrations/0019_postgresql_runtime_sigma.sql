-- A 股量化数据平台 Sigma：系统运行可观测与容量预警

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

CREATE TABLE IF NOT EXISTS qmeta.runtime_log (
    log_id                  BIGSERIAL PRIMARY KEY,
    log_code                VARCHAR(220) NOT NULL UNIQUE,
    environment             VARCHAR(64) NOT NULL DEFAULT 'local',
    component               VARCHAR(64) NOT NULL,
    service_name            VARCHAR(128),
    release_id              BIGINT REFERENCES qmeta.deployment_release(release_id) ON DELETE SET NULL,
    worker_run_id           BIGINT REFERENCES qmeta.worker_run(worker_run_id) ON DELETE SET NULL,
    log_time                TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity                VARCHAR(24) NOT NULL DEFAULT 'info',
    event_type              VARCHAR(64) NOT NULL DEFAULT 'runtime_event',
    message                 TEXT NOT NULL,
    trace_id                VARCHAR(128),
    request_id              VARCHAR(128),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_runtime_log_component_time
    ON qmeta.runtime_log(environment, component, log_time DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_log_severity_time
    ON qmeta.runtime_log(severity, log_time DESC);

CREATE TABLE IF NOT EXISTS qmeta.runtime_metric_snapshot (
    metric_id               BIGSERIAL PRIMARY KEY,
    metric_code             VARCHAR(220) NOT NULL UNIQUE,
    environment             VARCHAR(64) NOT NULL DEFAULT 'local',
    component               VARCHAR(64) NOT NULL,
    service_name            VARCHAR(128),
    metric_name             VARCHAR(96) NOT NULL,
    metric_time             TIMESTAMPTZ NOT NULL DEFAULT now(),
    metric_value            NUMERIC(28, 12) NOT NULL,
    unit                    VARCHAR(32) NOT NULL DEFAULT 'count',
    status                  VARCHAR(24) NOT NULL DEFAULT 'normal',
    warning_threshold       NUMERIC(28, 12),
    critical_threshold      NUMERIC(28, 12),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('normal', 'warning', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_runtime_metric_lookup
    ON qmeta.runtime_metric_snapshot(environment, component, metric_name, metric_time DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_metric_status_time
    ON qmeta.runtime_metric_snapshot(status, metric_time DESC);

CREATE TABLE IF NOT EXISTS qmeta.runtime_daily_report (
    report_id                       BIGSERIAL PRIMARY KEY,
    report_code                     VARCHAR(180) NOT NULL UNIQUE,
    environment                     VARCHAR(64) NOT NULL DEFAULT 'local',
    report_date                     DATE NOT NULL,
    status                          VARCHAR(24) NOT NULL DEFAULT 'success',
    api_request_count               BIGINT NOT NULL DEFAULT 0,
    api_failed_count                BIGINT NOT NULL DEFAULT 0,
    api_error_rate                  NUMERIC(12, 8) NOT NULL DEFAULT 0,
    api_slowest_duration_ms         BIGINT NOT NULL DEFAULT 0,
    worker_run_count                BIGINT NOT NULL DEFAULT 0,
    worker_failed_count             BIGINT NOT NULL DEFAULT 0,
    worker_warning_count            BIGINT NOT NULL DEFAULT 0,
    deployment_health_status        VARCHAR(24),
    vendor_readiness_watch_count    BIGINT NOT NULL DEFAULT 0,
    invoice_outstanding_amount      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    customer_health_risk_count      BIGINT NOT NULL DEFAULT 0,
    capacity_alert_count            BIGINT NOT NULL DEFAULT 0,
    open_capacity_alert_count       BIGINT NOT NULL DEFAULT 0,
    details                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (environment, report_date),
    CHECK (status IN ('success', 'warning', 'critical')),
    CHECK (api_request_count >= 0),
    CHECK (api_failed_count >= 0),
    CHECK (api_error_rate >= 0),
    CHECK (api_slowest_duration_ms >= 0),
    CHECK (worker_run_count >= 0),
    CHECK (worker_failed_count >= 0),
    CHECK (worker_warning_count >= 0),
    CHECK (vendor_readiness_watch_count >= 0),
    CHECK (invoice_outstanding_amount >= 0),
    CHECK (customer_health_risk_count >= 0),
    CHECK (capacity_alert_count >= 0),
    CHECK (open_capacity_alert_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_runtime_daily_report_status
    ON qmeta.runtime_daily_report(environment, report_date DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.capacity_alert (
    capacity_alert_id       BIGSERIAL PRIMARY KEY,
    alert_key               VARCHAR(256) NOT NULL UNIQUE,
    alert_id                BIGINT REFERENCES qmeta.alert_event(alert_id) ON DELETE SET NULL,
    environment             VARCHAR(64) NOT NULL DEFAULT 'local',
    component               VARCHAR(64) NOT NULL,
    metric_name             VARCHAR(96) NOT NULL,
    severity                VARCHAR(24) NOT NULL DEFAULT 'medium',
    status                  VARCHAR(24) NOT NULL DEFAULT 'open',
    metric_value            NUMERIC(28, 12) NOT NULL,
    threshold_value         NUMERIC(28, 12) NOT NULL,
    unit                    VARCHAR(32) NOT NULL DEFAULT 'count',
    message                 TEXT NOT NULL,
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'acknowledged', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS idx_capacity_alert_status
    ON qmeta.capacity_alert(status, severity, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_capacity_alert_lookup
    ON qmeta.capacity_alert(environment, component, metric_name, last_seen_at DESC);
