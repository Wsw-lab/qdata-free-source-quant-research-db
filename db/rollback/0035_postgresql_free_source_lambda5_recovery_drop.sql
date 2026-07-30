-- Rollback Lambda-5 free source recovery orchestration.

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'mu_free_source_recovery_30m';

DELETE FROM qmeta.worker_schedule_tick
WHERE task_name = 'free_source_recovery';

DELETE FROM qmeta.worker_run
WHERE task_filter @> ARRAY['free_source_recovery']::text[];

DROP TABLE IF EXISTS qmeta.free_source_recovery_action CASCADE;
DROP TABLE IF EXISTS qmeta.free_source_recovery_run CASCADE;

DELETE FROM qmeta.alert_notification_delivery d
USING qmeta.alert_event ae
WHERE d.alert_id = ae.alert_id
  AND ae.alert_type = 'free_source_recovery_required';

DELETE FROM qmeta.alert_event
WHERE alert_type = 'free_source_recovery_required';

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule'));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule'));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule'));

ALTER TABLE qmeta.alert_event
    DROP CONSTRAINT IF EXISTS alert_event_alert_type_check;

ALTER TABLE qmeta.alert_event
    ADD CONSTRAINT alert_event_alert_type_check
    CHECK (alert_type IN (
        'missing_run',
        'pipeline_status',
        'pipeline_late',
        'completeness_below_sla',
        'conflict_rate_above_sla',
        'api_error_rate_above_sla',
        'duration_above_sla',
        'vendor_score_below_sla',
        'vendor_conflict_rate_above_sla',
        'vendor_failure_rate_above_sla',
        'vendor_latency_above_sla',
        'provider_error_count_above_sla',
        'budget_threshold_warning',
        'budget_exceeded',
        'budget_blocked',
        'budget_usage_spike',
        'runtime_metric_warning',
        'runtime_metric_critical',
        'runtime_capacity_warning',
        'runtime_capacity_critical',
        'runtime_daily_degraded'
    ));
