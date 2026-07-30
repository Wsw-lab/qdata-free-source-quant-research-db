-- Rollback Omega automation control metadata.

DROP TABLE IF EXISTS qmeta.automation_rollback CASCADE;
DROP TABLE IF EXISTS qmeta.automation_execution_attempt CASCADE;
DROP TABLE IF EXISTS qmeta.automation_approval CASCADE;
DROP TABLE IF EXISTS qmeta.automation_executor CASCADE;

ALTER TABLE IF EXISTS qmeta.automation_action
    DROP CONSTRAINT IF EXISTS automation_action_omega_control_status_check,
    DROP CONSTRAINT IF EXISTS automation_action_retry_count_check,
    DROP COLUMN IF EXISTS omega_control_status,
    DROP COLUMN IF EXISTS executor_code,
    DROP COLUMN IF EXISTS retry_count,
    DROP COLUMN IF EXISTS max_retry_count,
    DROP COLUMN IF EXISTS next_retry_at,
    DROP COLUMN IF EXISTS rollback_required,
    DROP COLUMN IF EXISTS rollback_plan;
