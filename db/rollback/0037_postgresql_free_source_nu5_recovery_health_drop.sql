-- Rollback Nu-5 free source recovery health snapshots.

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'nu_free_source_recovery_health_15m';

DELETE FROM qmeta.worker_schedule_tick
WHERE task_name = 'free_source_recovery_health';

DELETE FROM qmeta.worker_task_run
WHERE task_name = 'free_source_recovery_health';

DELETE FROM qmeta.worker_run
WHERE task_filter @> ARRAY['free_source_recovery_health']::text[];

DROP TABLE IF EXISTS qmeta.free_source_recovery_health_snapshot CASCADE;

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
