-- 回滚 Theta 供应商生产化、全市场压测和上线决策对象

DROP TABLE IF EXISTS qmeta.vendor_decision_report CASCADE;
DROP TABLE IF EXISTS qmeta.provider_benchmark_suite_run CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_field_mapping CASCADE;

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
        'duration_above_sla'
    ));

ALTER TABLE qmeta.sla_policy
    DROP CONSTRAINT IF EXISTS chk_sla_policy_theta_vendor_thresholds,
    DROP COLUMN IF EXISTS min_vendor_score,
    DROP COLUMN IF EXISTS max_vendor_conflict_rate,
    DROP COLUMN IF EXISTS max_vendor_failure_rate,
    DROP COLUMN IF EXISTS max_vendor_latency_ms,
    DROP COLUMN IF EXISTS max_provider_error_count;
