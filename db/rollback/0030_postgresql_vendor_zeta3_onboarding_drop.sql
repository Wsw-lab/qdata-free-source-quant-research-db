-- Rollback Zeta-3 vendor onboarding operational tables.

DROP TABLE IF EXISTS qmeta.vendor_onboarding_dataset_result CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_onboarding_run CASCADE;
