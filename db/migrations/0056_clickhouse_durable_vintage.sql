-- Make market-data vintages durable across ReplacingMergeTree background merges.
--
-- ClickHouse 24.8 does not permit an existing data_version column, or a newly
-- added DEFAULT/MATERIALIZED alias of it, to be appended with MODIFY ORDER BY.
-- Existing tables therefore require a create-copy-exchange migration.
--
-- Operational requirements:
--   * pause daily/minute ingestion for the duration of this script;
--   * run this migration exactly once against an Atomic qts database;
--   * audit both canonical and __0056_rebuild tables after each EXCHANGE.
--
-- EXCHANGE TABLES is atomic.  After each exchange the canonical name points to
-- the new durable table, while __0056_rebuild points to the complete old table
-- and remains available as an audit/rollback copy.  Do not drop that copy until
-- row counts and representative vintages have been independently verified.
-- Both source merges are stopped before any rebuild DDL/DML, the old-key backup
-- remains stopped after exchange, and merges are explicitly enabled on the new
-- canonical table.
-- If this script aborts before an EXCHANGE, resume merges on that source table
-- before returning ingestion to service.
--
-- IMPORTANT: versions already removed by an old-key merge cannot be recovered
-- by this migration and must be restored from upstream/raw snapshots.

SYSTEM STOP MERGES qts.daily_bar;
SYSTEM STOP MERGES qts.minute_bar;

CREATE TABLE qts.daily_bar__0056_rebuild
(
    security_id     UInt64,
    trade_date      Date,
    open            Nullable(Float64),
    high            Nullable(Float64),
    low             Nullable(Float64),
    close           Nullable(Float64),
    pre_close       Nullable(Float64),
    volume          Nullable(Float64),
    amount          Nullable(Float64),
    vwap            Nullable(Float64),
    turnover_rate   Nullable(Float64),
    limit_up        Nullable(Float64),
    limit_down      Nullable(Float64),
    is_suspended    UInt8,
    source_id       UInt64,
    batch_id        UInt64,
    data_version    UInt64,
    ingest_time     DateTime64(3, 'Asia/Shanghai'),
    quality_flag    LowCardinality(String)
)
ENGINE = ReplacingMergeTree(ingest_time)
PARTITION BY toYYYYMM(trade_date)
ORDER BY (security_id, trade_date, data_version);

INSERT INTO qts.daily_bar__0056_rebuild
(
    security_id, trade_date, open, high, low, close, pre_close, volume, amount,
    vwap, turnover_rate, limit_up, limit_down, is_suspended, source_id, batch_id,
    data_version, ingest_time, quality_flag
)
SELECT
    security_id, trade_date, open, high, low, close, pre_close, volume, amount,
    vwap, turnover_rate, limit_up, limit_down, is_suspended, source_id, batch_id,
    data_version, ingest_time, quality_flag
FROM qts.daily_bar;

EXCHANGE TABLES qts.daily_bar AND qts.daily_bar__0056_rebuild;

SYSTEM STOP MERGES qts.daily_bar__0056_rebuild;
SYSTEM START MERGES qts.daily_bar;

CREATE TABLE qts.minute_bar__0056_rebuild
(
    security_id     UInt64,
    trade_date      Date,
    bar_time        DateTime64(3, 'Asia/Shanghai'),
    open            Nullable(Float64),
    high            Nullable(Float64),
    low             Nullable(Float64),
    close           Nullable(Float64),
    volume          Nullable(Float64),
    amount          Nullable(Float64),
    vwap            Nullable(Float64),
    source_id       UInt64,
    batch_id        UInt64,
    data_version    UInt64,
    ingest_time     DateTime64(3, 'Asia/Shanghai'),
    quality_flag    LowCardinality(String)
)
ENGINE = ReplacingMergeTree(ingest_time)
PARTITION BY toYYYYMM(trade_date)
ORDER BY (security_id, trade_date, bar_time, data_version);

INSERT INTO qts.minute_bar__0056_rebuild
(
    security_id, trade_date, bar_time, open, high, low, close, volume, amount,
    vwap, source_id, batch_id, data_version, ingest_time, quality_flag
)
SELECT
    security_id, trade_date, bar_time, open, high, low, close, volume, amount,
    vwap, source_id, batch_id, data_version, ingest_time, quality_flag
FROM qts.minute_bar;

EXCHANGE TABLES qts.minute_bar AND qts.minute_bar__0056_rebuild;

SYSTEM STOP MERGES qts.minute_bar__0056_rebuild;
SYSTEM START MERGES qts.minute_bar;
