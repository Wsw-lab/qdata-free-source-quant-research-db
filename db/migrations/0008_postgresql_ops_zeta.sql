-- A 股量化运维 Zeta：质量看板、SLA 和告警治理

CREATE TABLE IF NOT EXISTS qmeta.sla_policy (
    policy_id               BIGSERIAL PRIMARY KEY,
    policy_code             VARCHAR(128) NOT NULL UNIQUE,
    policy_name             VARCHAR(128) NOT NULL,
    dataset_id              BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    job_id                  BIGINT REFERENCES qmeta.pipeline_job(job_id),
    source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    target_finish_time      TIME,
    timezone                VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    min_completeness        NUMERIC(12, 8),
    max_conflict_rate       NUMERIC(12, 8),
    max_api_error_rate      NUMERIC(12, 8),
    max_duration_ms         BIGINT,
    alert_severity          VARCHAR(24) NOT NULL DEFAULT 'high',
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    owner                   VARCHAR(128),
    notification_channels   JSONB NOT NULL DEFAULT '[]'::jsonb,
    description             TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (min_completeness IS NULL OR (min_completeness >= 0 AND min_completeness <= 1)),
    CHECK (max_conflict_rate IS NULL OR (max_conflict_rate >= 0 AND max_conflict_rate <= 1)),
    CHECK (max_api_error_rate IS NULL OR (max_api_error_rate >= 0 AND max_api_error_rate <= 1)),
    CHECK (max_duration_ms IS NULL OR max_duration_ms >= 0),
    CHECK (alert_severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_sla_policy_active_dataset_job
    ON qmeta.sla_policy(is_active, dataset_id, job_id, source_id);

CREATE TABLE IF NOT EXISTS qmeta.alert_event (
    alert_id            BIGSERIAL PRIMARY KEY,
    alert_key           VARCHAR(256) NOT NULL UNIQUE,
    policy_id           BIGINT REFERENCES qmeta.sla_policy(policy_id),
    dataset_id          BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    job_id              BIGINT REFERENCES qmeta.pipeline_job(job_id),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    trade_date          DATE,
    alert_type          VARCHAR(64) NOT NULL,
    severity            VARCHAR(24) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'open',
    metric_name         VARCHAR(96),
    metric_value        NUMERIC(28, 12),
    threshold_value     NUMERIC(28, 12),
    message             TEXT NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at     TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (alert_type IN (
        'missing_run',
        'pipeline_status',
        'pipeline_late',
        'completeness_below_sla',
        'conflict_rate_above_sla',
        'api_error_rate_above_sla',
        'duration_above_sla'
    )),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'acknowledged', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS idx_alert_event_status_date
    ON qmeta.alert_event(status, trade_date DESC, severity);

CREATE INDEX IF NOT EXISTS idx_alert_event_policy_date
    ON qmeta.alert_event(policy_id, trade_date DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.ops_dashboard_snapshot (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    snapshot_code       VARCHAR(160) NOT NULL UNIQUE,
    snapshot_date       DATE NOT NULL DEFAULT CURRENT_DATE,
    window_start        DATE NOT NULL,
    window_end          DATE NOT NULL,
    job_code            VARCHAR(128),
    dataset_code        VARCHAR(96),
    pipeline_summary    JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    sla_summary         JSONB NOT NULL DEFAULT '{}'::jsonb,
    api_summary         JSONB NOT NULL DEFAULT '{}'::jsonb,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (window_end >= window_start)
);

CREATE INDEX IF NOT EXISTS idx_ops_dashboard_snapshot_window
    ON qmeta.ops_dashboard_snapshot(window_start DESC, window_end DESC, created_at DESC);
