-- Gamma-6: writable route incident approval API, quorum signatures and console actions.

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_command (
    command_id                       BIGSERIAL PRIMARY KEY,
    command_code                     VARCHAR(180) NOT NULL UNIQUE,
    idempotency_key                  VARCHAR(220) NOT NULL UNIQUE,
    requested_by                     VARCHAR(128) NOT NULL,
    principal_code                   VARCHAR(128) NOT NULL,
    trigger_mode                     VARCHAR(32) NOT NULL DEFAULT 'api',
    decision                         VARCHAR(16) NOT NULL,
    status                           VARCHAR(24) NOT NULL DEFAULT 'pending_quorum',
    command_scope                    VARCHAR(16) NOT NULL DEFAULT 'single',
    batch_code                       VARCHAR(180),
    control_code                     VARCHAR(280),
    approval_code                    VARCHAR(260),
    required_approvals               INTEGER NOT NULL DEFAULT 1,
    approval_count                   INTEGER NOT NULL DEFAULT 0,
    duplicate_count                  INTEGER NOT NULL DEFAULT 0,
    target_count                     INTEGER NOT NULL DEFAULT 0,
    applied_count                    INTEGER NOT NULL DEFAULT 0,
    held_count                       INTEGER NOT NULL DEFAULT 0,
    rejected_count                   INTEGER NOT NULL DEFAULT 0,
    skipped_count                    INTEGER NOT NULL DEFAULT 0,
    failed_count                     INTEGER NOT NULL DEFAULT 0,
    quorum_status                    VARCHAR(24) NOT NULL DEFAULT 'pending',
    notify_wecom                     BOOLEAN NOT NULL DEFAULT FALSE,
    allow_wecom_external             BOOLEAN NOT NULL DEFAULT FALSE,
    response_payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    command_issues                   TEXT[] NOT NULL DEFAULT '{}',
    error_message                    TEXT,
    started_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                      TIMESTAMPTZ,
    duration_ms                      INTEGER,
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('api', 'manual', 'smoke')),
    CHECK (decision IN ('approve', 'reject', 'hold')),
    CHECK (status IN ('pending_quorum', 'applied', 'skipped', 'failed')),
    CHECK (command_scope IN ('single', 'batch')),
    CHECK (quorum_status IN ('not_required', 'pending', 'met')),
    CHECK (required_approvals BETWEEN 1 AND 5),
    CHECK (approval_count >= 0),
    CHECK (duplicate_count >= 0),
    CHECK (target_count >= 0),
    CHECK (applied_count >= 0),
    CHECK (held_count >= 0),
    CHECK (rejected_count >= 0),
    CHECK (skipped_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_command_item (
    item_id                          BIGSERIAL PRIMARY KEY,
    command_id                       BIGINT NOT NULL REFERENCES qmeta.source_route_incident_approval_command(command_id) ON DELETE CASCADE,
    command_code                     VARCHAR(180) NOT NULL,
    control_id                       BIGINT REFERENCES qmeta.source_route_incident_control(control_id) ON DELETE SET NULL,
    approval_id                      BIGINT REFERENCES qmeta.automation_approval(approval_id) ON DELETE SET NULL,
    control_code                     VARCHAR(280),
    approval_code                    VARCHAR(260),
    incident_action_code             VARCHAR(280),
    dataset_code                     VARCHAR(128),
    source_code                      VARCHAR(128),
    source_signal_type               VARCHAR(64),
    safety_level                     VARCHAR(24),
    decision                         VARCHAR(16) NOT NULL,
    item_status                      VARCHAR(24) NOT NULL DEFAULT 'pending_quorum',
    approval_status_before           VARCHAR(24),
    approval_status_after            VARCHAR(24),
    control_stage_before             VARCHAR(32),
    control_stage_after              VARCHAR(32),
    signer_code                      VARCHAR(128),
    signature_count                  INTEGER NOT NULL DEFAULT 0,
    required_approvals               INTEGER NOT NULL DEFAULT 1,
    idempotency_key                  VARCHAR(220) NOT NULL,
    evidence                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                    TEXT,
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (command_id, control_id),
    CHECK (decision IN ('approve', 'reject', 'hold')),
    CHECK (item_status IN ('pending_quorum', 'applied', 'held', 'skipped', 'failed')),
    CHECK (signature_count >= 0),
    CHECK (required_approvals BETWEEN 1 AND 5)
);

CREATE TABLE IF NOT EXISTS qmeta.source_route_incident_approval_signature (
    signature_id                     BIGSERIAL PRIMARY KEY,
    signature_code                   VARCHAR(220) NOT NULL UNIQUE,
    command_id                       BIGINT REFERENCES qmeta.source_route_incident_approval_command(command_id) ON DELETE SET NULL,
    control_id                       BIGINT NOT NULL REFERENCES qmeta.source_route_incident_control(control_id) ON DELETE CASCADE,
    approval_id                      BIGINT REFERENCES qmeta.automation_approval(approval_id) ON DELETE SET NULL,
    control_code                     VARCHAR(280),
    approval_code                    VARCHAR(260),
    decision                         VARCHAR(16) NOT NULL,
    signer_code                      VARCHAR(128) NOT NULL,
    idempotency_key                  VARCHAR(220) NOT NULL UNIQUE,
    status                           VARCHAR(24) NOT NULL DEFAULT 'active',
    evidence                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    signed_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (control_id, decision, signer_code),
    CHECK (decision IN ('approve', 'reject', 'hold')),
    CHECK (status IN ('active', 'superseded', 'duplicate', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_approval_command_lookup
    ON qmeta.source_route_incident_approval_command(started_at DESC, status, decision, quorum_status);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_approval_command_target
    ON qmeta.source_route_incident_approval_command(control_code, approval_code, batch_code, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_approval_item_target
    ON qmeta.source_route_incident_approval_command_item(control_code, approval_code, item_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_route_incident_approval_signature_lookup
    ON qmeta.source_route_incident_approval_signature(control_code, approval_code, decision, signer_code, signed_at DESC);

