-- Rollback Psi automation metadata.
-- This removes only Psi execution audit tables and does not undo source business data.

DROP TABLE IF EXISTS qmeta.automation_action CASCADE;
DROP TABLE IF EXISTS qmeta.automation_run CASCADE;

