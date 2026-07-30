-- Rollback Sigma runtime observability metadata.

DROP TABLE IF EXISTS qmeta.capacity_alert CASCADE;
DROP TABLE IF EXISTS qmeta.runtime_daily_report CASCADE;
DROP TABLE IF EXISTS qmeta.runtime_metric_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.runtime_log CASCADE;

DELETE FROM qmeta.alert_notification_delivery d
USING qmeta.alert_event ae
WHERE d.alert_id = ae.alert_id
  AND ae.alert_type IN (
      'runtime_metric_warning',
      'runtime_metric_critical',
      'runtime_capacity_warning',
      'runtime_capacity_critical',
      'runtime_daily_degraded'
  );

DELETE FROM qmeta.alert_event
WHERE alert_type IN (
    'runtime_metric_warning',
    'runtime_metric_critical',
    'runtime_capacity_warning',
    'runtime_capacity_critical',
    'runtime_daily_degraded'
);

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
        'budget_usage_spike'
    ));
