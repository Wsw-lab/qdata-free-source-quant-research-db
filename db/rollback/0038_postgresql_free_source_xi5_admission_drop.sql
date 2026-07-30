-- Roll back Xi-5 free source admission matrix.

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'xi_free_source_admission_review_6h';

DROP TABLE IF EXISTS qmeta.free_source_admission_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.free_source_admission_profile CASCADE;

ALTER TABLE IF EXISTS qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE IF EXISTS qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health'
    ));

ALTER TABLE IF EXISTS qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE IF EXISTS qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health'
    ));

ALTER TABLE IF EXISTS qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE IF EXISTS qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health'
    ));
