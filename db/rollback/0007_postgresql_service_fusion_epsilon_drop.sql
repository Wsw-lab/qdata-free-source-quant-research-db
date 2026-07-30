-- Roll back Epsilon service/fusion metadata only.
-- This does not touch existing market, PIT, pipeline, or matrix-export data.

DROP TABLE IF EXISTS qmeta.multi_source_quality_daily CASCADE;
DROP TABLE IF EXISTS qmeta.api_request_audit CASCADE;
DROP TABLE IF EXISTS qmeta.api_token CASCADE;
DROP TABLE IF EXISTS qmeta.data_conflict_daily CASCADE;
DROP TABLE IF EXISTS qmeta.source_priority CASCADE;
