-- A 股量化数据平台 Delta-2：企业微信 live validation 与回执审计

CREATE TABLE IF NOT EXISTS qmeta.automation_live_provider_receipt (
    receipt_id                 BIGSERIAL PRIMARY KEY,
    receipt_code               VARCHAR(180) NOT NULL UNIQUE,
    validation_id              BIGINT REFERENCES qmeta.automation_channel_validation(validation_id) ON DELETE SET NULL,
    profile_id                 BIGINT REFERENCES qmeta.automation_channel_profile(profile_id) ON DELETE SET NULL,
    channel_id                 BIGINT REFERENCES qmeta.automation_external_channel(channel_id) ON DELETE SET NULL,
    provider_code              VARCHAR(64) NOT NULL,
    environment                VARCHAR(32) NOT NULL DEFAULT 'live_test',
    message_type               VARCHAR(32) NOT NULL DEFAULT 'markdown',
    status                     VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL DEFAULT 'delta2',
    endpoint_secret_ref        VARCHAR(128),
    provider_status_code       INTEGER,
    provider_errcode           INTEGER,
    provider_errmsg            TEXT,
    request_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    sent_at                    TIMESTAMPTZ,
    acknowledged_at            TIMESTAMPTZ,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (provider_code IN ('wecom', 'feishu', 'email', 'webhook')),
    CHECK (message_type IN ('text', 'markdown')),
    CHECK (status IN ('planned', 'success', 'failed', 'blocked', 'skipped')),
    CHECK (provider_status_code IS NULL OR provider_status_code >= 100)
);

CREATE INDEX IF NOT EXISTS idx_automation_live_receipt_profile
    ON qmeta.automation_live_provider_receipt(profile_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_automation_live_receipt_status
    ON qmeta.automation_live_provider_receipt(provider_code, environment, status, created_at DESC);

INSERT INTO qmeta.automation_recovery_runbook (
    runbook_code, runbook_name, failure_class, severity, status,
    owner, recovery_steps, rollback_steps, details
) VALUES (
    'delta2-wecom-live',
    'Delta-2 WeCom live webhook recovery',
    'wecom_live_delivery',
    'high',
    'active',
    'platform-ops',
    '["verify QDATA_DELTA2_WECOM_WEBHOOK_URL is configured","send a blocked dry run before live message","check WeCom robot errcode and group delivery","disable profile if provider returns nonzero errcode"]'::jsonb,
    '["set profile readiness_status to blocked","clear live endpoint env var in runtime","fall back to Gamma-2 dry-run profile"]'::jsonb,
    '{"source":"delta2"}'::jsonb
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

INSERT INTO qmeta.automation_secret_ref (
    secret_ref, secret_scope, secret_kind, status, owner, description, metadata
) VALUES (
    'delta2-wecom-webhook-url',
    'automation',
    'generic',
    'active',
    'platform-ops',
    'Delta-2 WeCom group robot webhook URL; value must come from environment.',
    '{"env_var":"QDATA_DELTA2_WECOM_WEBHOOK_URL","source":"delta2","secret_role":"endpoint_url"}'::jsonb
)
ON CONFLICT (secret_ref) DO UPDATE SET
    status = 'active',
    owner = EXCLUDED.owner,
    description = EXCLUDED.description,
    metadata = EXCLUDED.metadata,
    updated_at = now();

INSERT INTO qmeta.automation_external_channel (
    channel_code, channel_name, channel_type, environment, status,
    endpoint_url, allowlist_code, secret_ref, signing_algorithm,
    timeout_seconds, max_retry_count, retry_backoff_seconds,
    duplicate_window_seconds, owner, runbook_code, config, details
) VALUES (
    'delta2-wecom-live-webhook',
    'Delta-2 WeCom live webhook',
    'wecom',
    'live_test',
    'active',
    NULL,
    NULL,
    'delta2-wecom-webhook-url',
    'none',
    10,
    0,
    0,
    0,
    'platform-ops',
    'delta2-wecom-live',
    '{"provider":"wecom","message_type":"markdown","endpoint_env_var":"QDATA_DELTA2_WECOM_WEBHOOK_URL","dry_run_only":false}'::jsonb,
    '{"source":"delta2","endpoint_url_storage":"env_var_only"}'::jsonb
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

INSERT INTO qmeta.automation_channel_profile (
    profile_code, channel_id, provider_code, environment, profile_status,
    readiness_status, dry_run_only, endpoint_url, dry_run_endpoint_url,
    live_endpoint_url, allowlist_code, secret_ref, next_secret_ref,
    signing_algorithm, owner, runbook_code, config, details
)
SELECT
    'delta2-wecom-live-profile',
    ch.channel_id,
    'wecom',
    'live_test',
    'active',
    'not_configured',
    FALSE,
    'env:QDATA_DELTA2_WECOM_WEBHOOK_URL',
    'env:QDATA_DELTA2_WECOM_WEBHOOK_URL',
    'env:QDATA_DELTA2_WECOM_WEBHOOK_URL',
    NULL,
    'delta2-wecom-webhook-url',
    NULL,
    'none',
    'platform-ops',
    'delta2-wecom-live',
    '{"message_type":"markdown","robot_type":"group_robot","approval_owner":"quant-ops","live_external_side_effect":true}'::jsonb,
    '{"source":"delta2","endpoint_url_storage":"env_var_only"}'::jsonb
FROM qmeta.automation_external_channel ch
WHERE ch.channel_code = 'delta2-wecom-live-webhook'
ON CONFLICT (profile_code) DO UPDATE SET
    channel_id = EXCLUDED.channel_id,
    provider_code = EXCLUDED.provider_code,
    environment = EXCLUDED.environment,
    dry_run_only = EXCLUDED.dry_run_only,
    endpoint_url = EXCLUDED.endpoint_url,
    dry_run_endpoint_url = EXCLUDED.dry_run_endpoint_url,
    live_endpoint_url = EXCLUDED.live_endpoint_url,
    allowlist_code = EXCLUDED.allowlist_code,
    secret_ref = EXCLUDED.secret_ref,
    next_secret_ref = EXCLUDED.next_secret_ref,
    signing_algorithm = EXCLUDED.signing_algorithm,
    owner = EXCLUDED.owner,
    runbook_code = EXCLUDED.runbook_code,
    config = EXCLUDED.config,
    details = EXCLUDED.details,
    updated_at = now();
