-- A 股量化数据平台 Phi：统一策略引擎、策略信号、决策和升级事件

CREATE TABLE IF NOT EXISTS qmeta.strategy_policy (
    policy_id               BIGSERIAL PRIMARY KEY,
    policy_code             VARCHAR(160) NOT NULL UNIQUE,
    policy_name             VARCHAR(180) NOT NULL,
    domain                  VARCHAR(32) NOT NULL,
    subject_type            VARCHAR(32) NOT NULL,
    decision_type           VARCHAR(32) NOT NULL,
    default_action          VARCHAR(64) NOT NULL,
    status                  VARCHAR(24) NOT NULL DEFAULT 'active',
    severity_floor          VARCHAR(24) NOT NULL DEFAULT 'low',
    evaluation_cadence      VARCHAR(32) NOT NULL DEFAULT 'daily',
    owner                   VARCHAR(128),
    description             TEXT,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (domain IN ('data_quality', 'vendor', 'runtime', 'commercial', 'payment', 'unified')),
    CHECK (subject_type IN ('dataset', 'source', 'environment', 'tenant', 'project', 'product', 'invoice', 'payment', 'platform')),
    CHECK (decision_type IN ('gate', 'role', 'escalation', 'limit', 'reconcile', 'monitor')),
    CHECK (status IN ('active', 'testing', 'paused', 'retired')),
    CHECK (severity_floor IN ('low', 'medium', 'high', 'critical')),
    CHECK (evaluation_cadence IN ('intraday', 'daily', 'weekly', 'monthly', 'manual'))
);

CREATE INDEX IF NOT EXISTS idx_strategy_policy_domain_status
    ON qmeta.strategy_policy(domain, status, decision_type);

