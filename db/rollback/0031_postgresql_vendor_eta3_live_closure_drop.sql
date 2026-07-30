-- Rollback Eta-3 vendor live closure operational tables.

DROP TABLE IF EXISTS qmeta.vendor_live_endpoint_probe CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_live_closure_run CASCADE;
