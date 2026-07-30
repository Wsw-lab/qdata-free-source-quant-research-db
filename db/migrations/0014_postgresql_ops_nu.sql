-- A 股量化数据平台 Nu：部署发布、健康快照和巡检明细

CREATE TABLE IF NOT EXISTS qmeta.deployment_release (
    release_id          BIGSERIAL PRIMARY KEY,
    release_code        VARCHAR(160) NOT NULL UNIQUE,
    release_name        VARCHAR(160) NOT NULL,
    environment         VARCHAR(64) NOT NULL DEFAULT 'local',
    version_label       VARCHAR(128),
    git_ref             VARCHAR(160),
    status              VARCHAR(32) NOT NULL DEFAULT 'planned',
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    health_snapshot_id  BIGINT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('planned', 'deploying', 'healthy', 'degraded', 'failed', 'rolled_back')),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_deployment_release_env_status
    ON qmeta.deployment_release(environment, status, created_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.deployment_health_snapshot (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    snapshot_code       VARCHAR(180) NOT NULL UNIQUE,
    release_id          BIGINT REFERENCES qmeta.deployment_release(release_id) ON DELETE SET NULL,
    environment         VARCHAR(64) NOT NULL DEFAULT 'local',
    status              VARCHAR(32) NOT NULL,
    checked_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms         BIGINT NOT NULL DEFAULT 0,
    check_count         INTEGER NOT NULL DEFAULT 0,
    success_count       INTEGER NOT NULL DEFAULT 0,
    warning_count       INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('success', 'warning', 'failed')),
    CHECK (duration_ms >= 0),
    CHECK (check_count >= 0),
    CHECK (success_count >= 0),
    CHECK (warning_count >= 0),
    CHECK (failed_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_deployment_health_snapshot_env_checked
    ON qmeta.deployment_health_snapshot(environment, checked_at DESC, status);

ALTER TABLE qmeta.deployment_release
    DROP CONSTRAINT IF EXISTS fk_deployment_release_health_snapshot;

ALTER TABLE qmeta.deployment_release
    ADD CONSTRAINT fk_deployment_release_health_snapshot
    FOREIGN KEY (health_snapshot_id)
    REFERENCES qmeta.deployment_health_snapshot(snapshot_id)
    ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS qmeta.deployment_health_check (
    health_check_id     BIGSERIAL PRIMARY KEY,
    snapshot_id         BIGINT NOT NULL REFERENCES qmeta.deployment_health_snapshot(snapshot_id) ON DELETE CASCADE,
    check_name          VARCHAR(128) NOT NULL,
    component           VARCHAR(64) NOT NULL,
    status              VARCHAR(32) NOT NULL,
    duration_ms         BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (component IN ('postgres', 'clickhouse', 'api', 'scheduler', 'kappa', 'docker', 'migration', 'release')),
    CHECK (status IN ('success', 'warning', 'failed', 'skipped')),
    CHECK (duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_deployment_health_check_snapshot_status
    ON qmeta.deployment_health_check(snapshot_id, status, component);

CREATE TABLE IF NOT EXISTS qmeta.deployment_event (
    event_id            BIGSERIAL PRIMARY KEY,
    release_id          BIGINT REFERENCES qmeta.deployment_release(release_id) ON DELETE SET NULL,
    event_code          VARCHAR(180) NOT NULL UNIQUE,
    environment         VARCHAR(64) NOT NULL DEFAULT 'local',
    event_type          VARCHAR(64) NOT NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'success',
    message             TEXT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (event_type IN ('deploy_start', 'deploy_finish', 'health_check', 'rollback_start', 'rollback_finish', 'manual_note')),
    CHECK (status IN ('success', 'warning', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_deployment_event_env_created
    ON qmeta.deployment_event(environment, created_at DESC, event_type);
