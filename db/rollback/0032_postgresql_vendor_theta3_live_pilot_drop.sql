-- Rollback Theta-3 vendor live pilot operational tables.

DROP TABLE IF EXISTS qmeta.vendor_live_pilot_dataset_result CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_live_pilot_run CASCADE;
