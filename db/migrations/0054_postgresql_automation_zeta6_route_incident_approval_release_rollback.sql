-- Roll back Zeta-6 route incident approval release artifacts.

DELETE FROM qmeta.worker_schedule
WHERE schedule_code = 'zeta6_route_incident_approval_release_30m';

DROP TABLE IF EXISTS qmeta.source_route_incident_approval_audit_export CASCADE;
DROP TABLE IF EXISTS qmeta.source_route_incident_approval_concurrency_test CASCADE;
DROP TABLE IF EXISTS qmeta.source_route_incident_approval_secret_rotation CASCADE;
DROP TABLE IF EXISTS qmeta.source_route_incident_approval_release_preflight CASCADE;

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
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer',
        'vendor_route_weight_executor',
        'source_route_feedback_monitor',
        'route_incident_automation',
        'route_incident_control',
        'route_incident_control_health',
        'route_incident_operations',
        'route_incident_approval_governance',
        'route_incident_approval_resilience'
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
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer',
        'vendor_route_weight_executor',
        'source_route_feedback_monitor',
        'route_incident_automation',
        'route_incident_control',
        'route_incident_control_health',
        'route_incident_operations',
        'route_incident_approval_governance',
        'route_incident_approval_resilience'
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
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer',
        'vendor_route_weight_executor',
        'source_route_feedback_monitor',
        'route_incident_automation',
        'route_incident_control',
        'route_incident_control_health',
        'route_incident_operations',
        'route_incident_approval_governance',
        'route_incident_approval_resilience'
    ));
