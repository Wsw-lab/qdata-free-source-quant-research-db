-- Rollback Beta-2 automation external integration control layer.

DROP TABLE IF EXISTS qmeta.automation_external_dispatch CASCADE;
DROP TABLE IF EXISTS qmeta.automation_external_channel CASCADE;
DROP TABLE IF EXISTS qmeta.automation_recovery_runbook CASCADE;
