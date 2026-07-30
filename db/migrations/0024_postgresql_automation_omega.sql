-- A 股量化数据平台 Omega：生产级自动化控制、审批、执行器、重试和回滚

ALTER TABLE qmeta.automation_action
    ADD COLUMN IF NOT EXISTS omega_control_status VARCHAR(32) NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS executor_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_retry_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rollback_required BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rollback_plan JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE qmeta.automation_action
    DROP CONSTRAINT IF EXISTS automation_action_omega_control_status_check,
    DROP CONSTRAINT IF EXISTS automation_action_retry_count_check;

ALTER TABLE qmeta.automation_action
    ADD CONSTRAINT automation_action_omega_control_status_check
        CHECK (omega_control_status IN (
            'none',
            'pending_approval',
            'approved',
            'rejected',
            'queued',
            'running',
            'success',
            'failed',
            'retry_scheduled',
            'rollback_required',
            'rolled_back'
        )),
    ADD CONSTRAINT automation_action_retry_count_check
        CHECK (retry_count >= 0 AND max_retry_count >= 0);

CREATE TABLE IF NOT EXISTS qmeta.automation_executor (
    executor_id                BIGSERIAL PRIMARY KEY,
    executor_code              VARCHAR(128) NOT NULL UNIQUE,
    executor_name              VARCHAR(220) NOT NULL,
    executor_type              VARCHAR(32) NOT NULL DEFAULT 'noop',
    action_type                VARCHAR(64) NOT NULL,
    safety_level               VARCHAR(24) NOT NULL DEFAULT 'medium',
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    requires_approval          BOOLEAN NOT NULL DEFAULT FALSE,
    max_retry_count            INTEGER NOT NULL DEFAULT 1,
    retry_backoff_seconds      INTEGER NOT NULL DEFAULT 60,
    timeout_seconds            INTEGER NOT NULL DEFAULT 30,
    endpoint_url               TEXT,
    command_name               VARCHAR(220),
    config                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (executor_type IN ('noop', 'webhook', 'script')),
    CHECK (action_type IN (
        'repair_data_quality',
        'degrade_vendor',
        'pause_product',
        'freeze_budget',
        'escalate_commercial',
        'review_access_policy',
        'review_budget',
        'rotate_token',
        'contact_owner',
        'notify_owner',
        'monitor'
    )),
    CHECK (safety_level IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('active', 'inactive', 'disabled')),
    CHECK (max_retry_count >= 0),
    CHECK (retry_backoff_seconds >= 0),
    CHECK (timeout_seconds >= 1)
);

CREATE INDEX IF NOT EXISTS idx_automation_executor_action
    ON qmeta.automation_executor(action_type, safety_level, status);

