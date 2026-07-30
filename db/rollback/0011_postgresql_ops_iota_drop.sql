-- 回滚 Iota 生产通知、租户权限、用量计量和供应商压测调度对象

DROP TABLE IF EXISTS qmeta.vendor_benchmark_schedule CASCADE;
DROP TABLE IF EXISTS qmeta.alert_notification_delivery CASCADE;
DROP TABLE IF EXISTS qmeta.notification_channel CASCADE;
DROP TABLE IF EXISTS qmeta.api_usage_daily CASCADE;
DROP TABLE IF EXISTS qmeta.dataset_access_policy CASCADE;
DROP TABLE IF EXISTS qmeta.project_member CASCADE;
DROP TABLE IF EXISTS qmeta.principal CASCADE;
DROP TABLE IF EXISTS qmeta.project CASCADE;
DROP TABLE IF EXISTS qmeta.tenant CASCADE;

ALTER TABLE qmeta.api_request_audit
    DROP COLUMN IF EXISTS cost_units,
    DROP COLUMN IF EXISTS principal_id,
    DROP COLUMN IF EXISTS project_id,
    DROP COLUMN IF EXISTS tenant_id;

ALTER TABLE qmeta.api_token
    DROP COLUMN IF EXISTS cost_center,
    DROP COLUMN IF EXISTS principal_id,
    DROP COLUMN IF EXISTS project_id,
    DROP COLUMN IF EXISTS tenant_id;
