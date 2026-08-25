-- Preserve contradictory factor rows so the read path can fail closed.
--
-- ReplacingMergeTree(calc_time) can physically discard one of two rows that
-- share the same factor/version/security/date/data_version/calc_time key.  Once
-- discarded, a reader cannot prove that a conflict existed.  This forward-only
-- create-copy-exchange migration changes the canonical factor table to plain
-- MergeTree while retaining the durable data_version sorting key from 0057.
--
-- Operational requirements:
--   * pause factor ingestion for the duration of this script;
--   * run exactly once against an Atomic qts database, after 0057;
--   * retain the exchanged __0062_rebuild table until row counts, checksums,
--     and representative duplicate/conflict groups have been audited;
--   * if execution stops before EXCHANGE, resume merges on the source before
--     returning ingestion to service.
--
-- Rows already removed by an earlier ReplacingMergeTree merge cannot be
-- recovered here; restore those from upstream/raw snapshots when required.

SYSTEM STOP MERGES qts.factor_value_daily;

CREATE TABLE qts.factor_value_daily__0062_rebuild
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
ENGINE = MergeTree
PARTITION BY toYYYYMM(trade_date)
ORDER BY (factor_id, trade_date, security_id, factor_version_id, data_version);

INSERT INTO qts.factor_value_daily__0062_rebuild
(
    factor_id, factor_version_id, security_id, trade_date, factor_value,
    universe_id, calc_time, data_version, quality_flag
)
SELECT
    factor_id, factor_version_id, security_id, trade_date, factor_value,
    universe_id, calc_time, data_version, quality_flag
FROM qts.factor_value_daily;

EXCHANGE TABLES qts.factor_value_daily AND qts.factor_value_daily__0062_rebuild;

SYSTEM STOP MERGES qts.factor_value_daily__0062_rebuild;
SYSTEM START MERGES qts.factor_value_daily;
