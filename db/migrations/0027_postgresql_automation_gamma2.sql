-- A 股量化数据平台 Gamma-2：多环境真实通知通道与密钥轮换演练层

CREATE TABLE IF NOT EXISTS qmeta.automation_channel_profile (
    profile_id                 BIGSERIAL PRIMARY KEY,
    profile_code               VARCHAR(128) NOT NULL UNIQUE,
    channel_id                 BIGINT NOT NULL REFERENCES qmeta.automation_external_channel(channel_id) ON DELETE CASCADE,
    provider_code              VARCHAR(64) NOT NULL,
    environment                VARCHAR(32) NOT NULL DEFAULT 'local',
    profile_status             VARCHAR(24) NOT NULL DEFAULT 'active',
    readiness_status           VARCHAR(32) NOT NULL DEFAULT 'not_configured',
    dry_run_only               BOOLEAN NOT NULL DEFAULT TRUE,
    endpoint_url               TEXT,
    dry_run_endpoint_url       TEXT,
    live_endpoint_url          TEXT,
    allowlist_code             VARCHAR(128),
    secret_ref                 VARCHAR(128),
    next_secret_ref            VARCHAR(128),
    signing_algorithm          VARCHAR(32) NOT NULL DEFAULT 'none',
    owner                      VARCHAR(128),
    runbook_code               VARCHAR(128),
    last_validation_code       VARCHAR(160),
    last_validation_status     VARCHAR(32),
    last_validated_at          TIMESTAMPTZ,
    config                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (provider_code IN ('webhook', 'feishu', 'wecom', 'email', 'manual')),
    CHECK (profile_status IN ('active', 'inactive', 'disabled')),
    CHECK (readiness_status IN ('not_configured', 'dry_run_ready', 'live_ready', 'blocked', 'failed')),
    CHECK (signing_algorithm IN ('none', 'hmac_sha256'))
);

CREATE INDEX IF NOT EXISTS idx_automation_channel_profile_env_status
    ON qmeta.automation_channel_profile(environment, profile_status, readiness_status);

CREATE INDEX IF NOT EXISTS idx_automation_channel_profile_channel
    ON qmeta.automation_channel_profile(channel_id, environment);