CREATE TABLE IF NOT EXISTS qmeta.strategy_run (
    run_id                  BIGSERIAL PRIMARY KEY,
    run_code                VARCHAR(200) NOT NULL UNIQUE,
    run_date                DATE NOT NULL,
    environment             VARCHAR(64) NOT NULL DEFAULT 'local',
    trigger_mode            VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                  VARCHAR(24) NOT NULL DEFAULT 'success',
    policy_count            INTEGER NOT NULL DEFAULT 0,
    signal_count            INTEGER NOT NULL DEFAULT 0,
    decision_count          INTEGER NOT NULL DEFAULT 0,
    escalation_count        INTEGER NOT NULL DEFAULT 0,
    highest_severity        VARCHAR(24) NOT NULL DEFAULT 'low',
    started_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at             TIMESTAMPTZ,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (status IN ('success', 'warning', 'critical', 'failed')),
    CHECK (highest_severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (policy_count >= 0),
    CHECK (signal_count >= 0),
    CHECK (decision_count >= 0),
    CHECK (escalation_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_strategy_run_lookup
    ON qmeta.strategy_run(environment, run_date DESC, status, highest_severity);

CREATE TABLE IF NOT EXISTS qmeta.strategy_signal (
    signal_id               BIGSERIAL PRIMARY KEY,
    run_id                  BIGINT NOT NULL REFERENCES qmeta.strategy_run(run_id) ON DELETE CASCADE,
    policy_id               BIGINT REFERENCES qmeta.strategy_policy(policy_id) ON DELETE SET NULL,
    signal_code             VARCHAR(240) NOT NULL UNIQUE,
    domain                  VARCHAR(32) NOT NULL,
    subject_type            VARCHAR(32) NOT NULL,
    subject_code            VARCHAR(200) NOT NULL,
    signal_type             VARCHAR(64) NOT NULL,
    severity                VARCHAR(24) NOT NULL,
    status                  VARCHAR(24) NOT NULL DEFAULT 'active',
    metric_name             VARCHAR(96),
    metric_value            NUMERIC(24, 8),
    threshold_value         NUMERIC(24, 8),
    score_delta             NUMERIC(10, 6) NOT NULL DEFAULT 0,
    source_table            VARCHAR(128),
    source_ref              VARCHAR(240),
    message                 TEXT NOT NULL,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (domain IN ('data_quality', 'vendor', 'runtime', 'commercial', 'payment', 'unified')),
    CHECK (subject_type IN ('dataset', 'source', 'environment', 'tenant', 'project', 'product', 'invoice', 'payment', 'platform')),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('active', 'suppressed', 'resolved')),
    CHECK (score_delta >= -1 AND score_delta <= 1)
);

CREATE INDEX IF NOT EXISTS idx_strategy_signal_run_severity
    ON qmeta.strategy_signal(run_id, severity, domain);

CREATE INDEX IF NOT EXISTS idx_strategy_signal_subject
    ON qmeta.strategy_signal(domain, subject_type, subject_code, observed_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.strategy_decision (
    decision_id             BIGSERIAL PRIMARY KEY,
    run_id                  BIGINT NOT NULL REFERENCES qmeta.strategy_run(run_id) ON DELETE CASCADE,
    policy_id               BIGINT REFERENCES qmeta.strategy_policy(policy_id) ON DELETE SET NULL,
    decision_code           VARCHAR(240) NOT NULL UNIQUE,
    domain                  VARCHAR(32) NOT NULL,
    subject_type            VARCHAR(32) NOT NULL,
    subject_code            VARCHAR(200) NOT NULL,
    decision_type           VARCHAR(32) NOT NULL,
    action                  VARCHAR(64) NOT NULL,
    status                  VARCHAR(24) NOT NULL,
    severity                VARCHAR(24) NOT NULL,
    confidence_score        NUMERIC(8, 6) NOT NULL DEFAULT 1,
    priority_score          NUMERIC(10, 6) NOT NULL DEFAULT 0,
    recommended_owner       VARCHAR(128),
    reason                  TEXT NOT NULL,
    signal_count            INTEGER NOT NULL DEFAULT 0,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    decided_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (domain IN ('data_quality', 'vendor', 'runtime', 'commercial', 'payment', 'unified')),
    CHECK (subject_type IN ('dataset', 'source', 'environment', 'tenant', 'project', 'product', 'invoice', 'payment', 'platform')),
    CHECK (decision_type IN ('gate', 'role', 'escalation', 'limit', 'reconcile', 'monitor')),
    CHECK (status IN ('allow', 'watch', 'review', 'escalate', 'block', 'approved', 'hold')),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (confidence_score >= 0 AND confidence_score <= 1),
    CHECK (priority_score >= 0),
    CHECK (signal_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_strategy_decision_run_status
    ON qmeta.strategy_decision(run_id, status, severity, priority_score DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_decision_subject
    ON qmeta.strategy_decision(domain, subject_type, subject_code, decided_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.strategy_escalation_event (
    escalation_id           BIGSERIAL PRIMARY KEY,
    event_code              VARCHAR(260) NOT NULL UNIQUE,
    run_id                  BIGINT NOT NULL REFERENCES qmeta.strategy_run(run_id) ON DELETE CASCADE,
    decision_id             BIGINT REFERENCES qmeta.strategy_decision(decision_id) ON DELETE CASCADE,
    signal_id               BIGINT REFERENCES qmeta.strategy_signal(signal_id) ON DELETE SET NULL,
    escalation_type         VARCHAR(64) NOT NULL,
    severity                VARCHAR(24) NOT NULL,
    status                  VARCHAR(24) NOT NULL DEFAULT 'open',
    owner                   VARCHAR(128),
    message                 TEXT NOT NULL,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (escalation_type IN ('human_review', 'source_owner', 'runtime_owner', 'finance_owner', 'commercial_owner')),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'acknowledged', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS idx_strategy_escalation_status
    ON qmeta.strategy_escalation_event(status, severity, created_at DESC);

INSERT INTO qmeta.strategy_policy (
    policy_code, policy_name, domain, subject_type, decision_type,
    default_action, status, severity_floor, evaluation_cadence, owner, description, details
) VALUES
    (
        'phi-data-quality-gate',
        'Phi Data Quality Production Gate',
        'data_quality',
        'dataset',
        'gate',
        'allow_production',
        'active',
        'medium',
        'daily',
        'data-ops',
        'Gate dataset production readiness using pipeline, repair queue and quality conflict signals.',
        '{"sources":["pipeline_repair_queue","multi_source_quality_daily","alert_event"]}'::jsonb
    ),
    (
        'phi-vendor-source-role',
        'Phi Vendor Source Role Decision',
        'vendor',
        'source',
        'role',
        'keep_backup',
        'active',
        'medium',
        'daily',
        'vendor-ops',
        'Promote, watch or hold vendor source roles using Pi readiness reviews.',
        '{"sources":["vendor_readiness_review","vendor_readiness_window"]}'::jsonb
    ),
    (
        'phi-runtime-capacity-gate',
        'Phi Runtime Capacity Gate',
        'runtime',
        'environment',
        'gate',
        'monitor',
        'active',
        'medium',
        'intraday',
        'platform-ops',
        'Detect runtime degradation using deployment health, Sigma reports and capacity alerts.',
        '{"sources":["deployment_health_snapshot","runtime_daily_report","capacity_alert"]}'::jsonb
    ),
    (
        'phi-commercial-risk-gate',
        'Phi Commercial Risk Gate',
        'commercial',
        'project',
        'limit',
        'monitor',
        'active',
        'medium',
        'daily',
        'commercial-ops',
        'Decide project commercial risk using budget, AR aging and customer health.',
        '{"sources":["budget_usage_snapshot","budget_alert","ar_aging_snapshot","customer_health_snapshot"]}'::jsonb
    ),
    (
        'phi-payment-revenue-reconcile',
        'Phi Payment Revenue Reconciliation',
        'payment',
        'payment',
        'reconcile',
        'reconcile_payment',
        'active',
        'medium',
        'daily',
        'finance-ops',
        'Escalate unmatched payments, reconciliation mismatch and outstanding receivables.',
        '{"sources":["payment_transaction","payment_import_batch","payment_invoice_match","revenue_reconciliation_run"]}'::jsonb
    )
ON CONFLICT (policy_code) DO UPDATE SET
    policy_name = EXCLUDED.policy_name,
    domain = EXCLUDED.domain,
    subject_type = EXCLUDED.subject_type,
    decision_type = EXCLUDED.decision_type,
    default_action = EXCLUDED.default_action,
    status = EXCLUDED.status,
    severity_floor = EXCLUDED.severity_floor,
    evaluation_cadence = EXCLUDED.evaluation_cadence,
    owner = EXCLUDED.owner,
    description = EXCLUDED.description,
    details = EXCLUDED.details,
    updated_at = now();
