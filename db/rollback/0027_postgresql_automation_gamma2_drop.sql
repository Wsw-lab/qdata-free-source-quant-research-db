-- Rollback Gamma-2 automation provider profile and secret rotation tables.

DROP TABLE IF EXISTS qmeta.automation_secret_rotation CASCADE;
DROP TABLE IF EXISTS qmeta.automation_channel_validation CASCADE;
DROP TABLE IF EXISTS qmeta.automation_channel_profile CASCADE;