CREATE TABLE IF NOT EXISTS qmeta.automation_channel_validation (
    validation_id              BIGSERIAL PRIMARY KEY,
    validation_code            VARCHAR(160) NOT NULL UNIQUE,
    profile_id                 BIGINT NOT NULL REFERENCES qmeta.automation_channel_profile(profile_id) ON DELETE CASCADE,
    channel_id                 BIGINT NOT NULL REFERENCES qmeta.automation_external_channel(channel_id) ON DELETE CASCADE,
    dispatch_id                BIGINT REFERENCES qmeta.automation_external_dispatch(dispatch_id) ON DELETE SET NULL,
    validation_type            VARCHAR(40) NOT NULL DEFAULT 'dry_run_dispatch',
    trigger_mode               VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                     VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL DEFAULT 'gamma2',
    target_secret_ref          VARCHAR(128),
    request_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    started_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                TIMESTAMPTZ,
    duration_ms                INTEGER NOT NULL DEFAULT 0,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (validation_type IN ('dry_run_dispatch', 'live_dispatch', 'secret_rotation', 'rollback_drill')),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (status IN ('planned', 'success', 'failed', 'blocked', 'skipped')),
    CHECK (duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_automation_channel_validation_profile
    ON qmeta.automation_channel_validation(profile_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_automation_channel_validation_status
    ON qmeta.automation_channel_validation(status, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.automation_secret_rotation (
    rotation_id                BIGSERIAL PRIMARY KEY,
    rotation_code              VARCHAR(160) NOT NULL UNIQUE,
    environment                VARCHAR(32) NOT NULL DEFAULT 'local',
    secret_ref                 VARCHAR(128) NOT NULL,
    next_secret_ref            VARCHAR(128) NOT NULL,
    rotation_type              VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                     VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL DEFAULT 'gamma2',
    approved_by                VARCHAR(128),
    reason                     TEXT,
    profile_id                 BIGINT REFERENCES qmeta.automation_channel_profile(profile_id) ON DELETE SET NULL,
    validation_id              BIGINT REFERENCES qmeta.automation_channel_validation(validation_id) ON DELETE SET NULL,
    affected_channel_count     INTEGER NOT NULL DEFAULT 0,
    validated_at               TIMESTAMPTZ,
    applied_at                 TIMESTAMPTZ,
    rolled_back_at             TIMESTAMPTZ,
    rolled_back_by             VARCHAR(128),
    rollback_reason            TEXT,
    error_message              TEXT,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (rotation_type IN ('manual', 'scheduled', 'emergency', 'drill')),
    CHECK (status IN ('planned', 'validated', 'applied', 'rolled_back', 'failed', 'blocked')),
    CHECK (affected_channel_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_automation_secret_rotation_status
    ON qmeta.automation_secret_rotation(status, environment, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_automation_secret_rotation_secret
    ON qmeta.automation_secret_rotation(secret_ref, next_secret_ref, created_at DESC);

INSERT INTO qmeta.automation_recovery_runbook (
    runbook_code, runbook_name, failure_class, severity, status,
    owner, recovery_steps, rollback_steps, details
) VALUES
    (
        'gamma2-secret-rotation',
        'Gamma-2 secret rotation recovery',
        'secret_rotation',
        'critical',
        'active',
        'platform-security',
        '["verify current and next secret env vars","run dry-run dispatch validation","apply rotation only after signed validation succeeds","record rollback evidence"]'::jsonb,
        '["rollback affected channel secret_ref to previous value","rerun dry-run validation","disable rotated profile if rollback fails"]'::jsonb,
        '{"source":"gamma2"}'::jsonb
    ),
    (
        'gamma2-provider-readiness',
        'Gamma-2 provider readiness recovery',
        'provider_readiness',
        'high',
        'active',
        'platform-ops',
        '["check provider endpoint and callback status","verify allowlist and HMAC signature","compare profile env with channel env","mark blocked until provider owner confirms"]'::jsonb,
        '["switch affected profile to dry_run_only","disable live endpoint","keep Beta-2 channel available for manual fallback"]'::jsonb,
        '{"source":"gamma2"}'::jsonb
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
) VALUES
    (
        'gamma2-local-hmac-current',
        'automation',
        'hmac',
        'active',
        'platform-security',
        'Local Gamma-2 current HMAC secret for provider dry-run dispatch.',
        '{"env_var":"QDATA_GAMMA2_HMAC_SECRET_CURRENT","source":"gamma2","rotation_role":"current"}'::jsonb
    ),
    (
        'gamma2-local-hmac-next',
        'automation',
        'hmac',
        'active',
        'platform-security',
        'Local Gamma-2 next HMAC secret candidate for rotation drills.',
        '{"env_var":"QDATA_GAMMA2_HMAC_SECRET_NEXT","source":"gamma2","rotation_role":"next"}'::jsonb
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
) VALUES
    (
        'gamma2-local-feishu-dryrun',
        'Gamma-2 local Feishu dry-run channel',
        'feishu',
        'local',
        'active',
        'http://127.0.0.1:18102/gamma2/feishu',
        'alpha2-webhook-localhost',
        'gamma2-local-hmac-current',
        'hmac_sha256',
        5,
        1,
        20,
        60,
        'platform-ops',
        'gamma2-provider-readiness',
        '{"dispatch_type":"approval_request","dry_run_only":true,"provider":"feishu"}'::jsonb,
        '{"source":"gamma2"}'::jsonb
    ),
    (
        'gamma2-local-wecom-dryrun',
        'Gamma-2 local WeCom dry-run channel',
        'wecom',
        'local',
        'active',
        'http://127.0.0.1:18103/gamma2/wecom',
        'alpha2-webhook-localhost',
        'gamma2-local-hmac-current',
        'hmac_sha256',
        5,
        1,
        20,
        60,
        'platform-ops',
        'gamma2-provider-readiness',
        '{"dispatch_type":"notification","dry_run_only":true,"provider":"wecom"}'::jsonb,
        '{"source":"gamma2"}'::jsonb
    ),
    (
        'gamma2-local-email-dryrun',
        'Gamma-2 local email dry-run channel',
        'email',
        'local',
        'active',
        'http://127.0.0.1:18104/gamma2/email',
        'alpha2-webhook-localhost',
        'gamma2-local-hmac-current',
        'hmac_sha256',
        5,
        1,
        20,
        60,
        'platform-ops',
        'gamma2-provider-readiness',
        '{"dispatch_type":"manual_review","dry_run_only":true,"provider":"email"}'::jsonb,
        '{"source":"gamma2"}'::jsonb
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
    item.profile_code,
    ch.channel_id,
    item.provider_code,
    item.environment,
    item.profile_status,
    item.readiness_status,
    item.dry_run_only,
    item.endpoint_url,
    item.dry_run_endpoint_url,
    item.live_endpoint_url,
    item.allowlist_code,
    item.secret_ref,
    item.next_secret_ref,
    item.signing_algorithm,
    item.owner,
    item.runbook_code,
    item.config,
    item.details
FROM (
    VALUES
        (
            'gamma2-local-feishu-profile',
            'gamma2-local-feishu-dryrun',
            'feishu',
            'local',
            'active',
            'not_configured',
            TRUE,
            'http://127.0.0.1:18102/gamma2/feishu',
            'http://127.0.0.1:18102/gamma2/feishu',
            NULL::text,
            'alpha2-webhook-localhost',
            'gamma2-local-hmac-current',
            'gamma2-local-hmac-next',
            'hmac_sha256',
            'platform-ops',
            'gamma2-provider-readiness',
            '{"approval_owner":"quant-ops","dry_run_payload":"feishu_card"}'::jsonb,
            '{"source":"gamma2"}'::jsonb
        ),
        (
            'gamma2-local-wecom-profile',
            'gamma2-local-wecom-dryrun',
            'wecom',
            'local',
            'active',
            'not_configured',
            TRUE,
            'http://127.0.0.1:18103/gamma2/wecom',
            'http://127.0.0.1:18103/gamma2/wecom',
            NULL::text,
            'alpha2-webhook-localhost',
            'gamma2-local-hmac-current',
            'gamma2-local-hmac-next',
            'hmac_sha256',
            'platform-ops',
            'gamma2-provider-readiness',
            '{"approval_owner":"quant-ops","dry_run_payload":"wecom_markdown"}'::jsonb,
            '{"source":"gamma2"}'::jsonb
        ),
        (
            'gamma2-local-email-profile',
            'gamma2-local-email-dryrun',
            'email',
            'local',
            'active',
            'not_configured',
            TRUE,
            'http://127.0.0.1:18104/gamma2/email',
            'http://127.0.0.1:18104/gamma2/email',
            NULL::text,
            'alpha2-webhook-localhost',
            'gamma2-local-hmac-current',
            'gamma2-local-hmac-next',
            'hmac_sha256',
            'platform-ops',
            'gamma2-provider-readiness',
            '{"approval_owner":"quant-ops","dry_run_payload":"email_digest"}'::jsonb,
            '{"source":"gamma2"}'::jsonb
        )
) AS item(
    profile_code, channel_code, provider_code, environment, profile_status,
    readiness_status, dry_run_only, endpoint_url, dry_run_endpoint_url,
    live_endpoint_url, allowlist_code, secret_ref, next_secret_ref,
    signing_algorithm, owner, runbook_code, config, details
)
JOIN qmeta.automation_external_channel ch ON ch.channel_code = item.channel_code
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
