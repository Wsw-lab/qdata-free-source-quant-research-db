-- A 股量化数据平台 Mu-5：免费源恢复执行、审批通知和结果回写

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery', 'free_source_recovery_execute'));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery', 'free_source_recovery_execute'));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery', 'free_source_recovery_execute'));

ALTER TABLE qmeta.free_source_recovery_action
    DROP CONSTRAINT IF EXISTS free_source_recovery_action_status_check;

ALTER TABLE qmeta.free_source_recovery_action
    ADD CONSTRAINT free_source_recovery_action_status_check
    CHECK (status IN (
        'planned',
        'skipped',
        'scheduled',
        'alerted',
        'review_required',
        'review_requested',
        'notified',
        'recovered',
        'suppressed',
        'failed',
        'success',
        'blocked'
    ));

CREATE TABLE IF NOT EXISTS qmeta.free_source_recovery_execution (
    execution_id                  BIGSERIAL PRIMARY KEY,
    execution_code                VARCHAR(180) NOT NULL UNIQUE,
    action_id                     BIGINT NOT NULL REFERENCES qmeta.free_source_recovery_action(action_id) ON DELETE CASCADE,
    recovery_run_id               BIGINT REFERENCES qmeta.free_source_recovery_run(recovery_run_id) ON DELETE SET NULL,
    execution_type                VARCHAR(32) NOT NULL,
    trigger_mode                  VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                        VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by                  VARCHAR(128) NOT NULL DEFAULT 'mu5',
    environment                   VARCHAR(32) NOT NULL DEFAULT 'local',
    dry_run                       BOOLEAN NOT NULL DEFAULT FALSE,
    source_id                     BIGINT REFERENCES qmeta.source_system(source_id),
    dataset_id                    BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    fabric_id                     BIGINT REFERENCES qmeta.free_source_fabric_run(fabric_id) ON DELETE SET NULL,
    fabric_code                   VARCHAR(180),
    iota5_pool_status             VARCHAR(32),
    automation_run_id             BIGINT REFERENCES qmeta.automation_run(automation_run_id) ON DELETE SET NULL,
    automation_action_id          BIGINT REFERENCES qmeta.automation_action(automation_action_id) ON DELETE SET NULL,
    approval_id                   BIGINT REFERENCES qmeta.automation_approval(approval_id) ON DELETE SET NULL,
    approval_code                 VARCHAR(260),
    wecom_receipt_id              BIGINT REFERENCES qmeta.automation_live_provider_receipt(receipt_id) ON DELETE SET NULL,
    wecom_receipt_code            VARCHAR(180),
    result_summary                JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                 TEXT,
    started_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                   TIMESTAMPTZ,
    duration_ms                   INTEGER,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (execution_type IN ('retry_canary', 'manual_review', 'observe', 'suppress')),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('planned', 'running', 'recovered', 'failed', 'suppressed', 'review_requested', 'notified', 'blocked', 'skipped')),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_lookup
    ON qmeta.free_source_recovery_execution(started_at DESC, status, execution_type);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_action
    ON qmeta.free_source_recovery_execution(action_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_source_dataset
    ON qmeta.free_source_recovery_execution(source_id, dataset_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_approval
    ON qmeta.free_source_recovery_execution(approval_code);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_wecom
    ON qmeta.free_source_recovery_execution(wecom_receipt_code);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'mu_free_source_recovery_execute_30m', 'free_source_recovery_execute', 1800, 900, 900, 300,
    '{"mu5_max_actions":20,"mu5_start_date":"2024-01-04","mu5_end_date":"2024-01-04","mu5_execute_retry_canary":true,"mu5_request_manual_review":true,"mu5_notify_wecom":true,"mu5_allow_wecom_external":false,"mu5_baostock_timeout_seconds":3.0}'::jsonb,
    '{"owner":"mu5","purpose":"execute Lambda-5 retry canary and manual-review recovery actions with audit writeback"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;
