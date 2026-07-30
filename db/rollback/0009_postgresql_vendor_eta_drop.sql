-- Roll back Eta vendor integration and benchmark metadata only.

DROP TABLE IF EXISTS qmeta.vendor_quality_score_daily CASCADE;
DROP TABLE IF EXISTS qmeta.provider_benchmark_run CASCADE;
DROP TABLE IF EXISTS qmeta.provider_error_event CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_integration_profile CASCADE;
