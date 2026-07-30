-- Roll back Xi product catalog, pricing, subscription and budget metadata.
-- This removes only 0015 objects. It keeps Iota API usage/audit and older business data.

DROP TABLE IF EXISTS qmeta.budget_alert CASCADE;
DROP TABLE IF EXISTS qmeta.budget_usage_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.budget_policy CASCADE;
DROP TABLE IF EXISTS qmeta.product_subscription CASCADE;
DROP TABLE IF EXISTS qmeta.pricing_rule CASCADE;
DROP TABLE IF EXISTS qmeta.pricing_plan CASCADE;
DROP TABLE IF EXISTS qmeta.data_product_api CASCADE;
DROP TABLE IF EXISTS qmeta.data_product_dataset CASCADE;
DROP TABLE IF EXISTS qmeta.data_product CASCADE;

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
        'provider_error_count_above_sla'
    ));
