-- A 股量化数据平台 Psi：决策自动化执行队列、护栏和执行审计

CREATE TABLE IF NOT EXISTS qmeta.automation_run (
    automation_run_id          BIGSERIAL PRIMARY KEY,
    run_code                   VARCHAR(220) NOT NULL UNIQUE,
    run_date                   DATE NOT NULL,
    environment                VARCHAR(64) NOT NULL DEFAULT 'local',
    trigger_mode               VARCHAR(32) NOT NULL DEFAULT 'manual',
    execution_mode             VARCHAR(24) NOT NULL DEFAULT 'dry_run',
    status                     VARCHAR(24) NOT NULL DEFAULT 'running',
    source_filter              JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_count               INTEGER NOT NULL DEFAULT 0,
    executable_count           INTEGER NOT NULL DEFAULT 0,
    executed_count             INTEGER NOT NULL DEFAULT 0,
    approval_required_count    INTEGER NOT NULL DEFAULT 0,
    skipped_count              INTEGER NOT NULL DEFAULT 0,
    failed_count               INTEGER NOT NULL DEFAULT 0,
    started_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                TIMESTAMPTZ,
    duration_ms                INTEGER,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (execution_mode IN ('dry_run', 'execute')),
    CHECK (status IN ('running', 'success', 'warning', 'failed', 'skipped')),
    CHECK (action_count >= 0),
    CHECK (executable_count >= 0),
    CHECK (executed_count >= 0),
    CHECK (approval_required_count >= 0),
    CHECK (skipped_count >= 0),
    CHECK (failed_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_automation_run_lookup
    ON qmeta.automation_run(environment, run_date DESC, execution_mode, status);

CREATE TABLE IF NOT EXISTS qmeta.automation_action (
    automation_action_id       BIGSERIAL PRIMARY KEY,
    action_code                VARCHAR(260) NOT NULL UNIQUE,
    automation_run_id          BIGINT NOT NULL REFERENCES qmeta.automation_run(automation_run_id) ON DELETE CASCADE,
    source_type                VARCHAR(32) NOT NULL,
    source_id                  BIGINT,
    source_code                VARCHAR(260) NOT NULL,
    tenant_id                  BIGINT REFERENCES qmeta.tenant(tenant_id) ON DELETE SET NULL,
    project_id                 BIGINT REFERENCES qmeta.project(project_id) ON DELETE SET NULL,
    principal_id               BIGINT REFERENCES qmeta.principal(principal_id) ON DELETE SET NULL,
    token_id                   BIGINT REFERENCES qmeta.api_token(token_id) ON DELETE SET NULL,
    dataset_id                 BIGINT REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE SET NULL,
    action_type                VARCHAR(64) NOT NULL,
    safety_level               VARCHAR(24) NOT NULL DEFAULT 'medium',
    execution_mode             VARCHAR(24) NOT NULL DEFAULT 'dry_run',
    status                     VARCHAR(24) NOT NULL DEFAULT 'planned',
    approval_required          BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by                VARCHAR(128),
    approved_at                TIMESTAMPTZ,
    owner                      VARCHAR(128),
    reason                     TEXT NOT NULL,
    idempotency_key            VARCHAR(260) NOT NULL,
    planned_effect             JSONB NOT NULL DEFAULT '{}'::jsonb,
    executed_effect            JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollback_hint              TEXT,
    error_message              TEXT,
    executed_at                TIMESTAMPTZ,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (automation_run_id, idempotency_key),
    CHECK (source_type IN ('phi_decision', 'chi_governance_action', 'manual')),
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
    CHECK (execution_mode IN ('dry_run', 'execute')),
    CHECK (status IN ('planned', 'approval_required', 'success', 'failed', 'skipped')),
    CHECK ((approved_by IS NULL AND approved_at IS NULL) OR approval_required = TRUE)
);

CREATE INDEX IF NOT EXISTS idx_automation_action_status
    ON qmeta.automation_action(status, safety_level, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_automation_action_source
    ON qmeta.automation_action(source_type, source_code, action_type);

CREATE INDEX IF NOT EXISTS idx_automation_action_project
    ON qmeta.automation_action(project_id, status, updated_at DESC);

