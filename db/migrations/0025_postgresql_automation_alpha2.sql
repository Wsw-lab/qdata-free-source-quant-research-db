-- A 股量化数据平台 Alpha-2：白名单 webhook/script 沙箱执行层

ALTER TABLE qmeta.automation_executor
    ADD COLUMN IF NOT EXISTS sandbox_mode BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS allowlist_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS secret_ref VARCHAR(128),
    ADD COLUMN IF NOT EXISTS signing_algorithm VARCHAR(32) NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS allowed_target TEXT;

ALTER TABLE qmeta.automation_executor
    DROP CONSTRAINT IF EXISTS automation_executor_signing_algorithm_check;

ALTER TABLE qmeta.automation_executor
    ADD CONSTRAINT automation_executor_signing_algorithm_check
        CHECK (signing_algorithm IN ('none', 'hmac_sha256'));

CREATE TABLE IF NOT EXISTS qmeta.automation_executor_allowlist (
    allowlist_id               BIGSERIAL PRIMARY KEY,
    allowlist_code             VARCHAR(128) NOT NULL UNIQUE,
    executor_type              VARCHAR(32) NOT NULL,
    target_pattern             TEXT NOT NULL,
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    sandbox_only               BOOLEAN NOT NULL DEFAULT TRUE,
    max_timeout_seconds        INTEGER NOT NULL DEFAULT 10,
    description                TEXT,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (executor_type IN ('webhook', 'script')),
    CHECK (status IN ('active', 'inactive', 'disabled')),
    CHECK (max_timeout_seconds >= 1)
);

CREATE INDEX IF NOT EXISTS idx_automation_allowlist_type_status
    ON qmeta.automation_executor_allowlist(executor_type, status);

CREATE TABLE IF NOT EXISTS qmeta.automation_secret_ref (
    secret_id                  BIGSERIAL PRIMARY KEY,
    secret_ref                 VARCHAR(128) NOT NULL UNIQUE,
    secret_scope               VARCHAR(64) NOT NULL DEFAULT 'automation',
    secret_kind                VARCHAR(32) NOT NULL DEFAULT 'hmac',
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    owner                      VARCHAR(128),
    description                TEXT,
    metadata                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (secret_kind IN ('hmac', 'bearer', 'basic', 'generic')),
    CHECK (status IN ('active', 'inactive', 'disabled'))
);

CREATE INDEX IF NOT EXISTS idx_automation_secret_ref_status
    ON qmeta.automation_secret_ref(secret_scope, status);

CREATE INDEX IF NOT EXISTS idx_automation_executor_allowlist
    ON qmeta.automation_executor(allowlist_code, executor_type, status);

INSERT INTO qmeta.automation_executor_allowlist (
    allowlist_code, executor_type, target_pattern, sandbox_only,
    max_timeout_seconds, description, details
) VALUES
    ('alpha2-webhook-localhost', 'webhook', 'http://127.0.0.1:*/*', TRUE, 5, 'Localhost webhook sandbox only', '{"source":"alpha2"}'::jsonb),
    ('alpha2-script-reporter', 'script', 'scripts/alpha2_executor_sandbox.py', TRUE, 5, 'Repository bundled script sandbox only', '{"source":"alpha2"}'::jsonb)
ON CONFLICT (allowlist_code) DO UPDATE SET
    executor_type = EXCLUDED.executor_type,
    target_pattern = EXCLUDED.target_pattern,
    sandbox_only = EXCLUDED.sandbox_only,
    max_timeout_seconds = EXCLUDED.max_timeout_seconds,
    description = EXCLUDED.description,
    status = 'active',
    updated_at = now();

INSERT INTO qmeta.automation_secret_ref (
    secret_ref, secret_scope, secret_kind, status, owner, description, metadata
) VALUES (
    'alpha2-local-hmac', 'automation', 'hmac', 'active', 'platform-ops',
    'Local Alpha-2 HMAC secret reference; value must come from environment.',
    '{"env_var":"QDATA_ALPHA2_HMAC_SECRET","source":"alpha2"}'::jsonb
)
ON CONFLICT (secret_ref) DO UPDATE SET
    status = 'active',
    owner = EXCLUDED.owner,
    description = EXCLUDED.description,
    metadata = EXCLUDED.metadata,
    updated_at = now();

INSERT INTO qmeta.automation_executor (
    executor_code, executor_name, executor_type, action_type, safety_level,
    status, requires_approval, max_retry_count, retry_backoff_seconds,
    timeout_seconds, endpoint_url, command_name, config,
    sandbox_mode, allowlist_code, secret_ref, signing_algorithm, allowed_target, updated_at
) VALUES
    (
        'alpha2-webhook-notify-owner',
        'Alpha-2 localhost webhook sandbox',
        'webhook',
        'notify_owner',
        'medium',
        'active',
        FALSE,
        1,
        30,
        5,
        'http://127.0.0.1:18099/alpha2-webhook',
        NULL,
        '{"operation":"notify_owner","sandbox":true}'::jsonb,
        TRUE,
        'alpha2-webhook-localhost',
        'alpha2-local-hmac',
        'hmac_sha256',
        'http://127.0.0.1:18099/alpha2-webhook',
        now()
    ),
    (
        'alpha2-script-notify-owner',
        'Alpha-2 script sandbox',
        'script',
        'notify_owner',
        'medium',
        'active',
        FALSE,
        1,
        30,
        5,
        NULL,
        'scripts/alpha2_executor_sandbox.py',
        '{"operation":"notify_owner","sandbox":true}'::jsonb,
        TRUE,
        'alpha2-script-reporter',
        NULL,
        'none',
        'scripts/alpha2_executor_sandbox.py',
        now()
    )
ON CONFLICT (executor_code) DO UPDATE SET
    executor_name = EXCLUDED.executor_name,
    executor_type = EXCLUDED.executor_type,
    action_type = EXCLUDED.action_type,
    safety_level = EXCLUDED.safety_level,
    status = 'active',
    requires_approval = EXCLUDED.requires_approval,
    max_retry_count = EXCLUDED.max_retry_count,
    retry_backoff_seconds = EXCLUDED.retry_backoff_seconds,
    timeout_seconds = EXCLUDED.timeout_seconds,
    endpoint_url = EXCLUDED.endpoint_url,
    command_name = EXCLUDED.command_name,
    config = EXCLUDED.config,
    sandbox_mode = EXCLUDED.sandbox_mode,
    allowlist_code = EXCLUDED.allowlist_code,
    secret_ref = EXCLUDED.secret_ref,
    signing_algorithm = EXCLUDED.signing_algorithm,
    allowed_target = EXCLUDED.allowed_target,
    updated_at = now();

