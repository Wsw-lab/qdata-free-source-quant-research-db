-- Rollback Alpha-2 automation sandbox metadata.

DELETE FROM qmeta.automation_executor
WHERE executor_code IN ('alpha2-webhook-notify-owner', 'alpha2-script-notify-owner');

DROP TABLE IF EXISTS qmeta.automation_secret_ref CASCADE;
DROP TABLE IF EXISTS qmeta.automation_executor_allowlist CASCADE;

ALTER TABLE IF EXISTS qmeta.automation_executor
    DROP CONSTRAINT IF EXISTS automation_executor_signing_algorithm_check,
    DROP COLUMN IF EXISTS sandbox_mode,
    DROP COLUMN IF EXISTS allowlist_code,
    DROP COLUMN IF EXISTS secret_ref,
    DROP COLUMN IF EXISTS signing_algorithm,
    DROP COLUMN IF EXISTS allowed_target;
