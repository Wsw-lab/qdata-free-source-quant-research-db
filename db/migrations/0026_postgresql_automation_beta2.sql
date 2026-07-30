-- A 股量化数据平台 Beta-2：真实审批/通知系统联调控制层

CREATE TABLE IF NOT EXISTS qmeta.automation_external_channel (
    channel_id                 BIGSERIAL PRIMARY KEY,
    channel_code               VARCHAR(128) NOT NULL UNIQUE,
    channel_name               VARCHAR(220) NOT NULL,
    channel_type               VARCHAR(32) NOT NULL,
    environment                VARCHAR(32) NOT NULL DEFAULT 'local',
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    endpoint_url               TEXT,
    allowlist_code             VARCHAR(128),
    secret_ref                 VARCHAR(128),
    signing_algorithm          VARCHAR(32) NOT NULL DEFAULT 'none',
    timeout_seconds            INTEGER NOT NULL DEFAULT 10,
    max_retry_count            INTEGER NOT NULL DEFAULT 2,
    retry_backoff_seconds      INTEGER NOT NULL DEFAULT 60,
    duplicate_window_seconds   INTEGER NOT NULL DEFAULT 300,
    owner                      VARCHAR(128),
    runbook_code               VARCHAR(128),
    config                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (channel_type IN ('webhook', 'feishu', 'wecom', 'email', 'manual')),
    CHECK (status IN ('active', 'inactive', 'disabled')),
    CHECK (signing_algorithm IN ('none', 'hmac_sha256')),
    CHECK (timeout_seconds >= 1),
    CHECK (max_retry_count >= 0),
    CHECK (retry_backoff_seconds >= 0),
    CHECK (duplicate_window_seconds >= 0)
);

CREATE INDEX IF NOT EXISTS idx_automation_external_channel_env_status
    ON qmeta.automation_external_channel(environment, status, channel_type);

