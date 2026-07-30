-- 回滚 Nu 部署发布和健康巡检对象

DROP TABLE IF EXISTS qmeta.deployment_event CASCADE;
DROP TABLE IF EXISTS qmeta.deployment_health_check CASCADE;
ALTER TABLE IF EXISTS qmeta.deployment_release
    DROP CONSTRAINT IF EXISTS fk_deployment_release_health_snapshot;
DROP TABLE IF EXISTS qmeta.deployment_health_snapshot CASCADE;
DROP TABLE IF EXISTS qmeta.deployment_release CASCADE;
