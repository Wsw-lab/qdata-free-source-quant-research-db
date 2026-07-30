-- Rollback Mu-5 free source recovery execution loop.

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'mu_free_source_recovery_execute_30m';

DELETE FROM qmeta.worker_schedule_tick
WHERE task_name = 'free_source_recovery_execute';

DELETE FROM qmeta.worker_task_run
WHERE task_name = 'free_source_recovery_execute';

DELETE FROM qmeta.worker_run
WHERE task_filter @> ARRAY['free_source_recovery_execute']::text[];

DROP TABLE IF EXISTS qmeta.free_source_recovery_execution CASCADE;

UPDATE qmeta.free_source_recovery_action
SET status = CASE
        WHEN status = 'recovered' THEN 'success'
        WHEN status IN ('review_requested', 'notified', 'blocked') THEN 'review_required'
        ELSE status
    END,
    updated_at = now()
WHERE status IN ('recovered', 'review_requested', 'notified', 'blocked');

ALTER TABLE qmeta.free_source_recovery_action
    DROP CONSTRAINT IF EXISTS free_source_recovery_action_status_check;

ALTER TABLE qmeta.free_source_recovery_action
    ADD CONSTRAINT free_source_recovery_action_status_check
    CHECK (status IN ('planned', 'skipped', 'scheduled', 'alerted', 'review_required', 'suppressed', 'failed', 'success'));

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery'));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery'));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery'));
