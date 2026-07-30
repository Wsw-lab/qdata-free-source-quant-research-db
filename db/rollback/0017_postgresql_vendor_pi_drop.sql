-- Roll back Pi vendor readiness review metadata.

DROP TABLE IF EXISTS qmeta.vendor_readiness_window CASCADE;
DROP TABLE IF EXISTS qmeta.vendor_readiness_review CASCADE;
