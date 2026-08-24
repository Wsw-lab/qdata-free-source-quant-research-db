-- Preserve factor input-data vintages across ReplacingMergeTree merges.
--
-- This forward-only migration cannot recover versions already collapsed by
-- the old sorting key. Pause factor ingestion, run once on an Atomic database,
-- and retain the exchanged old-key table until row counts and vintages have
-- been audited independently.

SYSTEM STOP MERGES qts.factor_value_daily;

CREATE TABLE qts.factor_value_daily__0057_rebuild
(
    factor_id           UInt64,
    factor_version_id   UInt64,
    security_id         UInt64,
    trade_date          Date,
    factor_value        Nullable(Float64),
    universe_id         Nullable(UInt64),
    calc_time           DateTime64(3, 'Asia/Shanghai'),
    data_version        UInt64,
    quality_flag        LowCardinality(String)
)
ENGINE = ReplacingMergeTree(calc_time)
PARTITION BY toYYYYMM(trade_date)
ORDER BY (factor_id, trade_date, security_id, factor_version_id, data_version);

INSERT INTO qts.factor_value_daily__0057_rebuild
(
    factor_id, factor_version_id, security_id, trade_date, factor_value,
    universe_id, calc_time, data_version, quality_flag
)
SELECT
    factor_id, factor_version_id, security_id, trade_date, factor_value,
    universe_id, calc_time, data_version, quality_flag
FROM qts.factor_value_daily;

EXCHANGE TABLES qts.factor_value_daily AND qts.factor_value_daily__0057_rebuild;

SYSTEM STOP MERGES qts.factor_value_daily__0057_rebuild;
SYSTEM START MERGES qts.factor_value_daily;
