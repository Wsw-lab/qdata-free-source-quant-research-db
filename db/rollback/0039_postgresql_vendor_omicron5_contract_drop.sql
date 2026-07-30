-- Roll back Omicron-5 vendor contract procurement readiness.

DELETE FROM qmeta.worker_schedule_tick
WHERE task_name = 'vendor_contract_readiness_review';

DELETE FROM qmeta.worker_task_run
WHERE task_name = 'vendor_contract_readiness_review';

DELETE FROM qmeta.worker_schedule
WHERE task_name = 'vendor_contract_readiness_review'
   OR schedule_code = 'omicron5_vendor_contract_readiness_6h';

DROP TABLE IF EXISTS qmeta.vendor_procurement_readiness_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_contract_dataset_entitlement CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_contract_profile CASCADE;

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review'
    ));