CREATE TABLE IF NOT EXISTS qmeta.automation_approval (
    approval_id                BIGSERIAL PRIMARY KEY,
    approval_code              VARCHAR(260) NOT NULL UNIQUE,
    automation_action_id       BIGINT NOT NULL REFERENCES qmeta.automation_action(automation_action_id) ON DELETE CASCADE,
    status                     VARCHAR(24) NOT NULL DEFAULT 'pending',
    requested_by               VARCHAR(128) NOT NULL,
    requested_reason           TEXT NOT NULL,
    requested_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at                 TIMESTAMPTZ,
    decided_by                 VARCHAR(128),
    decision_reason            TEXT,
    decided_at                 TIMESTAMPTZ,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
    CHECK ((status IN ('approved', 'rejected') AND decided_by IS NOT NULL AND decided_at IS NOT NULL) OR status NOT IN ('approved', 'rejected'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_automation_approval_pending_action
    ON qmeta.automation_approval(automation_action_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_automation_approval_status
    ON qmeta.automation_approval(status, requested_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.automation_execution_attempt (
    attempt_id                 BIGSERIAL PRIMARY KEY,
    attempt_code               VARCHAR(280) NOT NULL UNIQUE,
    automation_action_id       BIGINT NOT NULL REFERENCES qmeta.automation_action(automation_action_id) ON DELETE CASCADE,
    executor_id                BIGINT REFERENCES qmeta.automation_executor(executor_id) ON DELETE SET NULL,
    attempt_no                 INTEGER NOT NULL DEFAULT 1,
    trigger_mode               VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                     VARCHAR(32) NOT NULL DEFAULT 'queued',
    request_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    retry_count                INTEGER NOT NULL DEFAULT 0,
    max_retry_count            INTEGER NOT NULL DEFAULT 0,
    next_retry_at              TIMESTAMPTZ,
    started_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                TIMESTAMPTZ,
    duration_ms                INTEGER,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (automation_action_id, attempt_no),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (status IN ('queued', 'running', 'success', 'failed', 'skipped', 'approval_required', 'retry_scheduled')),
    CHECK (attempt_no >= 1),
    CHECK (retry_count >= 0 AND max_retry_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_automation_attempt_status
    ON qmeta.automation_execution_attempt(status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_automation_attempt_retry
    ON qmeta.automation_execution_attempt(next_retry_at, status)
    WHERE status = 'retry_scheduled';

CREATE TABLE IF NOT EXISTS qmeta.automation_rollback (
    rollback_id                BIGSERIAL PRIMARY KEY,
    rollback_code              VARCHAR(280) NOT NULL UNIQUE,
    automation_action_id       BIGINT NOT NULL REFERENCES qmeta.automation_action(automation_action_id) ON DELETE CASCADE,
    attempt_id                 BIGINT REFERENCES qmeta.automation_execution_attempt(attempt_id) ON DELETE SET NULL,
    rollback_type              VARCHAR(32) NOT NULL DEFAULT 'noop',
    status                     VARCHAR(24) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL,
    executed_by                VARCHAR(128),
    reason                     TEXT NOT NULL,
    rollback_plan              JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollback_result            JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_at                TIMESTAMPTZ,
    error_message              TEXT,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (rollback_type IN ('noop', 'manual', 'webhook', 'script')),
    CHECK (status IN ('planned', 'success', 'failed', 'skipped')),
    CHECK ((status IN ('success', 'failed', 'skipped') AND executed_by IS NOT NULL AND executed_at IS NOT NULL) OR status = 'planned')
);

CREATE INDEX IF NOT EXISTS idx_automation_rollback_status
    ON qmeta.automation_rollback(status, requested_at DESC);

INSERT INTO qmeta.automation_executor (
    executor_code, executor_name, executor_type, action_type, safety_level,
    requires_approval, max_retry_count, retry_backoff_seconds, timeout_seconds, config
) VALUES
    ('omega-noop-notify-owner', 'Omega noop notify owner', 'noop', 'notify_owner', 'medium', FALSE, 2, 60, 30, '{"operation":"notify_owner"}'::jsonb),
    ('omega-noop-escalate-commercial', 'Omega noop commercial escalation', 'noop', 'escalate_commercial', 'medium', FALSE, 2, 60, 30, '{"operation":"open_commercial_followup"}'::jsonb),
    ('omega-noop-contact-owner', 'Omega noop contact owner', 'noop', 'contact_owner', 'low', FALSE, 2, 60, 30, '{"operation":"record_owner_followup"}'::jsonb),
    ('omega-noop-monitor', 'Omega noop monitor', 'noop', 'monitor', 'low', FALSE, 1, 60, 30, '{"operation":"monitor"}'::jsonb),
    ('omega-noop-review-budget', 'Omega noop budget review', 'noop', 'review_budget', 'medium', FALSE, 2, 60, 30, '{"operation":"open_budget_review"}'::jsonb),
    ('omega-noop-review-access-policy', 'Omega noop access policy review', 'noop', 'review_access_policy', 'medium', FALSE, 2, 60, 30, '{"operation":"open_access_policy_review"}'::jsonb),
    ('omega-noop-repair-data-quality', 'Omega guarded data quality repair', 'noop', 'repair_data_quality', 'high', TRUE, 1, 120, 30, '{"operation":"enqueue_repair_guarded"}'::jsonb),
    ('omega-noop-degrade-vendor', 'Omega guarded vendor degradation', 'noop', 'degrade_vendor', 'high', TRUE, 1, 120, 30, '{"operation":"degrade_vendor_guarded"}'::jsonb),
    ('omega-noop-freeze-budget', 'Omega guarded budget freeze', 'noop', 'freeze_budget', 'high', TRUE, 1, 120, 30, '{"operation":"freeze_budget_guarded"}'::jsonb),
    ('omega-noop-rotate-token', 'Omega guarded token rotation', 'noop', 'rotate_token', 'high', TRUE, 1, 120, 30, '{"operation":"rotate_token_guarded"}'::jsonb),
    ('omega-noop-pause-product', 'Omega guarded product pause', 'noop', 'pause_product', 'critical', TRUE, 1, 300, 30, '{"operation":"pause_product_guarded"}'::jsonb)
ON CONFLICT (executor_code) DO UPDATE SET
    executor_name = EXCLUDED.executor_name,
    executor_type = EXCLUDED.executor_type,
    action_type = EXCLUDED.action_type,
    safety_level = EXCLUDED.safety_level,
    requires_approval = EXCLUDED.requires_approval,
    max_retry_count = EXCLUDED.max_retry_count,
    retry_backoff_seconds = EXCLUDED.retry_backoff_seconds,
    timeout_seconds = EXCLUDED.timeout_seconds,
    config = EXCLUDED.config,
    status = 'active',
    updated_at = now();