CREATE TABLE IF NOT EXISTS qmeta.automation_external_dispatch (
    dispatch_id                BIGSERIAL PRIMARY KEY,
    dispatch_code              VARCHAR(260) NOT NULL UNIQUE,
    automation_action_id       BIGINT NOT NULL REFERENCES qmeta.automation_action(automation_action_id) ON DELETE CASCADE,
    attempt_id                 BIGINT REFERENCES qmeta.automation_execution_attempt(attempt_id) ON DELETE SET NULL,
    channel_id                 BIGINT NOT NULL REFERENCES qmeta.automation_external_channel(channel_id) ON DELETE CASCADE,
    executor_id                BIGINT REFERENCES qmeta.automation_executor(executor_id) ON DELETE SET NULL,
    idempotency_key            VARCHAR(280) NOT NULL,
    dispatch_type              VARCHAR(32) NOT NULL DEFAULT 'notification',
    trigger_mode               VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                     VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL DEFAULT 'beta2',
    request_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    retry_count                INTEGER NOT NULL DEFAULT 0,
    max_retry_count            INTEGER NOT NULL DEFAULT 0,
    next_retry_at              TIMESTAMPTZ,
    dispatched_at              TIMESTAMPTZ,
    acknowledged_at            TIMESTAMPTZ,
    recovered_at               TIMESTAMPTZ,
    recovered_by               VARCHAR(128),
    recovery_reason            TEXT,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (dispatch_type IN ('notification', 'approval_request', 'manual_review')),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (status IN ('planned', 'sent', 'acknowledged', 'failed', 'retry_scheduled', 'dead_letter', 'recovered', 'suppressed')),
    CHECK (retry_count >= 0),
    CHECK (max_retry_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_automation_external_dispatch_status
    ON qmeta.automation_external_dispatch(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_automation_external_dispatch_action
    ON qmeta.automation_external_dispatch(automation_action_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_automation_external_dispatch_idempotency
    ON qmeta.automation_external_dispatch(idempotency_key, created_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.automation_recovery_runbook (
    runbook_id                 BIGSERIAL PRIMARY KEY,
    runbook_code               VARCHAR(128) NOT NULL UNIQUE,
    runbook_name               VARCHAR(220) NOT NULL,
    failure_class              VARCHAR(64) NOT NULL,
    severity                   VARCHAR(24) NOT NULL DEFAULT 'medium',
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    owner                      VARCHAR(128),
    recovery_steps             JSONB NOT NULL DEFAULT '[]'::jsonb,
    rollback_steps             JSONB NOT NULL DEFAULT '[]'::jsonb,
    drill_frequency_days       INTEGER NOT NULL DEFAULT 30,
    last_drill_at              TIMESTAMPTZ,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('active', 'inactive', 'disabled')),
    CHECK (drill_frequency_days >= 1)
);

CREATE INDEX IF NOT EXISTS idx_automation_recovery_runbook_status
    ON qmeta.automation_recovery_runbook(status, failure_class);

INSERT INTO qmeta.automation_recovery_runbook (
    runbook_code, runbook_name, failure_class, severity, status,
    owner, recovery_steps, rollback_steps, details
) VALUES
    (
        'beta2-webhook-timeout',
        'Beta-2 webhook timeout recovery',
        'webhook_timeout',
        'high',
        'active',
        'platform-ops',
        '["check endpoint health","verify allowlist and DNS","replay dispatch with --force after endpoint recovers","recover dead-letter with reason"]'::jsonb,
        '["disable affected channel","switch to manual review channel","notify owner from Kappa dispatch detail"]'::jsonb,
        '{"source":"beta2"}'::jsonb
    ),
    (
        'beta2-signature-mismatch',
        'Beta-2 signature mismatch recovery',
        'signature_mismatch',
        'critical',
        'active',
        'platform-security',
        '["verify QDATA_ALPHA2_HMAC_SECRET","rotate secret ref if leaked","rerun signed smoke","recover blocked dispatch"]'::jsonb,
        '["disable signed channel","revoke exposed token","keep affected dispatch in dead-letter until reviewed"]'::jsonb,
        '{"source":"beta2"}'::jsonb
    )
ON CONFLICT (runbook_code) DO UPDATE SET
    runbook_name = EXCLUDED.runbook_name,
    failure_class = EXCLUDED.failure_class,
    severity = EXCLUDED.severity,
    status = 'active',
    owner = EXCLUDED.owner,
    recovery_steps = EXCLUDED.recovery_steps,
    rollback_steps = EXCLUDED.rollback_steps,
    details = EXCLUDED.details,
    updated_at = now();

INSERT INTO qmeta.automation_external_channel (
    channel_code, channel_name, channel_type, environment, status,
    endpoint_url, allowlist_code, secret_ref, signing_algorithm,
    timeout_seconds, max_retry_count, retry_backoff_seconds,
    duplicate_window_seconds, owner, runbook_code, config, details
) VALUES
    (
        'beta2-local-approval-webhook',
        'Beta-2 local approval webhook',
        'webhook',
        'local',
        'active',
        'http://127.0.0.1:18100/beta2-approval',
        'alpha2-webhook-localhost',
        'alpha2-local-hmac',
        'hmac_sha256',
        5,
        2,
        30,
        300,
        'platform-ops',
        'beta2-webhook-timeout',
        '{"dispatch_type":"approval_request","sandbox":true}'::jsonb,
        '{"source":"beta2"}'::jsonb
    ),
    (
        'beta2-local-deadletter-webhook',
        'Beta-2 local dead-letter webhook',
        'webhook',
        'local',
        'active',
        'http://127.0.0.1:18101/beta2-deadletter',
        'alpha2-webhook-localhost',
        'alpha2-local-hmac',
        'hmac_sha256',
        2,
        0,
        0,
        0,
        'platform-ops',
        'beta2-webhook-timeout',
        '{"dispatch_type":"notification","sandbox":true,"expected_failure":"dead_letter_smoke"}'::jsonb,
        '{"source":"beta2"}'::jsonb
    )
ON CONFLICT (channel_code) DO UPDATE SET
    channel_name = EXCLUDED.channel_name,
    channel_type = EXCLUDED.channel_type,
    environment = EXCLUDED.environment,
    status = 'active',
    endpoint_url = EXCLUDED.endpoint_url,
    allowlist_code = EXCLUDED.allowlist_code,
    secret_ref = EXCLUDED.secret_ref,
    signing_algorithm = EXCLUDED.signing_algorithm,
    timeout_seconds = EXCLUDED.timeout_seconds,
    max_retry_count = EXCLUDED.max_retry_count,
    retry_backoff_seconds = EXCLUDED.retry_backoff_seconds,
    duplicate_window_seconds = EXCLUDED.duplicate_window_seconds,
    owner = EXCLUDED.owner,
    runbook_code = EXCLUDED.runbook_code,
    config = EXCLUDED.config,
    details = EXCLUDED.details,
    updated_at = now();
