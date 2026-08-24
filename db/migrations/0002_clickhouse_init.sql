-- Run the following section in ClickHouse.
-- ============================================================

CREATE DATABASE IF NOT EXISTS qts;

CREATE TABLE IF NOT EXISTS qts.daily_bar
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

CREATE TABLE IF NOT EXISTS qts.minute_bar
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

CREATE TABLE IF NOT EXISTS qts.factor_value_daily
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

CREATE TABLE IF NOT EXISTS qts.factor_quality_daily
(
    factor_id           UInt64,
    factor_version_id   UInt64,
    trade_date          Date,
    universe_id         Nullable(UInt64),
    coverage_rate       Nullable(Float64),
    missing_rate        Nullable(Float64),
    outlier_rate        Nullable(Float64),
    mean_value          Nullable(Float64),
    std_value           Nullable(Float64),
    min_value           Nullable(Float64),
    max_value           Nullable(Float64),
    calc_time           DateTime64(3, 'Asia/Shanghai')
)
ENGINE = ReplacingMergeTree(calc_time)
PARTITION BY toYYYYMM(trade_date)
ORDER BY (factor_id, trade_date, factor_version_id);

CREATE TABLE IF NOT EXISTS qts.market_data_health_daily
(
    dataset_code        LowCardinality(String),
    trade_date          Date,
    expected_rows       UInt64,
    actual_rows         UInt64,
    missing_rows        UInt64,
    duplicate_rows      UInt64,
    abnormal_rows       UInt64,
    completeness_rate   Nullable(Float64),
    latest_ingest_time  DateTime64(3, 'Asia/Shanghai'),
    status              LowCardinality(String),
    details             String
)
ENGINE = ReplacingMergeTree(latest_ingest_time)
PARTITION BY toYYYYMM(trade_date)
ORDER BY (dataset_code, trade_date);
