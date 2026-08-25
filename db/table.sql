-- 中国量化金融数据底座结构参考快照（非迁移入口）
-- 说明：
-- 1. canonical fresh-install 入口是 db/migrations/0001_postgresql_init.sql
--    与 db/migrations/0002_clickhouse_init.sql；升级只执行版本化 migrations。
-- 2. 本文件把 PostgreSQL 与 ClickHouse 两种方言汇总在一起，仅供审阅和
--    schema contract 测试使用，不应整体交给任一数据库客户端执行。
-- 3. 所有时间字段默认使用 Asia/Shanghai 业务语义，服务层统一转换和校验。

-- ============================================================
-- PostgreSQL: metadata, master data, PIT data
-- ============================================================

CREATE SCHEMA IF NOT EXISTS qmeta;
CREATE SCHEMA IF NOT EXISTS qpit;

-- ----------------------------
-- Data source and batch metadata
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.source_system (
    source_id           BIGSERIAL PRIMARY KEY,
    source_code         VARCHAR(64) NOT NULL UNIQUE,
    source_name         VARCHAR(128) NOT NULL,
    source_type         VARCHAR(32) NOT NULL,
    license_scope       TEXT,
    update_frequency    VARCHAR(32),
    latency_level       VARCHAR(16),
    owner               VARCHAR(128),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_type IN ('exchange', 'vendor', 'index_provider', 'announcement', 'internal', 'news', 'other')),
    CHECK (latency_level IS NULL OR latency_level IN ('L0', 'L1', 'L2', 'L3', 'L4'))
);

CREATE TABLE IF NOT EXISTS qmeta.dataset_catalog (
    dataset_id          BIGSERIAL PRIMARY KEY,
    dataset_code        VARCHAR(96) NOT NULL UNIQUE,
    dataset_name        VARCHAR(128) NOT NULL,
    asset_type          VARCHAR(32),
    frequency           VARCHAR(32),
    storage_layer       VARCHAR(32) NOT NULL,
    primary_source_id   BIGINT REFERENCES qmeta.source_system(source_id),
    pit_required        BOOLEAN NOT NULL DEFAULT FALSE,
    description         TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (storage_layer IN ('raw', 'postgresql', 'clickhouse', 'object_store', 'search', 'vector'))
);

CREATE TABLE IF NOT EXISTS qmeta.data_batch (
    batch_id            BIGSERIAL PRIMARY KEY,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    batch_code          VARCHAR(128) NOT NULL UNIQUE,
    trade_date          DATE,
    natural_date        DATE,
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    status              VARCHAR(24) NOT NULL,
    raw_uri             TEXT,
    row_count           BIGINT,
    error_count         BIGINT NOT NULL DEFAULT 0,
    checksum            VARCHAR(128),
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('created', 'running', 'success', 'partial_success', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_data_batch_dataset_date
    ON qmeta.data_batch(dataset_id, trade_date, status);

CREATE TABLE IF NOT EXISTS qmeta.dataset_version (
    data_version        BIGSERIAL PRIMARY KEY,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    version_code        VARCHAR(128) NOT NULL UNIQUE,
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to            TIMESTAMPTZ,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('active', 'superseded', 'recalled', 'draft'))
);

-- ----------------------------
-- Security master
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.security_master (
    security_id         BIGSERIAL PRIMARY KEY,
    asset_type          VARCHAR(32) NOT NULL,
    exchange            VARCHAR(16) NOT NULL,
    current_symbol      VARCHAR(32) NOT NULL,
    current_name        VARCHAR(128) NOT NULL,
    currency            VARCHAR(16) NOT NULL DEFAULT 'CNY',
    list_date           DATE,
    delist_date         DATE,
    current_status      VARCHAR(32) NOT NULL DEFAULT 'active',
    primary_source_id   BIGINT REFERENCES qmeta.source_system(source_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_type, exchange, current_symbol),
    CHECK (asset_type IN ('stock', 'etf', 'lof', 'convertible_bond', 'index', 'future', 'option', 'fund')),
    CONSTRAINT ck_security_master_current_status CHECK (
        current_status IN (
            'prelisted', 'active', 'suspended', 'st', 'star_st',
            'delisting_period', 'delisted', 'terminated', 'unknown'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_security_master_symbol
    ON qmeta.security_master(current_symbol, exchange);

CREATE TABLE IF NOT EXISTS qmeta.security_identifier_history (
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    symbol              VARCHAR(32) NOT NULL,
    exchange            VARCHAR(16) NOT NULL,
    identifier_type     VARCHAR(32) NOT NULL DEFAULT 'trade_symbol',
    start_date          DATE NOT NULL,
    end_date            DATE,
    announce_time       TIMESTAMPTZ NOT NULL,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT NOT NULL REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, identifier_type, symbol, start_date, revision_id),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_security_identifier_lookup
    ON qmeta.security_identifier_history(symbol, exchange, start_date, end_date);

CREATE TABLE IF NOT EXISTS qmeta.security_name_history (
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    name                VARCHAR(128) NOT NULL,
    start_date          DATE NOT NULL,
    end_date            DATE,
    announce_time       TIMESTAMPTZ NOT NULL,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT NOT NULL REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, start_date, revision_id),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS qmeta.security_status_history (
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    status              VARCHAR(32) NOT NULL,
    start_date          DATE NOT NULL,
    end_date            DATE,
    reason              TEXT,
    announce_time       TIMESTAMPTZ NOT NULL,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT NOT NULL REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, status, start_date, revision_id),
    CHECK (status IN ('prelisted', 'active', 'suspended', 'st', 'star_st', 'delisting_period', 'delisted', 'unknown')),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_security_status_asof
    ON qmeta.security_status_history(security_id, start_date, end_date);

-- ----------------------------
-- Trading calendar
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.trading_calendar (
    exchange            VARCHAR(16) NOT NULL,
    trade_date          DATE NOT NULL,
    is_open             BOOLEAN NOT NULL,
    session_type        VARCHAR(32) NOT NULL DEFAULT 'full_day',
    pretrade_date       DATE,
    next_trade_date     DATE,
    open_time           TIME,
    close_time          TIME,
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, trade_date),
    CHECK (session_type IN ('full_day', 'half_day', 'closed', 'special'))
);

-- ----------------------------
-- Market constraints and adjustment factors
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.adjustment_factor (
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    trade_date          DATE NOT NULL,
    factor_forward      NUMERIC(24, 12),
    factor_backward     NUMERIC(24, 12),
    ex_right_type       VARCHAR(64),
    announce_time       TIMESTAMPTZ,
    effective_time      TIMESTAMPTZ,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (security_id, trade_date, revision_id)
);

CREATE INDEX IF NOT EXISTS idx_adjustment_factor_security_date_revision
    ON qmeta.adjustment_factor(security_id, trade_date DESC, revision_id DESC);

CREATE TABLE IF NOT EXISTS qmeta.suspension_history (
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ,
    suspension_type     VARCHAR(64),
    reason              TEXT,
    announce_time       TIMESTAMPTZ,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (security_id, start_time, revision_id)
);

CREATE INDEX IF NOT EXISTS idx_suspension_asof
    ON qmeta.suspension_history(security_id, start_time, end_time);

CREATE TABLE IF NOT EXISTS qmeta.limit_price_daily (
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    trade_date          DATE NOT NULL,
    limit_up            NUMERIC(20, 6),
    limit_down          NUMERIC(20, 6),
    limit_rule          VARCHAR(64),
    is_st               BOOLEAN NOT NULL DEFAULT FALSE,
    is_new_listing      BOOLEAN NOT NULL DEFAULT FALSE,
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (security_id, trade_date, revision_id)
);

CREATE INDEX IF NOT EXISTS idx_limit_price_security_date_revision
    ON qmeta.limit_price_daily(security_id, trade_date DESC, revision_id DESC);

-- ----------------------------
-- Point-in-Time fundamentals
-- ----------------------------

CREATE TABLE IF NOT EXISTS qpit.financial_statement_pit (
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    report_period       DATE NOT NULL,
    statement_type      VARCHAR(32) NOT NULL,
    period_type         VARCHAR(16) NOT NULL,
    field_name          VARCHAR(96) NOT NULL,
    field_value         NUMERIC(28, 8),
    unit                VARCHAR(32) NOT NULL DEFAULT 'CNY',
    announce_time       TIMESTAMPTZ NOT NULL,
    effective_time      TIMESTAMPTZ NOT NULL,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL,
    is_restated         BOOLEAN NOT NULL DEFAULT FALSE,
    quality_flag        VARCHAR(32) NOT NULL DEFAULT 'normal',
    PRIMARY KEY (security_id, report_period, statement_type, period_type, field_name, revision_id),
    CHECK (statement_type IN ('balance_sheet', 'income_statement', 'cash_flow')),
    CHECK (period_type IN ('single_quarter', 'ytd', 'ttm', 'annual')),
    CHECK (quality_flag IN ('normal', 'estimated', 'missing', 'abnormal', 'vendor_conflict'))
);

CREATE INDEX IF NOT EXISTS idx_financial_statement_pit_asof
    ON qpit.financial_statement_pit(security_id, field_name, announce_time, ingest_time);

CREATE TABLE IF NOT EXISTS qpit.financial_metric_pit (
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    report_period       DATE NOT NULL,
    metric_name         VARCHAR(96) NOT NULL,
    metric_value        NUMERIC(28, 8),
    metric_unit         VARCHAR(32),
    metric_scope        VARCHAR(32) NOT NULL,
    announce_time       TIMESTAMPTZ NOT NULL,
    effective_time      TIMESTAMPTZ NOT NULL,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL,
    is_restated         BOOLEAN NOT NULL DEFAULT FALSE,
    quality_flag        VARCHAR(32) NOT NULL DEFAULT 'normal',
    PRIMARY KEY (security_id, report_period, metric_name, metric_scope, revision_id),
    CHECK (metric_scope IN ('single_quarter', 'ytd', 'ttm', 'annual')),
    CHECK (quality_flag IN ('normal', 'estimated', 'missing', 'abnormal', 'vendor_conflict'))
);

CREATE INDEX IF NOT EXISTS idx_financial_metric_pit_asof
    ON qpit.financial_metric_pit(security_id, metric_name, announce_time, ingest_time);

CREATE TABLE IF NOT EXISTS qpit.earnings_forecast_pit (
    forecast_id         BIGSERIAL PRIMARY KEY,
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    report_period       DATE NOT NULL,
    forecast_type       VARCHAR(64),
    net_profit_lower    NUMERIC(28, 8),
    net_profit_upper    NUMERIC(28, 8),
    yoy_lower           NUMERIC(20, 8),
    yoy_upper           NUMERIC(20, 8),
    currency            VARCHAR(16) NOT NULL DEFAULT 'CNY',
    announce_time       TIMESTAMPTZ NOT NULL,
    effective_time      TIMESTAMPTZ NOT NULL,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_doc_id       VARCHAR(128),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    quality_flag        VARCHAR(32) NOT NULL DEFAULT 'normal'
);

CREATE INDEX IF NOT EXISTS idx_earnings_forecast_pit_asof
    ON qpit.earnings_forecast_pit(security_id, report_period, announce_time, ingest_time);

CREATE TABLE IF NOT EXISTS qpit.earnings_express_pit (
    express_id          BIGSERIAL PRIMARY KEY,
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    report_period       DATE NOT NULL,
    revenue             NUMERIC(28, 8),
    net_profit          NUMERIC(28, 8),
    net_profit_parent   NUMERIC(28, 8),
    eps                 NUMERIC(20, 8),
    roe                 NUMERIC(20, 8),
    announce_time       TIMESTAMPTZ NOT NULL,
    effective_time      TIMESTAMPTZ NOT NULL,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_doc_id       VARCHAR(128),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    quality_flag        VARCHAR(32) NOT NULL DEFAULT 'normal'
);

CREATE INDEX IF NOT EXISTS idx_earnings_express_pit_asof
    ON qpit.earnings_express_pit(security_id, report_period, announce_time, ingest_time);

-- ----------------------------
-- Index, industry, universe
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.index_master (
    index_id            BIGSERIAL PRIMARY KEY,
    index_code          VARCHAR(32) NOT NULL,
    exchange            VARCHAR(16),
    index_name          VARCHAR(128) NOT NULL,
    provider            VARCHAR(64),
    currency            VARCHAR(16) NOT NULL DEFAULT 'CNY',
    base_date           DATE,
    launch_date         DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (index_code, provider)
);

CREATE TABLE IF NOT EXISTS qpit.index_member_pit (
    index_id            BIGINT NOT NULL REFERENCES qmeta.index_master(index_id),
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    effective_date      DATE NOT NULL,
    end_date            DATE,
    weight              NUMERIC(20, 10),
    announce_time       TIMESTAMPTZ,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (index_id, security_id, effective_date, revision_id),
    CHECK (end_date IS NULL OR end_date >= effective_date)
);

CREATE INDEX IF NOT EXISTS idx_index_member_pit_asof
    ON qpit.index_member_pit(index_id, effective_date, end_date, ingest_time);

CREATE TABLE IF NOT EXISTS qmeta.industry_system (
    industry_system_id  BIGSERIAL PRIMARY KEY,
    system_code         VARCHAR(32) NOT NULL UNIQUE,
    system_name         VARCHAR(128) NOT NULL,
    provider            VARCHAR(64),
    version             VARCHAR(64),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.industry_category (
    industry_id         BIGSERIAL PRIMARY KEY,
    industry_system_id  BIGINT NOT NULL REFERENCES qmeta.industry_system(industry_system_id),
    industry_code       VARCHAR(64) NOT NULL,
    industry_name       VARCHAR(128) NOT NULL,
    level               SMALLINT NOT NULL,
    parent_industry_id  BIGINT REFERENCES qmeta.industry_category(industry_id),
    start_date          DATE,
    end_date            DATE,
    UNIQUE (industry_system_id, industry_code, level)
);

CREATE TABLE IF NOT EXISTS qmeta.industry_category_history (
    industry_id         BIGINT NOT NULL REFERENCES qmeta.industry_category(industry_id),
    industry_system_id  BIGINT NOT NULL REFERENCES qmeta.industry_system(industry_system_id),
    industry_code       VARCHAR(64) NOT NULL,
    industry_name       VARCHAR(128) NOT NULL,
    level               SMALLINT NOT NULL,
    parent_industry_id  BIGINT REFERENCES qmeta.industry_category(industry_id),
    start_date          DATE NOT NULL,
    end_date            DATE,
    announce_time       TIMESTAMPTZ NOT NULL,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT NOT NULL REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (industry_id, start_date, revision_id),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_industry_category_history_asof
    ON qmeta.industry_category_history(
        industry_system_id, level, start_date, ingest_time, batch_id
    );

CREATE TABLE IF NOT EXISTS qpit.industry_membership_pit (
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    industry_system_id  BIGINT NOT NULL REFERENCES qmeta.industry_system(industry_system_id),
    industry_id         BIGINT NOT NULL REFERENCES qmeta.industry_category(industry_id),
    effective_date      DATE NOT NULL,
    end_date            DATE,
    announce_time       TIMESTAMPTZ,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (security_id, industry_system_id, industry_id, effective_date, revision_id),
    CHECK (end_date IS NULL OR end_date >= effective_date)
);

CREATE INDEX IF NOT EXISTS idx_industry_membership_pit_asof
    ON qpit.industry_membership_pit(security_id, industry_system_id, effective_date, end_date);

CREATE TABLE IF NOT EXISTS qmeta.universe_definition (
    universe_id         BIGSERIAL PRIMARY KEY,
    universe_code       VARCHAR(64) NOT NULL UNIQUE,
    universe_name       VARCHAR(128) NOT NULL,
    universe_type       VARCHAR(32) NOT NULL,
    description         TEXT,
    owner               VARCHAR(128),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (universe_type IN ('index', 'rule_based', 'manual', 'strategy'))
);

-- A universe's type determines which PIT selection contract applies.  Changing
-- it in place would reinterpret existing membership history, so type changes
-- must be represented by a new universe_definition row instead.
CREATE OR REPLACE FUNCTION qmeta.reject_universe_type_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.universe_type IS DISTINCT FROM OLD.universe_type THEN
        RAISE EXCEPTION
            'universe_type is immutable for universe_id %; create a new universe instead',
            OLD.universe_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_universe_type_immutable
    ON qmeta.universe_definition;

CREATE TRIGGER trg_universe_type_immutable
    BEFORE UPDATE OF universe_type ON qmeta.universe_definition
    FOR EACH ROW
    EXECUTE FUNCTION qmeta.reject_universe_type_change();

CREATE TABLE IF NOT EXISTS qmeta.universe_snapshot (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    universe_id         BIGINT NOT NULL REFERENCES qmeta.universe_definition(universe_id),
    trade_date          DATE NOT NULL,
    batch_id            BIGINT NOT NULL REFERENCES qmeta.data_batch(batch_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (universe_id, trade_date, batch_id)
);

CREATE INDEX IF NOT EXISTS idx_universe_snapshot_selection
    ON qmeta.universe_snapshot(universe_id, trade_date, batch_id DESC);

CREATE TABLE IF NOT EXISTS qpit.universe_member_pit (
    universe_id         BIGINT NOT NULL REFERENCES qmeta.universe_definition(universe_id),
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    effective_date      DATE NOT NULL,
    end_date            DATE,
    weight              NUMERIC(20, 10),
    announce_time       TIMESTAMPTZ,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    PRIMARY KEY (universe_id, security_id, effective_date, revision_id),
    CHECK (end_date IS NULL OR end_date >= effective_date)
);

CREATE INDEX IF NOT EXISTS idx_universe_member_pit_universe_asof
    ON qpit.universe_member_pit(universe_id, effective_date DESC, end_date, security_id);

-- ----------------------------
-- Corporate events
-- ----------------------------

CREATE TABLE IF NOT EXISTS qpit.corporate_event_pit (
    event_id            BIGSERIAL PRIMARY KEY,
    security_id         BIGINT NOT NULL REFERENCES qmeta.security_master(security_id),
    event_type          VARCHAR(64) NOT NULL,
    event_time          TIMESTAMPTZ,
    announce_time       TIMESTAMPTZ NOT NULL,
    effective_time      TIMESTAMPTZ,
    ingest_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence          NUMERIC(8, 6),
    source_doc_id       VARCHAR(128),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    revision_id         BIGINT NOT NULL DEFAULT 1,
    quality_flag        VARCHAR(32) NOT NULL DEFAULT 'normal'
);

CREATE INDEX IF NOT EXISTS idx_corporate_event_pit_asof
    ON qpit.corporate_event_pit(security_id, event_type, announce_time, ingest_time);

CREATE INDEX IF NOT EXISTS idx_corporate_event_payload_gin
    ON qpit.corporate_event_pit USING GIN (event_payload);

-- ----------------------------
-- Factor metadata
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.factor_definition (
    factor_id           BIGSERIAL PRIMARY KEY,
    factor_code         VARCHAR(96) NOT NULL UNIQUE,
    factor_name         VARCHAR(128) NOT NULL,
    factor_type         VARCHAR(32) NOT NULL,
    frequency           VARCHAR(32) NOT NULL,
    description         TEXT,
    owner               VARCHAR(128),
    default_direction   SMALLINT,
    is_pit_safe         BOOLEAN NOT NULL DEFAULT FALSE,
    status              VARCHAR(24) NOT NULL DEFAULT 'draft',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (factor_type IN ('price_volume', 'fundamental', 'valuation', 'liquidity', 'volatility', 'event', 'sentiment', 'industry', 'microstructure', 'other')),
    CHECK (frequency IN ('tick', '1m', '5m', '15m', '30m', '1d', '1w', '1mth')),
    CHECK (status IN ('draft', 'testing', 'published', 'deprecated', 'disabled')),
    CHECK (default_direction IS NULL OR default_direction IN (-1, 0, 1))
);

CREATE TABLE IF NOT EXISTS qmeta.factor_version (
    factor_version_id   BIGSERIAL PRIMARY KEY,
    factor_id           BIGINT NOT NULL REFERENCES qmeta.factor_definition(factor_id),
    version_code        VARCHAR(96) NOT NULL,
    code_repo           TEXT,
    code_commit         VARCHAR(128),
    input_datasets      JSONB NOT NULL DEFAULT '[]'::jsonb,
    input_data_versions JSONB NOT NULL DEFAULT '[]'::jsonb,
    parameter_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_at        TIMESTAMPTZ,
    status              VARCHAR(24) NOT NULL DEFAULT 'draft',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (factor_id, version_code),
    CHECK (status IN ('draft', 'testing', 'published', 'deprecated', 'disabled'))
);

-- ----------------------------
-- Quality and audit
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.data_quality_check_result (
    check_id            BIGSERIAL PRIMARY KEY,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    batch_id            BIGINT REFERENCES qmeta.data_batch(batch_id),
    check_date          DATE,
    check_name          VARCHAR(128) NOT NULL,
    check_type          VARCHAR(64) NOT NULL,
    status              VARCHAR(24) NOT NULL,
    severity            VARCHAR(16) NOT NULL DEFAULT 'info',
    metric_value        NUMERIC(28, 8),
    threshold_value     NUMERIC(28, 8),
    affected_rows       BIGINT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('pass', 'warning', 'failed', 'skipped')),
    CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_quality_dataset_date
    ON qmeta.data_quality_check_result(dataset_id, check_date, status);

CREATE TABLE IF NOT EXISTS qmeta.pipeline_job (
    job_id              BIGSERIAL PRIMARY KEY,
    job_code            VARCHAR(128) NOT NULL UNIQUE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    provider            VARCHAR(64) NOT NULL,
    frequency           VARCHAR(32) NOT NULL DEFAULT 'daily',
    symbols             TEXT[] NOT NULL DEFAULT '{}',
    provider_config     JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_root            TEXT NOT NULL DEFAULT 'raw',
    strict_quality      BOOLEAN NOT NULL DEFAULT TRUE,
    retry_limit         INTEGER NOT NULL DEFAULT 1,
    all_market          BOOLEAN NOT NULL DEFAULT FALSE,
    batch_size          INTEGER NOT NULL DEFAULT 0,
    max_symbols         INTEGER,
    min_completeness    NUMERIC(12, 8) NOT NULL DEFAULT 1,
    skip_closed_days    BOOLEAN NOT NULL DEFAULT TRUE,
    sleep_seconds       NUMERIC(12, 3) NOT NULL DEFAULT 0,
    schedule_timezone   VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (frequency IN ('daily', 'minute', 'quarterly', 'adhoc')),
    CHECK (retry_limit >= 0),
    CONSTRAINT chk_pipeline_job_batch_size CHECK (batch_size >= 0),
    CONSTRAINT chk_pipeline_job_max_symbols CHECK (max_symbols IS NULL OR max_symbols > 0),
    CONSTRAINT chk_pipeline_job_min_completeness CHECK (min_completeness >= 0 AND min_completeness <= 1),
    CONSTRAINT chk_pipeline_job_sleep_seconds CHECK (sleep_seconds >= 0)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_job_dataset_source
    ON qmeta.pipeline_job(dataset_id, source_id, is_active);

CREATE TABLE IF NOT EXISTS qmeta.pipeline_run (
    run_id              BIGSERIAL PRIMARY KEY,
    job_id              BIGINT NOT NULL REFERENCES qmeta.pipeline_job(job_id),
    trade_date          DATE NOT NULL,
    attempt             INTEGER NOT NULL DEFAULT 1,
    run_type            VARCHAR(32) NOT NULL DEFAULT 'manual',
    status              VARCHAR(24) NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    input_symbols       TEXT[] NOT NULL DEFAULT '{}',
    provider_config     JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_paths           JSONB NOT NULL DEFAULT '{}'::jsonb,
    row_count           BIGINT,
    expected_row_count  BIGINT,
    missing_count       BIGINT NOT NULL DEFAULT 0,
    missing_symbols     TEXT[] NOT NULL DEFAULT '{}',
    completeness_rate   NUMERIC(12, 8),
    expected_by_exchange JSONB NOT NULL DEFAULT '{}'::jsonb,
    actual_by_exchange  JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_by_exchange JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_explanations JSONB NOT NULL DEFAULT '{}'::jsonb,
    batch_count         INTEGER NOT NULL DEFAULT 1,
    all_market          BOOLEAN NOT NULL DEFAULT FALSE,
    repair_status       VARCHAR(24) NOT NULL DEFAULT 'none',
    quality_passed      BOOLEAN,
    error_count         BIGINT NOT NULL DEFAULT 0,
    warning_count       BIGINT NOT NULL DEFAULT 0,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, trade_date, attempt),
    CHECK (attempt >= 1),
    CHECK (run_type IN ('manual', 'scheduled', 'backfill', 'retry', 'dry_run')),
    CHECK (status IN ('created', 'running', 'success', 'partial_success', 'failed', 'skipped', 'cancelled')),
    CONSTRAINT chk_pipeline_run_expected_row_count CHECK (expected_row_count IS NULL OR expected_row_count >= 0),
    CONSTRAINT chk_pipeline_run_missing_count CHECK (missing_count >= 0),
    CONSTRAINT chk_pipeline_run_completeness_rate CHECK (completeness_rate IS NULL OR (completeness_rate >= 0 AND completeness_rate <= 1)),
    CONSTRAINT chk_pipeline_run_batch_count CHECK (batch_count >= 0),
    CONSTRAINT chk_pipeline_run_repair_status CHECK (repair_status IN ('none', 'queued', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_job_date
    ON qmeta.pipeline_run(job_id, trade_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_pipeline_run_status_started
    ON qmeta.pipeline_run(status, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.pipeline_watermark (
    job_id                  BIGINT PRIMARY KEY REFERENCES qmeta.pipeline_job(job_id),
    last_success_trade_date DATE,
    last_success_run_id     BIGINT REFERENCES qmeta.pipeline_run(run_id),
    last_attempt_trade_date DATE,
    last_attempt_run_id     BIGINT REFERENCES qmeta.pipeline_run(run_id),
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (consecutive_failures >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.pipeline_repair_queue (
    repair_id           BIGSERIAL PRIMARY KEY,
    job_id              BIGINT NOT NULL REFERENCES qmeta.pipeline_job(job_id),
    run_id              BIGINT REFERENCES qmeta.pipeline_run(run_id),
    trade_date          DATE NOT NULL,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    reason              VARCHAR(64) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'open',
    expected_row_count  BIGINT,
    row_count           BIGINT,
    missing_count       BIGINT NOT NULL DEFAULT 0,
    missing_symbols     TEXT[] NOT NULL DEFAULT '{}',
    completeness_rate   NUMERIC(12, 8),
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    UNIQUE (job_id, trade_date, reason),
    CHECK (status IN ('open', 'in_progress', 'resolved', 'ignored')),
    CHECK (reason IN ('failed', 'partial_success', 'completeness_below_threshold')),
    CHECK (expected_row_count IS NULL OR expected_row_count >= 0),
    CHECK (row_count IS NULL OR row_count >= 0),
    CHECK (missing_count >= 0),
    CHECK (completeness_rate IS NULL OR (completeness_rate >= 0 AND completeness_rate <= 1))
);

CREATE INDEX IF NOT EXISTS idx_pipeline_repair_status_date
    ON qmeta.pipeline_repair_queue(status, trade_date, updated_at);

CREATE INDEX IF NOT EXISTS idx_pipeline_repair_job_date
    ON qmeta.pipeline_repair_queue(job_id, trade_date DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.query_audit_log (
    audit_id            BIGSERIAL PRIMARY KEY,
    user_id             VARCHAR(128),
    api_name            VARCHAR(128) NOT NULL,
    request_id          VARCHAR(128),
    request_hash        VARCHAR(128),
    request_summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_versions       JSONB NOT NULL DEFAULT '[]'::jsonb,
    status              VARCHAR(24) NOT NULL,
    error_code          VARCHAR(64),
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    row_count           BIGINT,
    client_ip           INET,
    user_agent          TEXT,
    CHECK (status IN ('success', 'failed', 'partial_success'))
);

CREATE INDEX IF NOT EXISTS idx_query_audit_user_time
    ON qmeta.query_audit_log(user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.matrix_export_audit (
    export_id           BIGSERIAL PRIMARY KEY,
    export_code         VARCHAR(128),
    dataset_code        VARCHAR(96) NOT NULL,
    field_name          VARCHAR(128) NOT NULL,
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    symbol_count        BIGINT NOT NULL DEFAULT 0,
    row_count           BIGINT NOT NULL DEFAULT 0,
    output_uri          TEXT NOT NULL,
    output_format       VARCHAR(24) NOT NULL,
    request_summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (symbol_count >= 0),
    CHECK (row_count >= 0),
    CHECK (output_format IN ('csv', 'parquet'))
);

CREATE INDEX IF NOT EXISTS idx_matrix_export_audit_dataset_date
    ON qmeta.matrix_export_audit(dataset_code, end_date DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.source_priority (
    priority_id         BIGSERIAL PRIMARY KEY,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    priority            INTEGER NOT NULL,
    is_fallback         BOOLEAN NOT NULL DEFAULT TRUE,
    effective_date      DATE NOT NULL DEFAULT DATE '1900-01-01',
    end_date            DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, source_id, effective_date),
    CHECK (priority >= 0),
    CHECK (end_date IS NULL OR end_date >= effective_date)
);

CREATE INDEX IF NOT EXISTS idx_source_priority_dataset_effective
    ON qmeta.source_priority(dataset_id, effective_date DESC, priority);

CREATE TABLE IF NOT EXISTS qmeta.data_conflict_daily (
    conflict_id         BIGSERIAL PRIMARY KEY,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    security_id         BIGINT REFERENCES qmeta.security_master(security_id),
    symbol              VARCHAR(32) NOT NULL,
    trade_date          DATE NOT NULL,
    field_name          VARCHAR(96) NOT NULL,
    primary_value       TEXT,
    secondary_value     TEXT,
    absolute_diff       NUMERIC(28, 12),
    relative_diff       NUMERIC(28, 12),
    severity            VARCHAR(24) NOT NULL DEFAULT 'low',
    status              VARCHAR(24) NOT NULL DEFAULT 'open',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, primary_source_id, secondary_source_id, symbol, trade_date, field_name),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'accepted', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS idx_data_conflict_daily_date_status
    ON qmeta.data_conflict_daily(trade_date DESC, status, severity);

CREATE INDEX IF NOT EXISTS idx_data_conflict_daily_dataset_date
    ON qmeta.data_conflict_daily(dataset_id, trade_date DESC, severity);

CREATE TABLE IF NOT EXISTS qmeta.api_token (
    token_id            BIGSERIAL PRIMARY KEY,
    token_hash          VARCHAR(128) NOT NULL UNIQUE,
    token_name          VARCHAR(128) NOT NULL,
    owner               VARCHAR(128),
    scopes              TEXT[] NOT NULL DEFAULT '{}',
    quota_per_min       INTEGER NOT NULL DEFAULT 120,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at        TIMESTAMPTZ,
    CHECK (quota_per_min > 0)
);

CREATE INDEX IF NOT EXISTS idx_api_token_active_owner
    ON qmeta.api_token(is_active, owner);

CREATE TABLE IF NOT EXISTS qmeta.api_request_audit (
    api_audit_id        BIGSERIAL PRIMARY KEY,
    token_id            BIGINT REFERENCES qmeta.api_token(token_id),
    api_name            VARCHAR(128) NOT NULL,
    request_id          VARCHAR(128),
    request_summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_format     VARCHAR(24) NOT NULL DEFAULT 'json',
    status              VARCHAR(24) NOT NULL,
    row_count           BIGINT,
    error_message       TEXT,
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    client_ip           INET,
    user_agent          TEXT,
    CHECK (status IN ('success', 'failed', 'partial_success')),
    CHECK (response_format IN ('json', 'csv', 'arrow'))
);

CREATE INDEX IF NOT EXISTS idx_api_request_audit_token_time
    ON qmeta.api_request_audit(token_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_request_audit_api_time
    ON qmeta.api_request_audit(api_name, started_at DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.multi_source_quality_daily (
    quality_id          BIGSERIAL PRIMARY KEY,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    trade_date          DATE NOT NULL,
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_count       BIGINT NOT NULL DEFAULT 0,
    secondary_count     BIGINT NOT NULL DEFAULT 0,
    matched_count       BIGINT NOT NULL DEFAULT 0,
    conflict_count      BIGINT NOT NULL DEFAULT 0,
    coverage_rate       NUMERIC(12, 8),
    conflict_rate       NUMERIC(12, 8),
    status              VARCHAR(24) NOT NULL DEFAULT 'pass',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, trade_date, primary_source_id, secondary_source_id),
    CHECK (primary_count >= 0),
    CHECK (secondary_count >= 0),
    CHECK (matched_count >= 0),
    CHECK (conflict_count >= 0),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate IS NULL OR (conflict_rate >= 0 AND conflict_rate <= 1)),
    CHECK (status IN ('pass', 'warning', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_multi_source_quality_daily_date_status
    ON qmeta.multi_source_quality_daily(trade_date DESC, status, conflict_rate DESC);

CREATE TABLE IF NOT EXISTS qmeta.sla_policy (
    policy_id               BIGSERIAL PRIMARY KEY,
    policy_code             VARCHAR(128) NOT NULL UNIQUE,
    policy_name             VARCHAR(128) NOT NULL,
    dataset_id              BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    job_id                  BIGINT REFERENCES qmeta.pipeline_job(job_id),
    source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    target_finish_time      TIME,
    timezone                VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    min_completeness        NUMERIC(12, 8),
    max_conflict_rate       NUMERIC(12, 8),
    max_api_error_rate      NUMERIC(12, 8),
    max_duration_ms         BIGINT,
    alert_severity          VARCHAR(24) NOT NULL DEFAULT 'high',
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    owner                   VARCHAR(128),
    notification_channels   JSONB NOT NULL DEFAULT '[]'::jsonb,
    description             TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (min_completeness IS NULL OR (min_completeness >= 0 AND min_completeness <= 1)),
    CHECK (max_conflict_rate IS NULL OR (max_conflict_rate >= 0 AND max_conflict_rate <= 1)),
    CHECK (max_api_error_rate IS NULL OR (max_api_error_rate >= 0 AND max_api_error_rate <= 1)),
    CHECK (max_duration_ms IS NULL OR max_duration_ms >= 0),
    CHECK (alert_severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_sla_policy_active_dataset_job
    ON qmeta.sla_policy(is_active, dataset_id, job_id, source_id);

CREATE TABLE IF NOT EXISTS qmeta.alert_event (
    alert_id            BIGSERIAL PRIMARY KEY,
    alert_key           VARCHAR(256) NOT NULL UNIQUE,
    policy_id           BIGINT REFERENCES qmeta.sla_policy(policy_id),
    dataset_id          BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    job_id              BIGINT REFERENCES qmeta.pipeline_job(job_id),
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    trade_date          DATE,
    alert_type          VARCHAR(64) NOT NULL,
    severity            VARCHAR(24) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'open',
    metric_name         VARCHAR(96),
    metric_value        NUMERIC(28, 12),
    threshold_value     NUMERIC(28, 12),
    message             TEXT NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at     TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (alert_type IN (
        'missing_run',
        'pipeline_status',
        'pipeline_late',
        'completeness_below_sla',
        'conflict_rate_above_sla',
        'api_error_rate_above_sla',
        'duration_above_sla'
    )),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'acknowledged', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS idx_alert_event_status_date
    ON qmeta.alert_event(status, trade_date DESC, severity);

CREATE INDEX IF NOT EXISTS idx_alert_event_policy_date
    ON qmeta.alert_event(policy_id, trade_date DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.ops_dashboard_snapshot (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    snapshot_code       VARCHAR(160) NOT NULL UNIQUE,
    snapshot_date       DATE NOT NULL DEFAULT CURRENT_DATE,
    window_start        DATE NOT NULL,
    window_end          DATE NOT NULL,
    job_code            VARCHAR(128),
    dataset_code        VARCHAR(96),
    pipeline_summary    JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_summary     JSONB NOT NULL DEFAULT '{}'::jsonb,
    sla_summary         JSONB NOT NULL DEFAULT '{}'::jsonb,
    api_summary         JSONB NOT NULL DEFAULT '{}'::jsonb,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (window_end >= window_start)
);

CREATE INDEX IF NOT EXISTS idx_ops_dashboard_snapshot_window
    ON qmeta.ops_dashboard_snapshot(window_start DESC, window_end DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_integration_profile (
    profile_id              BIGSERIAL PRIMARY KEY,
    source_id               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    provider_name           VARCHAR(64) NOT NULL,
    auth_mode               VARCHAR(32) NOT NULL DEFAULT 'none',
    endpoint_base           TEXT,
    enabled_datasets        TEXT[] NOT NULL DEFAULT '{}',
    rate_limit_per_min      INTEGER,
    retry_limit             INTEGER NOT NULL DEFAULT 2,
    timeout_ms              INTEGER NOT NULL DEFAULT 30000,
    license_scope           TEXT,
    redistribution_allowed  BOOLEAN,
    commercial_contract_ref VARCHAR(128),
    status                  VARCHAR(24) NOT NULL DEFAULT 'testing',
    owner                   VARCHAR(128),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, provider_name),
    CHECK (auth_mode IN ('none', 'bearer', 'header', 'query', 'basic')),
    CHECK (status IN ('testing', 'active', 'paused', 'retired')),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (retry_limit >= 0),
    CHECK (timeout_ms > 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_profile_status_provider
    ON qmeta.vendor_integration_profile(status, provider_name, source_id);

CREATE TABLE IF NOT EXISTS qmeta.provider_error_event (
    error_id            BIGSERIAL PRIMARY KEY,
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
    dataset_id          BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    provider_name       VARCHAR(64) NOT NULL,
    trade_date          DATE,
    symbol              VARCHAR(32),
    error_stage         VARCHAR(64) NOT NULL,
    error_type          VARCHAR(64) NOT NULL,
    retryable           BOOLEAN NOT NULL DEFAULT FALSE,
    attempt             INTEGER,
    error_message       TEXT NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (error_stage IN ('auth', 'rate_limit', 'request', 'parse', 'normalize', 'load', 'compare', 'benchmark')),
    CHECK (error_type IN ('auth', 'rate_limit', 'timeout', 'network', 'server', 'client', 'schema', 'empty', 'unknown')),
    CHECK (attempt IS NULL OR attempt >= 0)
);

CREATE INDEX IF NOT EXISTS idx_provider_error_event_source_date
    ON qmeta.provider_error_event(provider_name, trade_date DESC, error_type);

CREATE TABLE IF NOT EXISTS qmeta.provider_benchmark_run (
    benchmark_id        BIGSERIAL PRIMARY KEY,
    benchmark_code      VARCHAR(160) NOT NULL UNIQUE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    symbol_count        BIGINT NOT NULL DEFAULT 0,
    date_count          BIGINT NOT NULL DEFAULT 0,
    primary_row_count   BIGINT NOT NULL DEFAULT 0,
    secondary_row_count BIGINT NOT NULL DEFAULT 0,
    matched_count       BIGINT NOT NULL DEFAULT 0,
    conflict_count      BIGINT NOT NULL DEFAULT 0,
    request_count       BIGINT NOT NULL DEFAULT 0,
    failure_count       BIGINT NOT NULL DEFAULT 0,
    coverage_rate       NUMERIC(12, 8),
    conflict_rate       NUMERIC(12, 8),
    failure_rate        NUMERIC(12, 8),
    total_duration_ms   BIGINT,
    p50_latency_ms      NUMERIC(18, 4),
    p95_latency_ms      NUMERIC(18, 4),
    rows_per_second     NUMERIC(18, 4),
    status              VARCHAR(24) NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (symbol_count >= 0),
    CHECK (date_count >= 0),
    CHECK (primary_row_count >= 0),
    CHECK (secondary_row_count >= 0),
    CHECK (matched_count >= 0),
    CHECK (conflict_count >= 0),
    CHECK (request_count >= 0),
    CHECK (failure_count >= 0),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate IS NULL OR (conflict_rate >= 0 AND conflict_rate <= 1)),
    CHECK (failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)),
    CHECK (status IN ('success', 'warning', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_provider_benchmark_run_dataset_date
    ON qmeta.provider_benchmark_run(dataset_id, end_date DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.vendor_quality_score_daily (
    score_id            BIGSERIAL PRIMARY KEY,
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    score_date          DATE NOT NULL,
    benchmark_id        BIGINT REFERENCES qmeta.provider_benchmark_run(benchmark_id),
    coverage_rate       NUMERIC(12, 8),
    conflict_rate       NUMERIC(12, 8),
    failure_rate        NUMERIC(12, 8),
    latency_ms          NUMERIC(18, 4),
    coverage_score      NUMERIC(8, 4),
    conflict_score      NUMERIC(8, 4),
    stability_score     NUMERIC(8, 4),
    latency_score       NUMERIC(8, 4),
    cost_score          NUMERIC(8, 4),
    license_risk_score  NUMERIC(8, 4),
    total_score         NUMERIC(8, 4),
    rating              VARCHAR(16) NOT NULL DEFAULT 'unknown',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, dataset_id, score_date),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate IS NULL OR (conflict_rate >= 0 AND conflict_rate <= 1)),
    CHECK (failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)),
    CHECK (rating IN ('A', 'B', 'C', 'D', 'unknown'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_quality_score_daily_dataset_score
    ON qmeta.vendor_quality_score_daily(dataset_id, score_date DESC, total_score DESC);

-- Theta: vendor productionization, sharded benchmark and decision reports

ALTER TABLE qmeta.sla_policy
    ADD COLUMN IF NOT EXISTS min_vendor_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS max_vendor_conflict_rate NUMERIC(12, 8),
    ADD COLUMN IF NOT EXISTS max_vendor_failure_rate NUMERIC(12, 8),
    ADD COLUMN IF NOT EXISTS max_vendor_latency_ms NUMERIC(18, 4),
    ADD COLUMN IF NOT EXISTS max_provider_error_count BIGINT;

ALTER TABLE qmeta.alert_event
    DROP CONSTRAINT IF EXISTS alert_event_alert_type_check;

ALTER TABLE qmeta.alert_event
    ADD CONSTRAINT alert_event_alert_type_check
    CHECK (alert_type IN (
        'missing_run',
        'pipeline_status',
        'pipeline_late',
        'completeness_below_sla',
        'conflict_rate_above_sla',
        'api_error_rate_above_sla',
        'duration_above_sla',
        'vendor_score_below_sla',
        'vendor_conflict_rate_above_sla',
        'vendor_failure_rate_above_sla',
        'vendor_latency_above_sla',
        'provider_error_count_above_sla',
        'budget_threshold_warning',
        'budget_exceeded',
        'budget_blocked',
        'budget_usage_spike',
        'runtime_metric_warning',
        'runtime_metric_critical',
        'runtime_capacity_warning',
        'runtime_capacity_critical',
        'runtime_daily_degraded',
        'free_source_recovery_required'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_field_mapping (
    mapping_id          BIGSERIAL PRIMARY KEY,
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    external_field      VARCHAR(128) NOT NULL,
    internal_field      VARCHAR(128) NOT NULL,
    transform_rule      VARCHAR(64) NOT NULL DEFAULT 'identity',
    unit_from           VARCHAR(64),
    unit_to             VARCHAR(64),
    is_required         BOOLEAN NOT NULL DEFAULT FALSE,
    priority            INTEGER NOT NULL DEFAULT 100,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, dataset_id, external_field),
    CHECK (status IN ('active', 'testing', 'paused', 'retired')),
    CHECK (priority >= 0),
    CHECK (transform_rule IN (
        'identity',
        'date_yyyymmdd',
        'volume_hand_to_share',
        'amount_thousand_to_yuan',
        'amount_wan_to_yuan',
        'pct_to_ratio',
        'bps_to_ratio'
    ))
);

CREATE INDEX IF NOT EXISTS idx_vendor_field_mapping_lookup
    ON qmeta.vendor_field_mapping(source_id, dataset_id, status, priority);

CREATE TABLE IF NOT EXISTS qmeta.provider_benchmark_suite_run (
    suite_id            BIGSERIAL PRIMARY KEY,
    suite_code          VARCHAR(180) NOT NULL UNIQUE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    target_trade_days   INTEGER,
    shard_size          INTEGER NOT NULL,
    max_symbols         INTEGER,
    symbol_count        BIGINT NOT NULL DEFAULT 0,
    shard_count         BIGINT NOT NULL DEFAULT 0,
    benchmark_count     BIGINT NOT NULL DEFAULT 0,
    primary_row_count   BIGINT NOT NULL DEFAULT 0,
    secondary_row_count BIGINT NOT NULL DEFAULT 0,
    matched_count       BIGINT NOT NULL DEFAULT 0,
    conflict_count      BIGINT NOT NULL DEFAULT 0,
    request_count       BIGINT NOT NULL DEFAULT 0,
    failure_count       BIGINT NOT NULL DEFAULT 0,
    coverage_rate       NUMERIC(12, 8),
    conflict_rate       NUMERIC(12, 8),
    failure_rate        NUMERIC(12, 8),
    p95_latency_ms      NUMERIC(18, 4),
    rows_per_second     NUMERIC(18, 4),
    status              VARCHAR(24) NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (target_trade_days IS NULL OR target_trade_days > 0),
    CHECK (shard_size > 0),
    CHECK (max_symbols IS NULL OR max_symbols > 0),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate IS NULL OR (conflict_rate >= 0 AND conflict_rate <= 1)),
    CHECK (failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)),
    CHECK (status IN ('success', 'warning', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_provider_benchmark_suite_run_dataset_date
    ON qmeta.provider_benchmark_suite_run(dataset_id, end_date DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.vendor_decision_report (
    report_id           BIGSERIAL PRIMARY KEY,
    report_code         VARCHAR(180) NOT NULL UNIQUE,
    source_id           BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    score_date          DATE NOT NULL,
    suite_id            BIGINT REFERENCES qmeta.provider_benchmark_suite_run(suite_id),
    total_score         NUMERIC(8, 4),
    rating              VARCHAR(16),
    recommendation      VARCHAR(32) NOT NULL,
    recommended_role    VARCHAR(32) NOT NULL,
    rationale           TEXT NOT NULL,
    blocking_issues     TEXT[] NOT NULL DEFAULT '{}',
    next_actions        TEXT[] NOT NULL DEFAULT '{}',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (recommendation IN ('approve_primary', 'approve_backup', 'watch', 'reject')),
    CHECK (recommended_role IN ('primary', 'backup', 'research_only', 'none')),
    CHECK (rating IS NULL OR rating IN ('A', 'B', 'C', 'D', 'unknown'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_decision_report_dataset_date
    ON qmeta.vendor_decision_report(dataset_id, score_date DESC, recommendation);

-- Iota: production notifications, tenant ACL, usage metering and benchmark scheduling

CREATE TABLE IF NOT EXISTS qmeta.tenant (
    tenant_id           BIGSERIAL PRIMARY KEY,
    tenant_code         VARCHAR(96) NOT NULL UNIQUE,
    tenant_name         VARCHAR(128) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    owner               VARCHAR(128),
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE TABLE IF NOT EXISTS qmeta.project (
    project_id          BIGSERIAL PRIMARY KEY,
    tenant_id           BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    project_code        VARCHAR(96) NOT NULL,
    project_name        VARCHAR(128) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    owner               VARCHAR(128),
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, project_code),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE TABLE IF NOT EXISTS qmeta.principal (
    principal_id        BIGSERIAL PRIMARY KEY,
    tenant_id           BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    principal_code      VARCHAR(128) NOT NULL,
    principal_name      VARCHAR(128) NOT NULL,
    principal_type      VARCHAR(32) NOT NULL DEFAULT 'service_account',
    email               VARCHAR(256),
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, principal_code),
    CHECK (principal_type IN ('user', 'service_account')),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE TABLE IF NOT EXISTS qmeta.project_member (
    member_id           BIGSERIAL PRIMARY KEY,
    project_id          BIGINT NOT NULL REFERENCES qmeta.project(project_id),
    principal_id        BIGINT NOT NULL REFERENCES qmeta.principal(principal_id),
    role                VARCHAR(32) NOT NULL DEFAULT 'viewer',
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, principal_id),
    CHECK (role IN ('owner', 'admin', 'researcher', 'viewer', 'service')),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE TABLE IF NOT EXISTS qmeta.dataset_access_policy (
    access_id           BIGSERIAL PRIMARY KEY,
    tenant_id           BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    principal_id        BIGINT REFERENCES qmeta.principal(principal_id),
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    access_level        VARCHAR(32) NOT NULL DEFAULT 'read',
    field_allowlist     TEXT[] NOT NULL DEFAULT '{}',
    field_denylist      TEXT[] NOT NULL DEFAULT '{}',
    row_filter          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (access_level IN ('read', 'write', 'admin')),
    CHECK (status IN ('active', 'paused', 'retired')),
    CHECK (tenant_id IS NOT NULL OR project_id IS NOT NULL OR principal_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_dataset_access_policy_lookup
    ON qmeta.dataset_access_policy(dataset_id, status, tenant_id, project_id, principal_id);

ALTER TABLE qmeta.api_token
    ADD COLUMN IF NOT EXISTS tenant_id BIGINT REFERENCES qmeta.tenant(tenant_id),
    ADD COLUMN IF NOT EXISTS project_id BIGINT REFERENCES qmeta.project(project_id),
    ADD COLUMN IF NOT EXISTS principal_id BIGINT REFERENCES qmeta.principal(principal_id),
    ADD COLUMN IF NOT EXISTS cost_center VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_api_token_tenant_project
    ON qmeta.api_token(tenant_id, project_id, principal_id, is_active);

ALTER TABLE qmeta.api_request_audit
    ADD COLUMN IF NOT EXISTS tenant_id BIGINT REFERENCES qmeta.tenant(tenant_id),
    ADD COLUMN IF NOT EXISTS project_id BIGINT REFERENCES qmeta.project(project_id),
    ADD COLUMN IF NOT EXISTS principal_id BIGINT REFERENCES qmeta.principal(principal_id),
    ADD COLUMN IF NOT EXISTS cost_units NUMERIC(18, 6);

CREATE INDEX IF NOT EXISTS idx_api_request_audit_project_time
    ON qmeta.api_request_audit(project_id, started_at DESC, api_name);

CREATE TABLE IF NOT EXISTS qmeta.api_usage_daily (
    usage_id            BIGSERIAL PRIMARY KEY,
    usage_date          DATE NOT NULL,
    tenant_id           BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    principal_id        BIGINT REFERENCES qmeta.principal(principal_id),
    token_id            BIGINT REFERENCES qmeta.api_token(token_id),
    api_name            VARCHAR(128) NOT NULL,
    request_count       BIGINT NOT NULL DEFAULT 0,
    failed_count        BIGINT NOT NULL DEFAULT 0,
    row_count           BIGINT NOT NULL DEFAULT 0,
    duration_ms         BIGINT NOT NULL DEFAULT 0,
    cost_units          NUMERIC(18, 6) NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (usage_date, tenant_id, project_id, principal_id, token_id, api_name),
    CHECK (request_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (row_count >= 0),
    CHECK (duration_ms >= 0),
    CHECK (cost_units >= 0)
);

CREATE INDEX IF NOT EXISTS idx_api_usage_daily_project_date
    ON qmeta.api_usage_daily(project_id, usage_date DESC, cost_units DESC);

CREATE TABLE IF NOT EXISTS qmeta.notification_channel (
    channel_id          BIGSERIAL PRIMARY KEY,
    channel_code        VARCHAR(128) NOT NULL UNIQUE,
    channel_name        VARCHAR(128) NOT NULL,
    channel_type        VARCHAR(32) NOT NULL,
    endpoint            TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    min_severity        VARCHAR(24) NOT NULL DEFAULT 'low',
    config              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (channel_type IN ('stdout', 'webhook', 'email', 'feishu')),
    CHECK (min_severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE TABLE IF NOT EXISTS qmeta.alert_notification_delivery (
    delivery_id         BIGSERIAL PRIMARY KEY,
    alert_id            BIGINT NOT NULL REFERENCES qmeta.alert_event(alert_id),
    channel_id          BIGINT NOT NULL REFERENCES qmeta.notification_channel(channel_id),
    delivery_key        VARCHAR(256) NOT NULL UNIQUE,
    status              VARCHAR(24) NOT NULL DEFAULT 'pending',
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    last_attempt_at     TIMESTAMPTZ,
    delivered_at        TIMESTAMPTZ,
    response_summary    TEXT,
    error_message       TEXT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    CHECK (attempt_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_alert_notification_delivery_status
    ON qmeta.alert_notification_delivery(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_benchmark_schedule (
    schedule_id         BIGSERIAL PRIMARY KEY,
    schedule_code       VARCHAR(160) NOT NULL UNIQUE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id   BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    secondary_source_id BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    target_trade_days   INTEGER,
    shard_size          INTEGER NOT NULL DEFAULT 500,
    max_symbols         INTEGER,
    cadence             VARCHAR(32) NOT NULL DEFAULT 'manual',
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    last_suite_id       BIGINT REFERENCES qmeta.provider_benchmark_suite_run(suite_id),
    last_run_at         TIMESTAMPTZ,
    next_run_at         TIMESTAMPTZ,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date),
    CHECK (target_trade_days IS NULL OR target_trade_days > 0),
    CHECK (shard_size > 0),
    CHECK (max_symbols IS NULL OR max_symbols > 0),
    CHECK (cadence IN ('manual', 'daily', 'weekly', 'monthly')),
    CHECK (status IN ('active', 'paused', 'retired'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_benchmark_schedule_due
    ON qmeta.vendor_benchmark_schedule(status, next_run_at, cadence);

-- Lambda: background worker run/task observability

CREATE TABLE IF NOT EXISTS qmeta.worker_run (
    worker_run_id       BIGSERIAL PRIMARY KEY,
    run_code            VARCHAR(160) NOT NULL UNIQUE,
    trigger_mode        VARCHAR(32) NOT NULL DEFAULT 'manual',
    status              VARCHAR(24) NOT NULL DEFAULT 'running',
    task_filter         TEXT[] NOT NULL DEFAULT '{}',
    dry_run             BOOLEAN NOT NULL DEFAULT FALSE,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    processed_count     BIGINT NOT NULL DEFAULT 0,
    success_count       BIGINT NOT NULL DEFAULT 0,
    failed_count        BIGINT NOT NULL DEFAULT 0,
    warning_count       BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke')),
    CHECK (status IN ('running', 'success', 'warning', 'failed', 'skipped')),
    CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CHECK (processed_count >= 0),
    CHECK (success_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (warning_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_run_status_started
    ON qmeta.worker_run(status, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.worker_task_run (
    task_run_id         BIGSERIAL PRIMARY KEY,
    worker_run_id       BIGINT NOT NULL REFERENCES qmeta.worker_run(worker_run_id) ON DELETE CASCADE,
    task_name           VARCHAR(96) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'running',
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    processed_count     BIGINT NOT NULL DEFAULT 0,
    success_count       BIGINT NOT NULL DEFAULT 0,
    failed_count        BIGINT NOT NULL DEFAULT 0,
    warning_count       BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule')),
    CHECK (status IN ('running', 'success', 'warning', 'failed', 'skipped')),
    CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CHECK (processed_count >= 0),
    CHECK (success_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (warning_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_task_run_task_started
    ON qmeta.worker_task_run(task_name, started_at DESC, status);

-- Mu: scheduler, lock and heartbeat observability

CREATE TABLE IF NOT EXISTS qmeta.worker_schedule (
    schedule_id         BIGSERIAL PRIMARY KEY,
    schedule_code       VARCHAR(160) NOT NULL UNIQUE,
    task_name           VARCHAR(96) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    frequency_seconds   INTEGER NOT NULL DEFAULT 300,
    max_runtime_seconds INTEGER NOT NULL DEFAULT 600,
    lock_timeout_seconds INTEGER NOT NULL DEFAULT 900,
    retry_limit         INTEGER NOT NULL DEFAULT 3,
    retry_backoff_seconds INTEGER NOT NULL DEFAULT 60,
    dry_run             BOOLEAN NOT NULL DEFAULT FALSE,
    task_args           JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_worker_run_id  BIGINT REFERENCES qmeta.worker_run(worker_run_id),
    last_status         VARCHAR(24),
    last_run_at         TIMESTAMPTZ,
    next_run_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_count           BIGINT NOT NULL DEFAULT 0,
    success_count       BIGINT NOT NULL DEFAULT 0,
    warning_count       BIGINT NOT NULL DEFAULT 0,
    failed_count        BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule')),
    CHECK (status IN ('active', 'paused', 'retired')),
    CHECK (last_status IS NULL OR last_status IN ('running', 'success', 'warning', 'failed', 'skipped')),
    CHECK (frequency_seconds > 0),
    CHECK (max_runtime_seconds > 0),
    CHECK (lock_timeout_seconds > 0),
    CHECK (retry_limit >= 0),
    CHECK (retry_backoff_seconds >= 0),
    CHECK (run_count >= 0),
    CHECK (success_count >= 0),
    CHECK (warning_count >= 0),
    CHECK (failed_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_schedule_due
    ON qmeta.worker_schedule(status, next_run_at, task_name);

CREATE TABLE IF NOT EXISTS qmeta.worker_lock (
    lock_name           VARCHAR(200) PRIMARY KEY,
    owner_id            VARCHAR(160) NOT NULL,
    acquired_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_worker_lock_expires
    ON qmeta.worker_lock(expires_at);

CREATE TABLE IF NOT EXISTS qmeta.worker_heartbeat (
    scheduler_id        VARCHAR(160) PRIMARY KEY,
    status              VARCHAR(24) NOT NULL DEFAULT 'running',
    host_name           VARCHAR(160),
    process_id          INTEGER,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    stopped_at          TIMESTAMPTZ,
    current_schedule_code VARCHAR(160),
    tick_count          BIGINT NOT NULL DEFAULT 0,
    run_count           BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('running', 'stopping', 'stopped', 'failed')),
    CHECK (tick_count >= 0),
    CHECK (run_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_heartbeat_status_seen
    ON qmeta.worker_heartbeat(status, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.worker_schedule_tick (
    tick_id             BIGSERIAL PRIMARY KEY,
    tick_code           VARCHAR(180) NOT NULL UNIQUE,
    scheduler_id        VARCHAR(160) NOT NULL,
    schedule_id         BIGINT REFERENCES qmeta.worker_schedule(schedule_id) ON DELETE SET NULL,
    schedule_code       VARCHAR(160) NOT NULL,
    task_name           VARCHAR(96) NOT NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'running',
    due_at              TIMESTAMPTZ,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    duration_ms         BIGINT,
    worker_run_id       BIGINT REFERENCES qmeta.worker_run(worker_run_id),
    lock_name           VARCHAR(200),
    lock_acquired       BOOLEAN NOT NULL DEFAULT FALSE,
    dry_run             BOOLEAN NOT NULL DEFAULT FALSE,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule')),
    CHECK (status IN ('running', 'success', 'warning', 'failed', 'skipped', 'skipped_locked')),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_worker_schedule_tick_schedule_started
    ON qmeta.worker_schedule_tick(schedule_code, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_worker_schedule_tick_status_started
    ON qmeta.worker_schedule_tick(status, started_at DESC);

-- Nu: deployment release and health observability

CREATE TABLE IF NOT EXISTS qmeta.deployment_release (
    release_id          BIGSERIAL PRIMARY KEY,
    release_code        VARCHAR(160) NOT NULL UNIQUE,
    release_name        VARCHAR(160) NOT NULL,
    environment         VARCHAR(64) NOT NULL DEFAULT 'local',
    version_label       VARCHAR(128),
    git_ref             VARCHAR(160),
    status              VARCHAR(32) NOT NULL DEFAULT 'planned',
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    health_snapshot_id  BIGINT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('planned', 'deploying', 'healthy', 'degraded', 'failed', 'rolled_back')),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_deployment_release_env_status
    ON qmeta.deployment_release(environment, status, created_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.deployment_health_snapshot (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    snapshot_code       VARCHAR(180) NOT NULL UNIQUE,
    release_id          BIGINT REFERENCES qmeta.deployment_release(release_id) ON DELETE SET NULL,
    environment         VARCHAR(64) NOT NULL DEFAULT 'local',
    status              VARCHAR(32) NOT NULL,
    checked_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms         BIGINT NOT NULL DEFAULT 0,
    check_count         INTEGER NOT NULL DEFAULT 0,
    success_count       INTEGER NOT NULL DEFAULT 0,
    warning_count       INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('success', 'warning', 'failed')),
    CHECK (duration_ms >= 0),
    CHECK (check_count >= 0),
    CHECK (success_count >= 0),
    CHECK (warning_count >= 0),
    CHECK (failed_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_deployment_health_snapshot_env_checked
    ON qmeta.deployment_health_snapshot(environment, checked_at DESC, status);

ALTER TABLE qmeta.deployment_release
    DROP CONSTRAINT IF EXISTS fk_deployment_release_health_snapshot;

ALTER TABLE qmeta.deployment_release
    ADD CONSTRAINT fk_deployment_release_health_snapshot
    FOREIGN KEY (health_snapshot_id)
    REFERENCES qmeta.deployment_health_snapshot(snapshot_id)
    ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS qmeta.deployment_health_check (
    health_check_id     BIGSERIAL PRIMARY KEY,
    snapshot_id         BIGINT NOT NULL REFERENCES qmeta.deployment_health_snapshot(snapshot_id) ON DELETE CASCADE,
    check_name          VARCHAR(128) NOT NULL,
    component           VARCHAR(64) NOT NULL,
    status              VARCHAR(32) NOT NULL,
    duration_ms         BIGINT NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (component IN ('postgres', 'clickhouse', 'api', 'scheduler', 'kappa', 'docker', 'migration', 'release')),
    CHECK (status IN ('success', 'warning', 'failed', 'skipped')),
    CHECK (duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_deployment_health_check_snapshot_status
    ON qmeta.deployment_health_check(snapshot_id, status, component);

CREATE TABLE IF NOT EXISTS qmeta.deployment_event (
    event_id            BIGSERIAL PRIMARY KEY,
    release_id          BIGINT REFERENCES qmeta.deployment_release(release_id) ON DELETE SET NULL,
    event_code          VARCHAR(180) NOT NULL UNIQUE,
    environment         VARCHAR(64) NOT NULL DEFAULT 'local',
    event_type          VARCHAR(64) NOT NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'success',
    message             TEXT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (event_type IN ('deploy_start', 'deploy_finish', 'health_check', 'rollback_start', 'rollback_finish', 'manual_note')),
    CHECK (status IN ('success', 'warning', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_deployment_event_env_created
    ON qmeta.deployment_event(environment, created_at DESC, event_type);

-- ----------------------------
-- Xi product catalog, pricing and budget governance
-- ----------------------------

ALTER TABLE qmeta.alert_event
    DROP CONSTRAINT IF EXISTS alert_event_alert_type_check;

ALTER TABLE qmeta.alert_event
    ADD CONSTRAINT alert_event_alert_type_check
    CHECK (alert_type IN (
        'missing_run',
        'pipeline_status',
        'pipeline_late',
        'completeness_below_sla',
        'conflict_rate_above_sla',
        'api_error_rate_above_sla',
        'duration_above_sla',
        'vendor_score_below_sla',
        'vendor_conflict_rate_above_sla',
        'vendor_failure_rate_above_sla',
        'vendor_latency_above_sla',
        'provider_error_count_above_sla',
        'budget_threshold_warning',
        'budget_exceeded',
        'budget_blocked',
        'budget_usage_spike',
        'runtime_metric_warning',
        'runtime_metric_critical',
        'runtime_capacity_warning',
        'runtime_capacity_critical',
        'runtime_daily_degraded',
        'free_source_recovery_required'
    ));

CREATE TABLE IF NOT EXISTS qmeta.data_product (
    product_id          BIGSERIAL PRIMARY KEY,
    product_code        VARCHAR(128) NOT NULL UNIQUE,
    product_name        VARCHAR(160) NOT NULL,
    product_type        VARCHAR(32) NOT NULL DEFAULT 'dataset_bundle',
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    billing_unit        VARCHAR(32) NOT NULL DEFAULT 'cost_unit',
    update_frequency    VARCHAR(64),
    sla_level           VARCHAR(64),
    license_scope       TEXT,
    owner               VARCHAR(128),
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (product_type IN ('dataset_bundle', 'api_bundle', 'export', 'package')),
    CHECK (status IN ('active', 'testing', 'paused', 'retired')),
    CHECK (billing_unit IN ('request', 'row', 'cost_unit', 'export', 'month'))
);

CREATE INDEX IF NOT EXISTS idx_data_product_status_type
    ON qmeta.data_product(status, product_type, product_code);

CREATE TABLE IF NOT EXISTS qmeta.data_product_dataset (
    product_id          BIGINT NOT NULL REFERENCES qmeta.data_product(product_id) ON DELETE CASCADE,
    dataset_id          BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    access_level        VARCHAR(32) NOT NULL DEFAULT 'read',
    is_required         BOOLEAN NOT NULL DEFAULT TRUE,
    field_allowlist     TEXT[] NOT NULL DEFAULT '{}',
    field_denylist      TEXT[] NOT NULL DEFAULT '{}',
    row_filter          JSONB NOT NULL DEFAULT '{}'::jsonb,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, dataset_id),
    CHECK (access_level IN ('read', 'write', 'admin'))
);

CREATE INDEX IF NOT EXISTS idx_data_product_dataset_dataset
    ON qmeta.data_product_dataset(dataset_id, product_id);

CREATE TABLE IF NOT EXISTS qmeta.data_product_api (
    product_id          BIGINT NOT NULL REFERENCES qmeta.data_product(product_id) ON DELETE CASCADE,
    api_name            VARCHAR(128) NOT NULL,
    required_scope      VARCHAR(64) NOT NULL DEFAULT 'read',
    is_billable         BOOLEAN NOT NULL DEFAULT TRUE,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, api_name)
);

CREATE INDEX IF NOT EXISTS idx_data_product_api_name
    ON qmeta.data_product_api(api_name, is_billable);

CREATE TABLE IF NOT EXISTS qmeta.pricing_plan (
    plan_id             BIGSERIAL PRIMARY KEY,
    plan_code           VARCHAR(128) NOT NULL UNIQUE,
    plan_name           VARCHAR(160) NOT NULL,
    billing_cycle       VARCHAR(32) NOT NULL DEFAULT 'monthly',
    currency            VARCHAR(16) NOT NULL DEFAULT 'CNY',
    base_fee            NUMERIC(24, 8) NOT NULL DEFAULT 0,
    included_cost_units NUMERIC(24, 8) NOT NULL DEFAULT 0,
    included_requests   BIGINT NOT NULL DEFAULT 0,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (billing_cycle IN ('daily', 'monthly', 'annual', 'prepaid', 'usage')),
    CHECK (status IN ('active', 'testing', 'paused', 'retired')),
    CHECK (base_fee >= 0),
    CHECK (included_cost_units >= 0),
    CHECK (included_requests >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.pricing_rule (
    rule_id             BIGSERIAL PRIMARY KEY,
    plan_id             BIGINT NOT NULL REFERENCES qmeta.pricing_plan(plan_id) ON DELETE CASCADE,
    product_id          BIGINT REFERENCES qmeta.data_product(product_id) ON DELETE SET NULL,
    rule_code           VARCHAR(160) NOT NULL UNIQUE,
    metric_name         VARCHAR(32) NOT NULL DEFAULT 'cost_unit',
    api_name            VARCHAR(128),
    unit_price          NUMERIC(24, 10) NOT NULL DEFAULT 0,
    free_quantity       NUMERIC(24, 8) NOT NULL DEFAULT 0,
    tier_start          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    tier_end            NUMERIC(24, 8),
    effective_from      DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_to        DATE,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (metric_name IN ('request', 'row', 'cost_unit', 'export', 'monthly_fee')),
    CHECK (status IN ('active', 'testing', 'paused', 'retired')),
    CHECK (unit_price >= 0),
    CHECK (free_quantity >= 0),
    CHECK (tier_start >= 0),
    CHECK (tier_end IS NULL OR tier_end >= tier_start),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX IF NOT EXISTS idx_pricing_rule_lookup
    ON qmeta.pricing_rule(plan_id, product_id, api_name, metric_name, status, effective_from DESC);

CREATE TABLE IF NOT EXISTS qmeta.product_subscription (
    subscription_id     BIGSERIAL PRIMARY KEY,
    subscription_code   VARCHAR(160) NOT NULL UNIQUE,
    tenant_id           BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    plan_id             BIGINT NOT NULL REFERENCES qmeta.pricing_plan(plan_id),
    product_id          BIGINT NOT NULL REFERENCES qmeta.data_product(product_id),
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    starts_on           DATE NOT NULL DEFAULT CURRENT_DATE,
    ends_on             DATE,
    auto_renew          BOOLEAN NOT NULL DEFAULT TRUE,
    hard_limit_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('active', 'paused', 'cancelled', 'expired')),
    CHECK (ends_on IS NULL OR ends_on >= starts_on)
);

CREATE INDEX IF NOT EXISTS idx_product_subscription_lookup
    ON qmeta.product_subscription(tenant_id, project_id, product_id, status, starts_on, ends_on);

CREATE TABLE IF NOT EXISTS qmeta.budget_policy (
    budget_id           BIGSERIAL PRIMARY KEY,
    budget_code         VARCHAR(160) NOT NULL UNIQUE,
    budget_name         VARCHAR(160) NOT NULL,
    tenant_id           BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    principal_id        BIGINT REFERENCES qmeta.principal(principal_id),
    cost_center         VARCHAR(128),
    plan_id             BIGINT REFERENCES qmeta.pricing_plan(plan_id),
    product_id          BIGINT REFERENCES qmeta.data_product(product_id),
    period              VARCHAR(32) NOT NULL DEFAULT 'monthly',
    budget_amount       NUMERIC(24, 8) NOT NULL,
    currency            VARCHAR(16) NOT NULL DEFAULT 'CNY',
    soft_threshold_pct  NUMERIC(8, 4) NOT NULL DEFAULT 0.7000,
    hard_threshold_pct  NUMERIC(8, 4) NOT NULL DEFAULT 1.0000,
    hard_limit_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
    status              VARCHAR(24) NOT NULL DEFAULT 'active',
    starts_on           DATE NOT NULL DEFAULT CURRENT_DATE,
    ends_on             DATE,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period IN ('daily', 'monthly')),
    CHECK (budget_amount > 0),
    CHECK (soft_threshold_pct >= 0 AND soft_threshold_pct <= 1),
    CHECK (hard_threshold_pct >= 0 AND hard_threshold_pct <= 10),
    CHECK (hard_threshold_pct >= soft_threshold_pct),
    CHECK (status IN ('active', 'paused', 'retired')),
    CHECK (ends_on IS NULL OR ends_on >= starts_on),
    CHECK (tenant_id IS NOT NULL OR project_id IS NOT NULL OR principal_id IS NOT NULL OR cost_center IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_budget_policy_lookup
    ON qmeta.budget_policy(status, tenant_id, project_id, principal_id, cost_center, period);

CREATE TABLE IF NOT EXISTS qmeta.budget_usage_snapshot (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    snapshot_code       VARCHAR(180) NOT NULL UNIQUE,
    budget_id           BIGINT NOT NULL REFERENCES qmeta.budget_policy(budget_id) ON DELETE CASCADE,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    usage_amount        NUMERIC(24, 8) NOT NULL DEFAULT 0,
    budget_amount       NUMERIC(24, 8) NOT NULL,
    usage_pct           NUMERIC(12, 8) NOT NULL DEFAULT 0,
    request_count       BIGINT NOT NULL DEFAULT 0,
    row_count           BIGINT NOT NULL DEFAULT 0,
    cost_units          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    status              VARCHAR(24) NOT NULL DEFAULT 'normal',
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (budget_id, period_start, period_end),
    CHECK (period_end >= period_start),
    CHECK (usage_amount >= 0),
    CHECK (budget_amount > 0),
    CHECK (usage_pct >= 0),
    CHECK (request_count >= 0),
    CHECK (row_count >= 0),
    CHECK (cost_units >= 0),
    CHECK (status IN ('normal', 'warning', 'exceeded', 'blocked'))
);

CREATE INDEX IF NOT EXISTS idx_budget_usage_snapshot_status
    ON qmeta.budget_usage_snapshot(status, period_start DESC, usage_amount DESC);

CREATE TABLE IF NOT EXISTS qmeta.budget_alert (
    budget_alert_id     BIGSERIAL PRIMARY KEY,
    alert_key           VARCHAR(256) NOT NULL UNIQUE,
    budget_id           BIGINT NOT NULL REFERENCES qmeta.budget_policy(budget_id) ON DELETE CASCADE,
    snapshot_id         BIGINT REFERENCES qmeta.budget_usage_snapshot(snapshot_id) ON DELETE SET NULL,
    alert_type          VARCHAR(64) NOT NULL,
    severity            VARCHAR(24) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'open',
    threshold_pct       NUMERIC(8, 4),
    usage_pct           NUMERIC(12, 8) NOT NULL DEFAULT 0,
    message             TEXT NOT NULL,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (alert_type IN ('budget_threshold_warning', 'budget_exceeded', 'budget_blocked', 'budget_usage_spike')),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'acknowledged', 'resolved', 'ignored')),
    CHECK (threshold_pct IS NULL OR threshold_pct >= 0),
    CHECK (usage_pct >= 0)
);

CREATE INDEX IF NOT EXISTS idx_budget_alert_status
    ON qmeta.budget_alert(status, severity, last_seen_at DESC);

-- ----------------------------
-- Omicron invoices and revenue governance
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.invoice (
    invoice_id          BIGSERIAL PRIMARY KEY,
    invoice_code        VARCHAR(180) NOT NULL UNIQUE,
    tenant_id           BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    project_id          BIGINT REFERENCES qmeta.project(project_id),
    subscription_id     BIGINT REFERENCES qmeta.product_subscription(subscription_id),
    plan_id             BIGINT REFERENCES qmeta.pricing_plan(plan_id),
    product_id          BIGINT REFERENCES qmeta.data_product(product_id),
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    invoice_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    due_date            DATE,
    currency            VARCHAR(16) NOT NULL DEFAULT 'CNY',
    status              VARCHAR(24) NOT NULL DEFAULT 'draft',
    subtotal_amount     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    discount_amount     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    tax_amount          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    total_amount        NUMERIC(24, 8) NOT NULL DEFAULT 0,
    paid_amount         NUMERIC(24, 8) NOT NULL DEFAULT 0,
    outstanding_amount  NUMERIC(24, 8) NOT NULL DEFAULT 0,
    issued_at           TIMESTAMPTZ,
    paid_at             TIMESTAMPTZ,
    voided_at           TIMESTAMPTZ,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start),
    CHECK (due_date IS NULL OR due_date >= invoice_date),
    CHECK (status IN ('draft', 'issued', 'partially_paid', 'paid', 'overdue', 'void')),
    CHECK (subtotal_amount >= 0),
    CHECK (discount_amount >= 0),
    CHECK (tax_amount >= 0),
    CHECK (total_amount >= 0),
    CHECK (paid_amount >= 0),
    CHECK (outstanding_amount >= 0),
    CHECK (paid_amount <= total_amount)
);

CREATE INDEX IF NOT EXISTS idx_invoice_tenant_period
    ON qmeta.invoice(tenant_id, project_id, period_start DESC, period_end DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_status_due
    ON qmeta.invoice(status, due_date, invoice_date DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_subscription_period
    ON qmeta.invoice(subscription_id, period_start DESC, period_end DESC);

CREATE TABLE IF NOT EXISTS qmeta.invoice_line (
    line_id             BIGSERIAL PRIMARY KEY,
    invoice_id          BIGINT NOT NULL REFERENCES qmeta.invoice(invoice_id) ON DELETE CASCADE,
    line_code           VARCHAR(220) NOT NULL UNIQUE,
    product_id          BIGINT REFERENCES qmeta.data_product(product_id),
    pricing_rule_id     BIGINT REFERENCES qmeta.pricing_rule(rule_id) ON DELETE SET NULL,
    api_name            VARCHAR(128),
    metric_name         VARCHAR(32) NOT NULL,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    quantity            NUMERIC(24, 8) NOT NULL DEFAULT 0,
    unit_price          NUMERIC(24, 10) NOT NULL DEFAULT 0,
    amount              NUMERIC(24, 8) NOT NULL DEFAULT 0,
    request_count       BIGINT NOT NULL DEFAULT 0,
    row_count           BIGINT NOT NULL DEFAULT 0,
    cost_units          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start),
    CHECK (metric_name IN ('request', 'row', 'cost_unit', 'export', 'monthly_fee', 'base_fee', 'adjustment')),
    CHECK (quantity >= 0),
    CHECK (unit_price >= 0),
    CHECK (amount >= 0),
    CHECK (request_count >= 0),
    CHECK (row_count >= 0),
    CHECK (cost_units >= 0)
);

CREATE INDEX IF NOT EXISTS idx_invoice_line_invoice
    ON qmeta.invoice_line(invoice_id, line_id);

CREATE INDEX IF NOT EXISTS idx_invoice_line_product_api
    ON qmeta.invoice_line(product_id, api_name, metric_name);

CREATE TABLE IF NOT EXISTS qmeta.invoice_event (
    event_id            BIGSERIAL PRIMARY KEY,
    invoice_id          BIGINT NOT NULL REFERENCES qmeta.invoice(invoice_id) ON DELETE CASCADE,
    event_code          VARCHAR(220) NOT NULL UNIQUE,
    event_type          VARCHAR(64) NOT NULL,
    status              VARCHAR(24) NOT NULL DEFAULT 'success',
    message             TEXT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (event_type IN ('generated', 'issued', 'paid', 'overdue', 'void', 'manual_note')),
    CHECK (status IN ('success', 'warning', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_invoice_event_invoice_time
    ON qmeta.invoice_event(invoice_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_invoice_event_type_time
    ON qmeta.invoice_event(event_type, created_at DESC);

-- ----------------------------
-- Pi vendor readiness review
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.vendor_readiness_review (
    review_id                 BIGSERIAL PRIMARY KEY,
    review_code               VARCHAR(180) NOT NULL UNIQUE,
    dataset_id                BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id                 BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id         BIGINT REFERENCES qmeta.source_system(source_id),
    review_date               DATE NOT NULL DEFAULT CURRENT_DATE,
    required_windows          INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    suite_count               INTEGER NOT NULL DEFAULT 0,
    passed_window_count       INTEGER NOT NULL DEFAULT 0,
    warning_window_count      INTEGER NOT NULL DEFAULT 0,
    failed_window_count       INTEGER NOT NULL DEFAULT 0,
    missing_window_count      INTEGER NOT NULL DEFAULT 0,
    status                    VARCHAR(24) NOT NULL DEFAULT 'incomplete',
    recommendation            VARCHAR(32) NOT NULL DEFAULT 'watch',
    recommended_role          VARCHAR(32) NOT NULL DEFAULT 'research_only',
    min_coverage_rate         NUMERIC(12, 8) NOT NULL DEFAULT 0.95000000,
    max_conflict_rate         NUMERIC(12, 8) NOT NULL DEFAULT 0.00500000,
    max_failure_rate          NUMERIC(12, 8) NOT NULL DEFAULT 0.01000000,
    max_p95_latency_ms        NUMERIC(18, 4) NOT NULL DEFAULT 5000,
    min_rows_per_second       NUMERIC(18, 4) NOT NULL DEFAULT 0,
    observed_min_coverage_rate NUMERIC(12, 8),
    observed_max_conflict_rate NUMERIC(12, 8),
    observed_max_failure_rate  NUMERIC(12, 8),
    observed_max_p95_latency_ms NUMERIC(18, 4),
    observed_min_rows_per_second NUMERIC(18, 4),
    profile_status            VARCHAR(24),
    runtime_mode              VARCHAR(32) NOT NULL DEFAULT 'unknown',
    blocking_issues           TEXT[] NOT NULL DEFAULT '{}',
    next_actions              TEXT[] NOT NULL DEFAULT '{}',
    details                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (array_length(required_windows, 1) IS NOT NULL),
    CHECK (suite_count >= 0),
    CHECK (passed_window_count >= 0),
    CHECK (warning_window_count >= 0),
    CHECK (failed_window_count >= 0),
    CHECK (missing_window_count >= 0),
    CHECK (status IN ('ready', 'watch', 'rejected', 'incomplete')),
    CHECK (recommendation IN ('approve_primary', 'approve_backup', 'watch', 'reject')),
    CHECK (recommended_role IN ('primary', 'backup', 'research_only', 'none')),
    CHECK (min_coverage_rate >= 0 AND min_coverage_rate <= 1),
    CHECK (max_conflict_rate >= 0 AND max_conflict_rate <= 1),
    CHECK (max_failure_rate >= 0 AND max_failure_rate <= 1),
    CHECK (max_p95_latency_ms >= 0),
    CHECK (min_rows_per_second >= 0),
    CHECK (runtime_mode IN ('live', 'fixture', 'offline', 'unknown'))
);

CREATE INDEX IF NOT EXISTS idx_vendor_readiness_review_lookup
    ON qmeta.vendor_readiness_review(dataset_id, source_id, review_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_readiness_review_recommendation
    ON qmeta.vendor_readiness_review(recommendation, recommended_role, review_date DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_readiness_window (
    window_id          BIGSERIAL PRIMARY KEY,
    review_id          BIGINT NOT NULL REFERENCES qmeta.vendor_readiness_review(review_id) ON DELETE CASCADE,
    window_days        INTEGER NOT NULL,
    suite_id           BIGINT REFERENCES qmeta.provider_benchmark_suite_run(suite_id) ON DELETE SET NULL,
    status             VARCHAR(24) NOT NULL DEFAULT 'missing',
    coverage_rate      NUMERIC(12, 8),
    conflict_rate      NUMERIC(12, 8),
    failure_rate       NUMERIC(12, 8),
    p95_latency_ms     NUMERIC(18, 4),
    rows_per_second    NUMERIC(18, 4),
    symbol_count       BIGINT NOT NULL DEFAULT 0,
    benchmark_count    BIGINT NOT NULL DEFAULT 0,
    blocking_issues    TEXT[] NOT NULL DEFAULT '{}',
    details            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (review_id, window_days),
    CHECK (window_days > 0),
    CHECK (status IN ('pass', 'warning', 'failed', 'missing')),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate IS NULL OR (conflict_rate >= 0 AND conflict_rate <= 1)),
    CHECK (failure_rate IS NULL OR (failure_rate >= 0 AND failure_rate <= 1)),
    CHECK (p95_latency_ms IS NULL OR p95_latency_ms >= 0),
    CHECK (rows_per_second IS NULL OR rows_per_second >= 0),
    CHECK (symbol_count >= 0),
    CHECK (benchmark_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_readiness_window_status
    ON qmeta.vendor_readiness_window(review_id, status, window_days);

CREATE INDEX IF NOT EXISTS idx_vendor_readiness_window_suite
    ON qmeta.vendor_readiness_window(suite_id);

-- ----------------------------
-- Rho revenue reconciliation and customer health
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.revenue_reconciliation_run (
    reconciliation_id        BIGSERIAL PRIMARY KEY,
    reconciliation_code      VARCHAR(200) NOT NULL UNIQUE,
    tenant_id                BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    project_id               BIGINT REFERENCES qmeta.project(project_id),
    subscription_id          BIGINT REFERENCES qmeta.product_subscription(subscription_id),
    plan_id                  BIGINT REFERENCES qmeta.pricing_plan(plan_id),
    product_id               BIGINT REFERENCES qmeta.data_product(product_id),
    invoice_id               BIGINT REFERENCES qmeta.invoice(invoice_id) ON DELETE SET NULL,
    period_start             DATE NOT NULL,
    period_end               DATE NOT NULL,
    reconciliation_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    currency                 VARCHAR(16) NOT NULL DEFAULT 'CNY',
    status                   VARCHAR(32) NOT NULL DEFAULT 'matched',
    tolerance_amount         NUMERIC(24, 8) NOT NULL DEFAULT 0.00000001,
    recomputed_subtotal_amount NUMERIC(24, 8) NOT NULL DEFAULT 0,
    recomputed_total_amount  NUMERIC(24, 8) NOT NULL DEFAULT 0,
    invoice_subtotal_amount  NUMERIC(24, 8) NOT NULL DEFAULT 0,
    invoice_total_amount     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    amount_delta             NUMERIC(24, 8) NOT NULL DEFAULT 0,
    invoice_paid_amount      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    invoice_outstanding_amount NUMERIC(24, 8) NOT NULL DEFAULT 0,
    recomputed_line_count    INTEGER NOT NULL DEFAULT 0,
    invoice_line_count       INTEGER NOT NULL DEFAULT 0,
    matched_line_count       INTEGER NOT NULL DEFAULT 0,
    mismatch_line_count      INTEGER NOT NULL DEFAULT 0,
    missing_line_count       INTEGER NOT NULL DEFAULT 0,
    extra_line_count         INTEGER NOT NULL DEFAULT 0,
    request_count            BIGINT NOT NULL DEFAULT 0,
    row_count                BIGINT NOT NULL DEFAULT 0,
    cost_units               NUMERIC(24, 8) NOT NULL DEFAULT 0,
    details                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start),
    CHECK (status IN ('matched', 'mismatch', 'missing_invoice', 'warning')),
    CHECK (tolerance_amount >= 0),
    CHECK (recomputed_subtotal_amount >= 0),
    CHECK (recomputed_total_amount >= 0),
    CHECK (invoice_subtotal_amount >= 0),
    CHECK (invoice_total_amount >= 0),
    CHECK (invoice_paid_amount >= 0),
    CHECK (invoice_outstanding_amount >= 0),
    CHECK (recomputed_line_count >= 0),
    CHECK (invoice_line_count >= 0),
    CHECK (matched_line_count >= 0),
    CHECK (mismatch_line_count >= 0),
    CHECK (missing_line_count >= 0),
    CHECK (extra_line_count >= 0),
    CHECK (request_count >= 0),
    CHECK (row_count >= 0),
    CHECK (cost_units >= 0)
);

CREATE INDEX IF NOT EXISTS idx_revenue_reconciliation_lookup
    ON qmeta.revenue_reconciliation_run(tenant_id, project_id, product_id, period_start DESC, period_end DESC);

CREATE INDEX IF NOT EXISTS idx_revenue_reconciliation_status
    ON qmeta.revenue_reconciliation_run(status, reconciliation_date DESC, amount_delta);

CREATE TABLE IF NOT EXISTS qmeta.revenue_reconciliation_line (
    line_reconciliation_id   BIGSERIAL PRIMARY KEY,
    reconciliation_id        BIGINT NOT NULL REFERENCES qmeta.revenue_reconciliation_run(reconciliation_id) ON DELETE CASCADE,
    invoice_line_id          BIGINT REFERENCES qmeta.invoice_line(line_id) ON DELETE SET NULL,
    line_key                 VARCHAR(220) NOT NULL,
    api_name                 VARCHAR(128),
    metric_name              VARCHAR(32) NOT NULL,
    product_id               BIGINT REFERENCES qmeta.data_product(product_id),
    pricing_rule_id          BIGINT REFERENCES qmeta.pricing_rule(rule_id) ON DELETE SET NULL,
    status                   VARCHAR(32) NOT NULL DEFAULT 'matched',
    recomputed_quantity      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    invoice_quantity         NUMERIC(24, 8) NOT NULL DEFAULT 0,
    quantity_delta           NUMERIC(24, 8) NOT NULL DEFAULT 0,
    recomputed_amount        NUMERIC(24, 8) NOT NULL DEFAULT 0,
    invoice_amount           NUMERIC(24, 8) NOT NULL DEFAULT 0,
    amount_delta             NUMERIC(24, 8) NOT NULL DEFAULT 0,
    request_count            BIGINT NOT NULL DEFAULT 0,
    row_count                BIGINT NOT NULL DEFAULT 0,
    cost_units               NUMERIC(24, 8) NOT NULL DEFAULT 0,
    details                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (reconciliation_id, line_key),
    CHECK (metric_name IN ('request', 'row', 'cost_unit', 'export', 'monthly_fee', 'base_fee', 'adjustment')),
    CHECK (status IN ('matched', 'mismatch', 'missing_invoice_line', 'extra_invoice_line')),
    CHECK (recomputed_quantity >= 0),
    CHECK (invoice_quantity >= 0),
    CHECK (recomputed_amount >= 0),
    CHECK (invoice_amount >= 0),
    CHECK (request_count >= 0),
    CHECK (row_count >= 0),
    CHECK (cost_units >= 0)
);

CREATE INDEX IF NOT EXISTS idx_revenue_reconciliation_line_status
    ON qmeta.revenue_reconciliation_line(reconciliation_id, status, amount_delta);

CREATE TABLE IF NOT EXISTS qmeta.ar_aging_snapshot (
    aging_id                 BIGSERIAL PRIMARY KEY,
    aging_code               VARCHAR(200) NOT NULL UNIQUE,
    tenant_id                BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    project_id               BIGINT REFERENCES qmeta.project(project_id),
    product_id               BIGINT REFERENCES qmeta.data_product(product_id),
    plan_id                  BIGINT REFERENCES qmeta.pricing_plan(plan_id),
    as_of_date               DATE NOT NULL,
    currency                 VARCHAR(16) NOT NULL DEFAULT 'CNY',
    status                   VARCHAR(24) NOT NULL DEFAULT 'current',
    invoice_count            INTEGER NOT NULL DEFAULT 0,
    overdue_invoice_count    INTEGER NOT NULL DEFAULT 0,
    outstanding_amount       NUMERIC(24, 8) NOT NULL DEFAULT 0,
    current_amount           NUMERIC(24, 8) NOT NULL DEFAULT 0,
    bucket_1_30_amount       NUMERIC(24, 8) NOT NULL DEFAULT 0,
    bucket_31_60_amount      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    bucket_61_90_amount      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    bucket_90_plus_amount    NUMERIC(24, 8) NOT NULL DEFAULT 0,
    max_days_past_due        INTEGER NOT NULL DEFAULT 0,
    details                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, project_id, product_id, plan_id, currency, as_of_date),
    CHECK (status IN ('current', 'watch', 'overdue', 'critical')),
    CHECK (invoice_count >= 0),
    CHECK (overdue_invoice_count >= 0),
    CHECK (outstanding_amount >= 0),
    CHECK (current_amount >= 0),
    CHECK (bucket_1_30_amount >= 0),
    CHECK (bucket_31_60_amount >= 0),
    CHECK (bucket_61_90_amount >= 0),
    CHECK (bucket_90_plus_amount >= 0),
    CHECK (max_days_past_due >= 0)
);

CREATE INDEX IF NOT EXISTS idx_ar_aging_snapshot_status
    ON qmeta.ar_aging_snapshot(status, as_of_date DESC, outstanding_amount DESC);

CREATE TABLE IF NOT EXISTS qmeta.customer_health_snapshot (
    health_id                BIGSERIAL PRIMARY KEY,
    health_code              VARCHAR(220) NOT NULL UNIQUE,
    tenant_id                BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id),
    project_id               BIGINT REFERENCES qmeta.project(project_id),
    subscription_id          BIGINT REFERENCES qmeta.product_subscription(subscription_id),
    product_id               BIGINT REFERENCES qmeta.data_product(product_id),
    plan_id                  BIGINT REFERENCES qmeta.pricing_plan(plan_id),
    as_of_date               DATE NOT NULL,
    status                   VARCHAR(24) NOT NULL DEFAULT 'active',
    retention_signal         VARCHAR(32) NOT NULL DEFAULT 'healthy',
    health_score             INTEGER NOT NULL DEFAULT 100,
    last_usage_date          DATE,
    days_since_last_usage    INTEGER,
    request_count_7d         BIGINT NOT NULL DEFAULT 0,
    request_count_30d        BIGINT NOT NULL DEFAULT 0,
    request_count_90d        BIGINT NOT NULL DEFAULT 0,
    cost_units_30d           NUMERIC(24, 8) NOT NULL DEFAULT 0,
    invoice_count_90d        INTEGER NOT NULL DEFAULT 0,
    paid_amount_90d          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    total_amount_90d         NUMERIC(24, 8) NOT NULL DEFAULT 0,
    outstanding_amount       NUMERIC(24, 8) NOT NULL DEFAULT 0,
    overdue_amount           NUMERIC(24, 8) NOT NULL DEFAULT 0,
    overdue_invoice_count    INTEGER NOT NULL DEFAULT 0,
    details                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subscription_id, as_of_date),
    CHECK (status IN ('active', 'at_risk', 'dormant', 'churned')),
    CHECK (retention_signal IN ('healthy', 'payment_risk', 'usage_declining', 'inactive', 'no_usage')),
    CHECK (health_score >= 0 AND health_score <= 100),
    CHECK (days_since_last_usage IS NULL OR days_since_last_usage >= 0),
    CHECK (request_count_7d >= 0),
    CHECK (request_count_30d >= 0),
    CHECK (request_count_90d >= 0),
    CHECK (cost_units_30d >= 0),
    CHECK (invoice_count_90d >= 0),
    CHECK (paid_amount_90d >= 0),
    CHECK (total_amount_90d >= 0),
    CHECK (outstanding_amount >= 0),
    CHECK (overdue_amount >= 0),
    CHECK (overdue_invoice_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_customer_health_snapshot_status
    ON qmeta.customer_health_snapshot(status, as_of_date DESC, health_score);

-- Sigma runtime observability and capacity warning.

ALTER TABLE qmeta.alert_event
    DROP CONSTRAINT IF EXISTS alert_event_alert_type_check;

ALTER TABLE qmeta.alert_event
    ADD CONSTRAINT alert_event_alert_type_check
    CHECK (alert_type IN (
        'missing_run',
        'pipeline_status',
        'pipeline_late',
        'completeness_below_sla',
        'conflict_rate_above_sla',
        'api_error_rate_above_sla',
        'duration_above_sla',
        'vendor_score_below_sla',
        'vendor_conflict_rate_above_sla',
        'vendor_failure_rate_above_sla',
        'vendor_latency_above_sla',
        'provider_error_count_above_sla',
        'budget_threshold_warning',
        'budget_exceeded',
        'budget_blocked',
        'budget_usage_spike',
        'runtime_metric_warning',
        'runtime_metric_critical',
        'runtime_capacity_warning',
        'runtime_capacity_critical',
        'runtime_daily_degraded',
        'free_source_recovery_required'
    ));

CREATE TABLE IF NOT EXISTS qmeta.runtime_log (
    log_id                  BIGSERIAL PRIMARY KEY,
    log_code                VARCHAR(220) NOT NULL UNIQUE,
    environment             VARCHAR(64) NOT NULL DEFAULT 'local',
    component               VARCHAR(64) NOT NULL,
    service_name            VARCHAR(128),
    release_id              BIGINT REFERENCES qmeta.deployment_release(release_id) ON DELETE SET NULL,
    worker_run_id           BIGINT REFERENCES qmeta.worker_run(worker_run_id) ON DELETE SET NULL,
    log_time                TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity                VARCHAR(24) NOT NULL DEFAULT 'info',
    event_type              VARCHAR(64) NOT NULL DEFAULT 'runtime_event',
    message                 TEXT NOT NULL,
    trace_id                VARCHAR(128),
    request_id              VARCHAR(128),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_runtime_log_component_time
    ON qmeta.runtime_log(environment, component, log_time DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_log_severity_time
    ON qmeta.runtime_log(severity, log_time DESC);

CREATE TABLE IF NOT EXISTS qmeta.runtime_metric_snapshot (
    metric_id               BIGSERIAL PRIMARY KEY,
    metric_code             VARCHAR(220) NOT NULL UNIQUE,
    environment             VARCHAR(64) NOT NULL DEFAULT 'local',
    component               VARCHAR(64) NOT NULL,
    service_name            VARCHAR(128),
    metric_name             VARCHAR(96) NOT NULL,
    metric_time             TIMESTAMPTZ NOT NULL DEFAULT now(),
    metric_value            NUMERIC(28, 12) NOT NULL,
    unit                    VARCHAR(32) NOT NULL DEFAULT 'count',
    status                  VARCHAR(24) NOT NULL DEFAULT 'normal',
    warning_threshold       NUMERIC(28, 12),
    critical_threshold      NUMERIC(28, 12),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('normal', 'warning', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_runtime_metric_lookup
    ON qmeta.runtime_metric_snapshot(environment, component, metric_name, metric_time DESC);

CREATE INDEX IF NOT EXISTS idx_runtime_metric_status_time
    ON qmeta.runtime_metric_snapshot(status, metric_time DESC);

CREATE TABLE IF NOT EXISTS qmeta.runtime_daily_report (
    report_id                       BIGSERIAL PRIMARY KEY,
    report_code                     VARCHAR(180) NOT NULL UNIQUE,
    environment                     VARCHAR(64) NOT NULL DEFAULT 'local',
    report_date                     DATE NOT NULL,
    status                          VARCHAR(24) NOT NULL DEFAULT 'success',
    api_request_count               BIGINT NOT NULL DEFAULT 0,
    api_failed_count                BIGINT NOT NULL DEFAULT 0,
    api_error_rate                  NUMERIC(12, 8) NOT NULL DEFAULT 0,
    api_slowest_duration_ms         BIGINT NOT NULL DEFAULT 0,
    worker_run_count                BIGINT NOT NULL DEFAULT 0,
    worker_failed_count             BIGINT NOT NULL DEFAULT 0,
    worker_warning_count            BIGINT NOT NULL DEFAULT 0,
    deployment_health_status        VARCHAR(24),
    vendor_readiness_watch_count    BIGINT NOT NULL DEFAULT 0,
    invoice_outstanding_amount      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    customer_health_risk_count      BIGINT NOT NULL DEFAULT 0,
    capacity_alert_count            BIGINT NOT NULL DEFAULT 0,
    open_capacity_alert_count       BIGINT NOT NULL DEFAULT 0,
    details                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (environment, report_date),
    CHECK (status IN ('success', 'warning', 'critical')),
    CHECK (api_request_count >= 0),
    CHECK (api_failed_count >= 0),
    CHECK (api_error_rate >= 0),
    CHECK (api_slowest_duration_ms >= 0),
    CHECK (worker_run_count >= 0),
    CHECK (worker_failed_count >= 0),
    CHECK (worker_warning_count >= 0),
    CHECK (vendor_readiness_watch_count >= 0),
    CHECK (invoice_outstanding_amount >= 0),
    CHECK (customer_health_risk_count >= 0),
    CHECK (capacity_alert_count >= 0),
    CHECK (open_capacity_alert_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_runtime_daily_report_status
    ON qmeta.runtime_daily_report(environment, report_date DESC, status);

CREATE TABLE IF NOT EXISTS qmeta.capacity_alert (
    capacity_alert_id       BIGSERIAL PRIMARY KEY,
    alert_key               VARCHAR(256) NOT NULL UNIQUE,
    alert_id                BIGINT REFERENCES qmeta.alert_event(alert_id) ON DELETE SET NULL,
    environment             VARCHAR(64) NOT NULL DEFAULT 'local',
    component               VARCHAR(64) NOT NULL,
    metric_name             VARCHAR(96) NOT NULL,
    severity                VARCHAR(24) NOT NULL DEFAULT 'medium',
    status                  VARCHAR(24) NOT NULL DEFAULT 'open',
    metric_value            NUMERIC(28, 12) NOT NULL,
    threshold_value         NUMERIC(28, 12) NOT NULL,
    unit                    VARCHAR(32) NOT NULL DEFAULT 'count',
    message                 TEXT NOT NULL,
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('open', 'acknowledged', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS idx_capacity_alert_status
    ON qmeta.capacity_alert(status, severity, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_capacity_alert_lookup
    ON qmeta.capacity_alert(environment, component, metric_name, last_seen_at DESC);

-- Tau payment import, invoice matching and revenue ledger.

CREATE TABLE IF NOT EXISTS qmeta.fx_rate_daily (
    rate_id                 BIGSERIAL PRIMARY KEY,
    rate_code               VARCHAR(180) NOT NULL UNIQUE,
    rate_date               DATE NOT NULL,
    from_currency           VARCHAR(16) NOT NULL,
    to_currency             VARCHAR(16) NOT NULL DEFAULT 'CNY',
    rate                    NUMERIC(24, 12) NOT NULL,
    provider                VARCHAR(64) NOT NULL DEFAULT 'manual',
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rate_date, from_currency, to_currency, provider),
    CHECK (from_currency <> ''),
    CHECK (to_currency <> ''),
    CHECK (rate > 0)
);

CREATE INDEX IF NOT EXISTS idx_fx_rate_daily_lookup
    ON qmeta.fx_rate_daily(rate_date DESC, from_currency, to_currency);

CREATE TABLE IF NOT EXISTS qmeta.payment_import_batch (
    batch_id                BIGSERIAL PRIMARY KEY,
    batch_code              VARCHAR(180) NOT NULL UNIQUE,
    source_type             VARCHAR(32) NOT NULL,
    account_code            VARCHAR(128),
    statement_start         DATE,
    statement_end           DATE,
    currency                VARCHAR(16) NOT NULL DEFAULT 'CNY',
    status                  VARCHAR(24) NOT NULL DEFAULT 'imported',
    transaction_count       INTEGER NOT NULL DEFAULT 0,
    matched_count           INTEGER NOT NULL DEFAULT 0,
    unmatched_count         INTEGER NOT NULL DEFAULT 0,
    total_amount            NUMERIC(24, 8) NOT NULL DEFAULT 0,
    matched_amount          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    unmatched_amount        NUMERIC(24, 8) NOT NULL DEFAULT 0,
    imported_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_type IN ('bank_csv', 'alipay_csv', 'wechat_csv', 'manual_csv', 'api', 'demo')),
    CHECK (status IN ('imported', 'matched', 'partially_matched', 'failed', 'void')),
    CHECK (statement_end IS NULL OR statement_start IS NULL OR statement_end >= statement_start),
    CHECK (transaction_count >= 0),
    CHECK (matched_count >= 0),
    CHECK (unmatched_count >= 0),
    CHECK (total_amount >= 0),
    CHECK (matched_amount >= 0),
    CHECK (unmatched_amount >= 0)
);

CREATE INDEX IF NOT EXISTS idx_payment_import_batch_status
    ON qmeta.payment_import_batch(status, imported_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.payment_transaction (
    transaction_id          BIGSERIAL PRIMARY KEY,
    transaction_code        VARCHAR(220) NOT NULL UNIQUE,
    batch_id                BIGINT REFERENCES qmeta.payment_import_batch(batch_id) ON DELETE SET NULL,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id              BIGINT REFERENCES qmeta.project(project_id),
    invoice_id              BIGINT REFERENCES qmeta.invoice(invoice_id) ON DELETE SET NULL,
    payment_channel         VARCHAR(32) NOT NULL DEFAULT 'bank',
    external_transaction_id VARCHAR(160),
    counterparty_name       VARCHAR(180),
    counterparty_account    VARCHAR(180),
    transaction_time        TIMESTAMPTZ NOT NULL,
    value_date              DATE NOT NULL,
    direction               VARCHAR(16) NOT NULL DEFAULT 'inbound',
    currency                VARCHAR(16) NOT NULL DEFAULT 'CNY',
    amount                  NUMERIC(24, 8) NOT NULL,
    base_currency           VARCHAR(16) NOT NULL DEFAULT 'CNY',
    fx_rate_to_base         NUMERIC(24, 12) NOT NULL DEFAULT 1,
    base_amount             NUMERIC(24, 8) NOT NULL,
    status                  VARCHAR(24) NOT NULL DEFAULT 'imported',
    reference_text          TEXT,
    raw_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (payment_channel IN ('bank', 'alipay', 'wechat', 'manual', 'api')),
    CHECK (direction IN ('inbound', 'outbound')),
    CHECK (status IN ('imported', 'matched', 'partially_matched', 'overpaid', 'unmatched', 'ignored', 'reversed')),
    CHECK (amount >= 0),
    CHECK (fx_rate_to_base > 0),
    CHECK (base_amount >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_transaction_external
    ON qmeta.payment_transaction(batch_id, external_transaction_id)
    WHERE external_transaction_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payment_transaction_status
    ON qmeta.payment_transaction(status, value_date DESC, amount DESC);

CREATE INDEX IF NOT EXISTS idx_payment_transaction_invoice
    ON qmeta.payment_transaction(invoice_id, value_date DESC);

CREATE TABLE IF NOT EXISTS qmeta.payment_invoice_match (
    match_id                BIGSERIAL PRIMARY KEY,
    match_code              VARCHAR(240) NOT NULL UNIQUE,
    transaction_id          BIGINT NOT NULL REFERENCES qmeta.payment_transaction(transaction_id) ON DELETE CASCADE,
    invoice_id              BIGINT NOT NULL REFERENCES qmeta.invoice(invoice_id) ON DELETE CASCADE,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id              BIGINT REFERENCES qmeta.project(project_id),
    match_type              VARCHAR(32) NOT NULL,
    status                  VARCHAR(24) NOT NULL,
    currency                VARCHAR(16) NOT NULL DEFAULT 'CNY',
    matched_amount          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    base_currency           VARCHAR(16) NOT NULL DEFAULT 'CNY',
    fx_rate_to_base         NUMERIC(24, 12) NOT NULL DEFAULT 1,
    base_matched_amount     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    unmatched_amount        NUMERIC(24, 8) NOT NULL DEFAULT 0,
    match_score             NUMERIC(8, 6) NOT NULL DEFAULT 1,
    matched_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (transaction_id, invoice_id),
    CHECK (match_type IN ('auto_exact', 'auto_partial', 'auto_overpay', 'manual', 'rule_suggested')),
    CHECK (status IN ('matched', 'partial', 'overpaid', 'unmatched', 'reversed')),
    CHECK (matched_amount >= 0),
    CHECK (fx_rate_to_base > 0),
    CHECK (base_matched_amount >= 0),
    CHECK (unmatched_amount >= 0),
    CHECK (match_score >= 0 AND match_score <= 1)
);

CREATE INDEX IF NOT EXISTS idx_payment_invoice_match_status
    ON qmeta.payment_invoice_match(status, matched_at DESC);

CREATE INDEX IF NOT EXISTS idx_payment_invoice_match_invoice
    ON qmeta.payment_invoice_match(invoice_id, status, matched_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.revenue_ledger_entry (
    ledger_id               BIGSERIAL PRIMARY KEY,
    ledger_code             VARCHAR(240) NOT NULL UNIQUE,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id),
    project_id              BIGINT REFERENCES qmeta.project(project_id),
    invoice_id              BIGINT REFERENCES qmeta.invoice(invoice_id) ON DELETE SET NULL,
    transaction_id          BIGINT REFERENCES qmeta.payment_transaction(transaction_id) ON DELETE SET NULL,
    match_id                BIGINT REFERENCES qmeta.payment_invoice_match(match_id) ON DELETE SET NULL,
    entry_date              DATE NOT NULL,
    entry_type              VARCHAR(32) NOT NULL,
    currency                VARCHAR(16) NOT NULL DEFAULT 'CNY',
    debit_amount            NUMERIC(24, 8) NOT NULL DEFAULT 0,
    credit_amount           NUMERIC(24, 8) NOT NULL DEFAULT 0,
    balance_amount          NUMERIC(24, 8) NOT NULL DEFAULT 0,
    base_currency           VARCHAR(16) NOT NULL DEFAULT 'CNY',
    base_debit_amount       NUMERIC(24, 8) NOT NULL DEFAULT 0,
    base_credit_amount      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    base_balance_amount     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (entry_type IN ('invoice_issued', 'payment_received', 'payment_matched', 'payment_unmatched', 'refund', 'adjustment')),
    CHECK (debit_amount >= 0),
    CHECK (credit_amount >= 0),
    CHECK (balance_amount >= 0),
    CHECK (base_debit_amount >= 0),
    CHECK (base_credit_amount >= 0),
    CHECK (base_balance_amount >= 0)
);

CREATE INDEX IF NOT EXISTS idx_revenue_ledger_entry_date
    ON qmeta.revenue_ledger_entry(entry_date DESC, entry_type);

CREATE INDEX IF NOT EXISTS idx_revenue_ledger_entry_invoice
    ON qmeta.revenue_ledger_entry(invoice_id, entry_date DESC);

-- ============================================================
-- ClickHouse: market data and factor time series
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
-- Plain MergeTree intentionally preserves exact-key duplicates.  The read
-- path must detect equal data_version/calc_time conflicts and fail closed,
-- a replacing engine could erase that evidence during a background merge.
ENGINE = MergeTree
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

-- ----------------------------
-- Phi strategy engine metadata
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.strategy_policy (
    policy_id               BIGSERIAL PRIMARY KEY,
    policy_code             VARCHAR(160) NOT NULL UNIQUE,
    policy_name             VARCHAR(180) NOT NULL,
    domain                  VARCHAR(32) NOT NULL,
    subject_type            VARCHAR(32) NOT NULL,
    decision_type           VARCHAR(32) NOT NULL,
    default_action          VARCHAR(64) NOT NULL,
    status                  VARCHAR(24) NOT NULL DEFAULT 'active',
    severity_floor          VARCHAR(24) NOT NULL DEFAULT 'low',
    evaluation_cadence      VARCHAR(32) NOT NULL DEFAULT 'daily',
    owner                   VARCHAR(128),
    description             TEXT,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.strategy_run (
    run_id                  BIGSERIAL PRIMARY KEY,
    run_code                VARCHAR(200) NOT NULL UNIQUE,
    run_date                DATE NOT NULL,
    environment             VARCHAR(64) NOT NULL DEFAULT 'local',
    trigger_mode            VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                  VARCHAR(24) NOT NULL DEFAULT 'success',
    policy_count            INTEGER NOT NULL DEFAULT 0,
    signal_count            INTEGER NOT NULL DEFAULT 0,
    decision_count          INTEGER NOT NULL DEFAULT 0,
    escalation_count        INTEGER NOT NULL DEFAULT 0,
    highest_severity        VARCHAR(24) NOT NULL DEFAULT 'low',
    started_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at             TIMESTAMPTZ,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.strategy_signal (
    signal_id               BIGSERIAL PRIMARY KEY,
    run_id                  BIGINT NOT NULL REFERENCES qmeta.strategy_run(run_id) ON DELETE CASCADE,
    policy_id               BIGINT REFERENCES qmeta.strategy_policy(policy_id) ON DELETE SET NULL,
    signal_code             VARCHAR(240) NOT NULL UNIQUE,
    domain                  VARCHAR(32) NOT NULL,
    subject_type            VARCHAR(32) NOT NULL,
    subject_code            VARCHAR(200) NOT NULL,
    signal_type             VARCHAR(64) NOT NULL,
    severity                VARCHAR(24) NOT NULL,
    status                  VARCHAR(24) NOT NULL DEFAULT 'active',
    metric_name             VARCHAR(96),
    metric_value            NUMERIC(24, 8),
    threshold_value         NUMERIC(24, 8),
    score_delta             NUMERIC(10, 6) NOT NULL DEFAULT 0,
    source_table            VARCHAR(128),
    source_ref              VARCHAR(240),
    message                 TEXT NOT NULL,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.strategy_decision (
    decision_id             BIGSERIAL PRIMARY KEY,
    run_id                  BIGINT NOT NULL REFERENCES qmeta.strategy_run(run_id) ON DELETE CASCADE,
    policy_id               BIGINT REFERENCES qmeta.strategy_policy(policy_id) ON DELETE SET NULL,
    decision_code           VARCHAR(240) NOT NULL UNIQUE,
    domain                  VARCHAR(32) NOT NULL,
    subject_type            VARCHAR(32) NOT NULL,
    subject_code            VARCHAR(200) NOT NULL,
    decision_type           VARCHAR(32) NOT NULL,
    action                  VARCHAR(64) NOT NULL,
    status                  VARCHAR(24) NOT NULL,
    severity                VARCHAR(24) NOT NULL,
    confidence_score        NUMERIC(8, 6) NOT NULL DEFAULT 1,
    priority_score          NUMERIC(10, 6) NOT NULL DEFAULT 0,
    recommended_owner       VARCHAR(128),
    reason                  TEXT NOT NULL,
    signal_count            INTEGER NOT NULL DEFAULT 0,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    decided_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.strategy_escalation_event (
    escalation_id           BIGSERIAL PRIMARY KEY,
    event_code              VARCHAR(260) NOT NULL UNIQUE,
    run_id                  BIGINT NOT NULL REFERENCES qmeta.strategy_run(run_id) ON DELETE CASCADE,
    decision_id             BIGINT REFERENCES qmeta.strategy_decision(decision_id) ON DELETE CASCADE,
    signal_id               BIGINT REFERENCES qmeta.strategy_signal(signal_id) ON DELETE SET NULL,
    escalation_type         VARCHAR(64) NOT NULL,
    severity                VARCHAR(24) NOT NULL,
    status                  VARCHAR(24) NOT NULL DEFAULT 'open',
    owner                   VARCHAR(128),
    message                 TEXT NOT NULL,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------
-- Chi governance metadata
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.access_decision_audit (
    access_decision_id      BIGSERIAL PRIMARY KEY,
    decision_code           VARCHAR(220) NOT NULL UNIQUE,
    request_id              VARCHAR(128),
    token_id                BIGINT REFERENCES qmeta.api_token(token_id) ON DELETE SET NULL,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id) ON DELETE SET NULL,
    project_id              BIGINT REFERENCES qmeta.project(project_id) ON DELETE SET NULL,
    principal_id            BIGINT REFERENCES qmeta.principal(principal_id) ON DELETE SET NULL,
    dataset_id              BIGINT REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE SET NULL,
    access_id               BIGINT REFERENCES qmeta.dataset_access_policy(access_id) ON DELETE SET NULL,
    api_name                VARCHAR(128) NOT NULL DEFAULT 'manual',
    dataset_code            VARCHAR(128) NOT NULL,
    decision                VARCHAR(16) NOT NULL,
    required_access_level   VARCHAR(32) NOT NULL DEFAULT 'read',
    effective_access_level  VARCHAR(32),
    effective_scope         VARCHAR(32) NOT NULL DEFAULT 'none',
    requested_fields        TEXT[] NOT NULL DEFAULT '{}',
    denied_fields           TEXT[] NOT NULL DEFAULT '{}',
    reason                  TEXT,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    evaluated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.project_governance_snapshot (
    snapshot_id                 BIGSERIAL PRIMARY KEY,
    snapshot_code               VARCHAR(220) NOT NULL UNIQUE,
    snapshot_date               DATE NOT NULL,
    tenant_id                   BIGINT NOT NULL REFERENCES qmeta.tenant(tenant_id) ON DELETE CASCADE,
    project_id                  BIGINT NOT NULL REFERENCES qmeta.project(project_id) ON DELETE CASCADE,
    status                      VARCHAR(24) NOT NULL DEFAULT 'healthy',
    active_principal_count      INTEGER NOT NULL DEFAULT 0,
    active_token_count          INTEGER NOT NULL DEFAULT 0,
    dataset_policy_count        INTEGER NOT NULL DEFAULT 0,
    request_count_7d            BIGINT NOT NULL DEFAULT 0,
    failed_count_7d             BIGINT NOT NULL DEFAULT 0,
    error_rate_7d               NUMERIC(12, 8) NOT NULL DEFAULT 0,
    cost_units_7d               NUMERIC(24, 8) NOT NULL DEFAULT 0,
    denied_access_7d_count      BIGINT NOT NULL DEFAULT 0,
    budget_status               VARCHAR(24),
    budget_usage_pct            NUMERIC(12, 8),
    open_budget_alert_count     INTEGER NOT NULL DEFAULT 0,
    unpaid_invoice_count        INTEGER NOT NULL DEFAULT 0,
    overdue_invoice_count       INTEGER NOT NULL DEFAULT 0,
    open_governance_action_count INTEGER NOT NULL DEFAULT 0,
    risk_score                  NUMERIC(8, 4) NOT NULL DEFAULT 0,
    recommended_action          VARCHAR(64) NOT NULL DEFAULT 'monitor',
    details                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snapshot_date, project_id)
);

CREATE TABLE IF NOT EXISTS qmeta.governance_action (
    action_id               BIGSERIAL PRIMARY KEY,
    action_code             VARCHAR(240) NOT NULL UNIQUE,
    tenant_id               BIGINT REFERENCES qmeta.tenant(tenant_id) ON DELETE SET NULL,
    project_id              BIGINT REFERENCES qmeta.project(project_id) ON DELETE SET NULL,
    principal_id            BIGINT REFERENCES qmeta.principal(principal_id) ON DELETE SET NULL,
    token_id                BIGINT REFERENCES qmeta.api_token(token_id) ON DELETE SET NULL,
    dataset_id              BIGINT REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE SET NULL,
    snapshot_id             BIGINT REFERENCES qmeta.project_governance_snapshot(snapshot_id) ON DELETE SET NULL,
    action_type             VARCHAR(64) NOT NULL,
    severity                VARCHAR(24) NOT NULL DEFAULT 'medium',
    status                  VARCHAR(24) NOT NULL DEFAULT 'open',
    owner                   VARCHAR(128),
    reason                  TEXT NOT NULL,
    due_at                  TIMESTAMPTZ,
    details                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------
-- Psi automation metadata
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.automation_run (
    automation_run_id          BIGSERIAL PRIMARY KEY,
    run_code                   VARCHAR(220) NOT NULL UNIQUE,
    run_date                   DATE NOT NULL,
    environment                VARCHAR(64) NOT NULL DEFAULT 'local',
    trigger_mode               VARCHAR(32) NOT NULL DEFAULT 'manual',
    execution_mode             VARCHAR(24) NOT NULL DEFAULT 'dry_run',
    status                     VARCHAR(24) NOT NULL DEFAULT 'running',
    source_filter              JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_count               INTEGER NOT NULL DEFAULT 0,
    executable_count           INTEGER NOT NULL DEFAULT 0,
    executed_count             INTEGER NOT NULL DEFAULT 0,
    approval_required_count    INTEGER NOT NULL DEFAULT 0,
    skipped_count              INTEGER NOT NULL DEFAULT 0,
    failed_count               INTEGER NOT NULL DEFAULT 0,
    started_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                TIMESTAMPTZ,
    duration_ms                INTEGER,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_action (
    automation_action_id       BIGSERIAL PRIMARY KEY,
    action_code                VARCHAR(260) NOT NULL UNIQUE,
    automation_run_id          BIGINT NOT NULL REFERENCES qmeta.automation_run(automation_run_id) ON DELETE CASCADE,
    source_type                VARCHAR(32) NOT NULL,
    source_id                  BIGINT,
    source_code                VARCHAR(260) NOT NULL,
    tenant_id                  BIGINT REFERENCES qmeta.tenant(tenant_id) ON DELETE SET NULL,
    project_id                 BIGINT REFERENCES qmeta.project(project_id) ON DELETE SET NULL,
    principal_id               BIGINT REFERENCES qmeta.principal(principal_id) ON DELETE SET NULL,
    token_id                   BIGINT REFERENCES qmeta.api_token(token_id) ON DELETE SET NULL,
    dataset_id                 BIGINT REFERENCES qmeta.dataset_catalog(dataset_id) ON DELETE SET NULL,
    action_type                VARCHAR(64) NOT NULL,
    safety_level               VARCHAR(24) NOT NULL DEFAULT 'medium',
    execution_mode             VARCHAR(24) NOT NULL DEFAULT 'dry_run',
    status                     VARCHAR(24) NOT NULL DEFAULT 'planned',
    approval_required          BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by                VARCHAR(128),
    approved_at                TIMESTAMPTZ,
    owner                      VARCHAR(128),
    reason                     TEXT NOT NULL,
    idempotency_key            VARCHAR(260) NOT NULL,
    planned_effect             JSONB NOT NULL DEFAULT '{}'::jsonb,
    executed_effect            JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollback_hint              TEXT,
    error_message              TEXT,
    executed_at                TIMESTAMPTZ,
    omega_control_status       VARCHAR(32) NOT NULL DEFAULT 'none',
    executor_code              VARCHAR(128),
    retry_count                INTEGER NOT NULL DEFAULT 0,
    max_retry_count            INTEGER NOT NULL DEFAULT 0,
    next_retry_at              TIMESTAMPTZ,
    rollback_required          BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_plan              JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (automation_run_id, idempotency_key)
);

-- ----------------------------
-- Omega automation control
-- ----------------------------

CREATE TABLE IF NOT EXISTS qmeta.automation_executor (
    executor_id                BIGSERIAL PRIMARY KEY,
    executor_code              VARCHAR(128) NOT NULL UNIQUE,
    executor_name              VARCHAR(220) NOT NULL,
    executor_type              VARCHAR(32) NOT NULL DEFAULT 'noop',
    action_type                VARCHAR(64) NOT NULL,
    safety_level               VARCHAR(24) NOT NULL DEFAULT 'medium',
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    requires_approval          BOOLEAN NOT NULL DEFAULT FALSE,
    max_retry_count            INTEGER NOT NULL DEFAULT 1,
    retry_backoff_seconds      INTEGER NOT NULL DEFAULT 60,
    timeout_seconds            INTEGER NOT NULL DEFAULT 30,
    endpoint_url               TEXT,
    command_name               VARCHAR(220),
    sandbox_mode               BOOLEAN NOT NULL DEFAULT TRUE,
    allowlist_code             VARCHAR(128),
    secret_ref                 VARCHAR(128),
    signing_algorithm          VARCHAR(32) NOT NULL DEFAULT 'none',
    allowed_target             TEXT,
    config                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_executor_allowlist (
    allowlist_id               BIGSERIAL PRIMARY KEY,
    allowlist_code             VARCHAR(128) NOT NULL UNIQUE,
    executor_type              VARCHAR(32) NOT NULL,
    target_pattern             TEXT NOT NULL,
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    sandbox_only               BOOLEAN NOT NULL DEFAULT TRUE,
    max_timeout_seconds        INTEGER NOT NULL DEFAULT 10,
    description                TEXT,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_secret_ref (
    secret_id                  BIGSERIAL PRIMARY KEY,
    secret_ref                 VARCHAR(128) NOT NULL UNIQUE,
    secret_scope               VARCHAR(64) NOT NULL DEFAULT 'automation',
    secret_kind                VARCHAR(32) NOT NULL DEFAULT 'hmac',
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    owner                      VARCHAR(128),
    description                TEXT,
    metadata                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_external_channel (
    channel_id                 BIGSERIAL PRIMARY KEY,
    channel_code               VARCHAR(128) NOT NULL UNIQUE,
    channel_name               VARCHAR(220) NOT NULL,
    channel_type               VARCHAR(32) NOT NULL,
    environment                VARCHAR(32) NOT NULL DEFAULT 'local',
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    endpoint_url               TEXT,
    allowlist_code             VARCHAR(128),
    secret_ref                 VARCHAR(128),
    signing_algorithm          VARCHAR(32) NOT NULL DEFAULT 'none',
    timeout_seconds            INTEGER NOT NULL DEFAULT 10,
    max_retry_count            INTEGER NOT NULL DEFAULT 2,
    retry_backoff_seconds      INTEGER NOT NULL DEFAULT 60,
    duplicate_window_seconds   INTEGER NOT NULL DEFAULT 300,
    owner                      VARCHAR(128),
    runbook_code               VARCHAR(128),
    config                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_external_dispatch (
    dispatch_id                BIGSERIAL PRIMARY KEY,
    dispatch_code              VARCHAR(260) NOT NULL UNIQUE,
    automation_action_id       BIGINT NOT NULL REFERENCES qmeta.automation_action(automation_action_id) ON DELETE CASCADE,
    attempt_id                 BIGINT REFERENCES qmeta.automation_execution_attempt(attempt_id) ON DELETE SET NULL,
    channel_id                 BIGINT NOT NULL REFERENCES qmeta.automation_external_channel(channel_id) ON DELETE CASCADE,
    executor_id                BIGINT REFERENCES qmeta.automation_executor(executor_id) ON DELETE SET NULL,
    idempotency_key            VARCHAR(280) NOT NULL,
    dispatch_type              VARCHAR(32) NOT NULL DEFAULT 'notification',
    trigger_mode               VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                     VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL DEFAULT 'beta2',
    request_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    retry_count                INTEGER NOT NULL DEFAULT 0,
    max_retry_count            INTEGER NOT NULL DEFAULT 0,
    next_retry_at              TIMESTAMPTZ,
    dispatched_at              TIMESTAMPTZ,
    acknowledged_at            TIMESTAMPTZ,
    recovered_at               TIMESTAMPTZ,
    recovered_by               VARCHAR(128),
    recovery_reason            TEXT,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_recovery_runbook (
    runbook_id                 BIGSERIAL PRIMARY KEY,
    runbook_code               VARCHAR(128) NOT NULL UNIQUE,
    runbook_name               VARCHAR(220) NOT NULL,
    failure_class              VARCHAR(64) NOT NULL,
    severity                   VARCHAR(24) NOT NULL DEFAULT 'medium',
    status                     VARCHAR(24) NOT NULL DEFAULT 'active',
    owner                      VARCHAR(128),
    recovery_steps             JSONB NOT NULL DEFAULT '[]'::jsonb,
    rollback_steps             JSONB NOT NULL DEFAULT '[]'::jsonb,
    drill_frequency_days       INTEGER NOT NULL DEFAULT 30,
    last_drill_at              TIMESTAMPTZ,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_channel_profile (
    profile_id                 BIGSERIAL PRIMARY KEY,
    profile_code               VARCHAR(128) NOT NULL UNIQUE,
    channel_id                 BIGINT NOT NULL REFERENCES qmeta.automation_external_channel(channel_id) ON DELETE CASCADE,
    provider_code              VARCHAR(64) NOT NULL,
    environment                VARCHAR(32) NOT NULL DEFAULT 'local',
    profile_status             VARCHAR(24) NOT NULL DEFAULT 'active',
    readiness_status           VARCHAR(32) NOT NULL DEFAULT 'not_configured',
    dry_run_only               BOOLEAN NOT NULL DEFAULT TRUE,
    endpoint_url               TEXT,
    dry_run_endpoint_url       TEXT,
    live_endpoint_url          TEXT,
    allowlist_code             VARCHAR(128),
    secret_ref                 VARCHAR(128),
    next_secret_ref            VARCHAR(128),
    signing_algorithm          VARCHAR(32) NOT NULL DEFAULT 'none',
    owner                      VARCHAR(128),
    runbook_code               VARCHAR(128),
    last_validation_code       VARCHAR(160),
    last_validation_status     VARCHAR(32),
    last_validated_at          TIMESTAMPTZ,
    config                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_channel_validation (
    validation_id              BIGSERIAL PRIMARY KEY,
    validation_code            VARCHAR(160) NOT NULL UNIQUE,
    profile_id                 BIGINT NOT NULL REFERENCES qmeta.automation_channel_profile(profile_id) ON DELETE CASCADE,
    channel_id                 BIGINT NOT NULL REFERENCES qmeta.automation_external_channel(channel_id) ON DELETE CASCADE,
    dispatch_id                BIGINT REFERENCES qmeta.automation_external_dispatch(dispatch_id) ON DELETE SET NULL,
    validation_type            VARCHAR(40) NOT NULL DEFAULT 'dry_run_dispatch',
    trigger_mode               VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                     VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL DEFAULT 'gamma2',
    target_secret_ref          VARCHAR(128),
    request_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    started_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                TIMESTAMPTZ,
    duration_ms                INTEGER NOT NULL DEFAULT 0,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_secret_rotation (
    rotation_id                BIGSERIAL PRIMARY KEY,
    rotation_code              VARCHAR(160) NOT NULL UNIQUE,
    environment                VARCHAR(32) NOT NULL DEFAULT 'local',
    secret_ref                 VARCHAR(128) NOT NULL,
    next_secret_ref            VARCHAR(128) NOT NULL,
    rotation_type              VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                     VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL DEFAULT 'gamma2',
    approved_by                VARCHAR(128),
    reason                     TEXT,
    profile_id                 BIGINT REFERENCES qmeta.automation_channel_profile(profile_id) ON DELETE SET NULL,
    validation_id              BIGINT REFERENCES qmeta.automation_channel_validation(validation_id) ON DELETE SET NULL,
    affected_channel_count     INTEGER NOT NULL DEFAULT 0,
    validated_at               TIMESTAMPTZ,
    applied_at                 TIMESTAMPTZ,
    rolled_back_at             TIMESTAMPTZ,
    rolled_back_by             VARCHAR(128),
    rollback_reason            TEXT,
    error_message              TEXT,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_live_provider_receipt (
    receipt_id                 BIGSERIAL PRIMARY KEY,
    receipt_code               VARCHAR(180) NOT NULL UNIQUE,
    validation_id              BIGINT REFERENCES qmeta.automation_channel_validation(validation_id) ON DELETE SET NULL,
    profile_id                 BIGINT REFERENCES qmeta.automation_channel_profile(profile_id) ON DELETE SET NULL,
    channel_id                 BIGINT REFERENCES qmeta.automation_external_channel(channel_id) ON DELETE SET NULL,
    provider_code              VARCHAR(64) NOT NULL,
    environment                VARCHAR(32) NOT NULL DEFAULT 'live_test',
    message_type               VARCHAR(32) NOT NULL DEFAULT 'markdown',
    status                     VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL DEFAULT 'delta2',
    endpoint_secret_ref        VARCHAR(128),
    provider_status_code       INTEGER,
    provider_errcode           INTEGER,
    provider_errmsg            TEXT,
    request_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    sent_at                    TIMESTAMPTZ,
    acknowledged_at            TIMESTAMPTZ,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_approval (
    approval_id                BIGSERIAL PRIMARY KEY,
    approval_code              VARCHAR(260) NOT NULL UNIQUE,
    automation_action_id       BIGINT NOT NULL REFERENCES qmeta.automation_action(automation_action_id) ON DELETE CASCADE,
    status                     VARCHAR(24) NOT NULL DEFAULT 'pending',
    requested_by               VARCHAR(128) NOT NULL,
    requested_reason           TEXT NOT NULL,
    requested_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at                 TIMESTAMPTZ,
    decided_by                 VARCHAR(128),
    decision_reason            TEXT,
    decided_at                 TIMESTAMPTZ,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.automation_execution_attempt (
    attempt_id                 BIGSERIAL PRIMARY KEY,
    attempt_code               VARCHAR(280) NOT NULL UNIQUE,
    automation_action_id       BIGINT NOT NULL REFERENCES qmeta.automation_action(automation_action_id) ON DELETE CASCADE,
    executor_id                BIGINT REFERENCES qmeta.automation_executor(executor_id) ON DELETE SET NULL,
    attempt_no                 INTEGER NOT NULL DEFAULT 1,
    trigger_mode               VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                     VARCHAR(32) NOT NULL DEFAULT 'queued',
    request_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message              TEXT,
    retry_count                INTEGER NOT NULL DEFAULT 0,
    max_retry_count            INTEGER NOT NULL DEFAULT 0,
    next_retry_at              TIMESTAMPTZ,
    started_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                TIMESTAMPTZ,
    duration_ms                INTEGER,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (automation_action_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS qmeta.automation_rollback (
    rollback_id                BIGSERIAL PRIMARY KEY,
    rollback_code              VARCHAR(280) NOT NULL UNIQUE,
    automation_action_id       BIGINT NOT NULL REFERENCES qmeta.automation_action(automation_action_id) ON DELETE CASCADE,
    attempt_id                 BIGINT REFERENCES qmeta.automation_execution_attempt(attempt_id) ON DELETE SET NULL,
    rollback_type              VARCHAR(32) NOT NULL DEFAULT 'noop',
    status                     VARCHAR(24) NOT NULL DEFAULT 'planned',
    requested_by               VARCHAR(128) NOT NULL,
    executed_by                VARCHAR(128),
    reason                     TEXT NOT NULL,
    rollback_plan              JSONB NOT NULL DEFAULT '{}'::jsonb,
    rollback_result            JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_at                TIMESTAMPTZ,
    error_message              TEXT,
    details                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.vendor_live_gate_run (
    gate_id                  BIGSERIAL PRIMARY KEY,
    gate_code                VARCHAR(180) NOT NULL UNIQUE,
    dataset_id               BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id                BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id        BIGINT REFERENCES qmeta.source_system(source_id),
    profile_id               BIGINT REFERENCES qmeta.vendor_integration_profile(profile_id) ON DELETE SET NULL,
    review_id                BIGINT REFERENCES qmeta.vendor_readiness_review(review_id) ON DELETE SET NULL,
    requested_by             VARCHAR(128) NOT NULL DEFAULT 'epsilon3',
    trigger_mode             VARCHAR(32) NOT NULL DEFAULT 'manual',
    run_mode                 VARCHAR(32) NOT NULL DEFAULT 'blocked',
    status                   VARCHAR(32) NOT NULL DEFAULT 'planned',
    start_date               DATE NOT NULL,
    end_date                 DATE NOT NULL,
    required_windows         INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    executed_windows         INTEGER[] NOT NULL DEFAULT '{}',
    shard_size               INTEGER NOT NULL DEFAULT 500,
    max_symbols              INTEGER,
    symbol_count             BIGINT,
    allow_live               BOOLEAN NOT NULL DEFAULT FALSE,
    require_live             BOOLEAN NOT NULL DEFAULT FALSE,
    require_active_profile   BOOLEAN NOT NULL DEFAULT TRUE,
    require_contract         BOOLEAN NOT NULL DEFAULT TRUE,
    run_benchmarks           BOOLEAN NOT NULL DEFAULT FALSE,
    live_base_url_env        VARCHAR(128) NOT NULL DEFAULT 'QDATA_VENDOR_BASE_URL',
    live_token_env           VARCHAR(128) NOT NULL DEFAULT 'QDATA_VENDOR_TOKEN',
    live_base_url_present    BOOLEAN NOT NULL DEFAULT FALSE,
    live_token_present       BOOLEAN NOT NULL DEFAULT FALSE,
    profile_status           VARCHAR(24),
    runtime_mode             VARCHAR(32) NOT NULL DEFAULT 'unknown',
    review_code              VARCHAR(180),
    readiness_status         VARCHAR(24),
    recommendation           VARCHAR(32),
    recommended_role         VARCHAR(32),
    suite_ids                BIGINT[] NOT NULL DEFAULT '{}',
    suite_codes              TEXT[] NOT NULL DEFAULT '{}',
    blocking_issues          TEXT[] NOT NULL DEFAULT '{}',
    next_actions             TEXT[] NOT NULL DEFAULT '{}',
    request_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message            TEXT,
    started_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at              TIMESTAMPTZ,
    duration_ms              INTEGER,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qmeta.vendor_onboarding_run (
    run_id                    BIGSERIAL PRIMARY KEY,
    run_code                  VARCHAR(180) NOT NULL UNIQUE,
    source_id                 BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    profile_id                BIGINT REFERENCES qmeta.vendor_integration_profile(profile_id) ON DELETE SET NULL,
    primary_source_id         BIGINT REFERENCES qmeta.source_system(source_id),
    requested_by              VARCHAR(128) NOT NULL DEFAULT 'zeta3',
    trigger_mode              VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment               VARCHAR(32) NOT NULL DEFAULT 'local',
    status                    VARCHAR(32) NOT NULL DEFAULT 'planned',
    preflight_status          VARCHAR(32) NOT NULL DEFAULT 'planned',
    canary_status             VARCHAR(32) NOT NULL DEFAULT 'planned',
    gate_status               VARCHAR(32) NOT NULL DEFAULT 'planned',
    orchestration_status      VARCHAR(32) NOT NULL DEFAULT 'planned',
    recommendation            VARCHAR(32) NOT NULL DEFAULT 'research_only',
    recommended_role          VARCHAR(32) NOT NULL DEFAULT 'research_only',
    dataset_codes             TEXT[] NOT NULL DEFAULT '{}',
    canary_symbols            TEXT[] NOT NULL DEFAULT '{}',
    required_windows          INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    shard_size                INTEGER NOT NULL DEFAULT 500,
    max_symbols               INTEGER,
    allow_live                BOOLEAN NOT NULL DEFAULT FALSE,
    require_live              BOOLEAN NOT NULL DEFAULT FALSE,
    require_active_profile    BOOLEAN NOT NULL DEFAULT TRUE,
    require_contract          BOOLEAN NOT NULL DEFAULT TRUE,
    run_canary                BOOLEAN NOT NULL DEFAULT TRUE,
    run_gates                 BOOLEAN NOT NULL DEFAULT TRUE,
    run_benchmarks            BOOLEAN NOT NULL DEFAULT FALSE,
    full_market               BOOLEAN NOT NULL DEFAULT FALSE,
    live_base_url_env         VARCHAR(128) NOT NULL DEFAULT 'QDATA_VENDOR_BASE_URL',
    live_token_env            VARCHAR(128) NOT NULL DEFAULT 'QDATA_VENDOR_TOKEN',
    live_base_url_present     BOOLEAN NOT NULL DEFAULT FALSE,
    live_token_present        BOOLEAN NOT NULL DEFAULT FALSE,
    auth_mode                 VARCHAR(32),
    profile_status            VARCHAR(24),
    contract_status           VARCHAR(32) NOT NULL DEFAULT 'unknown',
    redistribution_allowed    BOOLEAN,
    rate_limit_per_min        INTEGER,
    gate_ids                  BIGINT[] NOT NULL DEFAULT '{}',
    gate_codes                TEXT[] NOT NULL DEFAULT '{}',
    blocking_issues           TEXT[] NOT NULL DEFAULT '{}',
    next_actions              TEXT[] NOT NULL DEFAULT '{}',
    request_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message             TEXT,
    started_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at               TIMESTAMPTZ,
    duration_ms               INTEGER,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (preflight_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (canary_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (gate_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (orchestration_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (recommendation IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (recommended_role IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (array_length(dataset_codes, 1) IS NOT NULL),
    CHECK (array_length(required_windows, 1) IS NOT NULL),
    CHECK (shard_size > 0),
    CHECK (max_symbols IS NULL OR max_symbols > 0),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0)
);

CREATE TABLE IF NOT EXISTS qmeta.vendor_onboarding_dataset_result (
    result_id                 BIGSERIAL PRIMARY KEY,
    run_id                    BIGINT NOT NULL REFERENCES qmeta.vendor_onboarding_run(run_id) ON DELETE CASCADE,
    dataset_id                BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id                 BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id         BIGINT REFERENCES qmeta.source_system(source_id),
    gate_id                   BIGINT REFERENCES qmeta.vendor_live_gate_run(gate_id) ON DELETE SET NULL,
    stage_status              VARCHAR(32) NOT NULL DEFAULT 'planned',
    preflight_status          VARCHAR(32) NOT NULL DEFAULT 'planned',
    canary_status             VARCHAR(32) NOT NULL DEFAULT 'planned',
    gate_status               VARCHAR(32) NOT NULL DEFAULT 'planned',
    recommendation            VARCHAR(32) NOT NULL DEFAULT 'research_only',
    recommended_role          VARCHAR(32) NOT NULL DEFAULT 'research_only',
    required_windows          INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    executed_windows          INTEGER[] NOT NULL DEFAULT '{}',
    shard_size                INTEGER NOT NULL DEFAULT 500,
    max_symbols               INTEGER,
    symbol_count              BIGINT,
    live_requested            BOOLEAN NOT NULL DEFAULT FALSE,
    live_executed             BOOLEAN NOT NULL DEFAULT FALSE,
    blocking_issues           TEXT[] NOT NULL DEFAULT '{}',
    next_actions              TEXT[] NOT NULL DEFAULT '{}',
    evidence                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message             TEXT,
    started_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at               TIMESTAMPTZ,
    duration_ms               INTEGER,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, dataset_id),
    CHECK (stage_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (preflight_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (canary_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (gate_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (recommendation IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (recommended_role IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (array_length(required_windows, 1) IS NOT NULL),
    CHECK (shard_size > 0),
    CHECK (max_symbols IS NULL OR max_symbols > 0),
    CHECK (symbol_count IS NULL OR symbol_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_onboarding_run_lookup
    ON qmeta.vendor_onboarding_run(source_id, started_at DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_onboarding_run_status
    ON qmeta.vendor_onboarding_run(status, recommendation, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_onboarding_dataset_lookup
    ON qmeta.vendor_onboarding_dataset_result(run_id, dataset_id, stage_status);

CREATE INDEX IF NOT EXISTS idx_vendor_onboarding_dataset_status
    ON qmeta.vendor_onboarding_dataset_result(stage_status, gate_status, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_live_closure_run (
    closure_id                BIGSERIAL PRIMARY KEY,
    closure_code              VARCHAR(180) NOT NULL UNIQUE,
    source_id                 BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    profile_id                BIGINT REFERENCES qmeta.vendor_integration_profile(profile_id) ON DELETE SET NULL,
    primary_source_id         BIGINT REFERENCES qmeta.source_system(source_id),
    onboarding_run_id         BIGINT REFERENCES qmeta.vendor_onboarding_run(run_id) ON DELETE SET NULL,
    requested_by              VARCHAR(128) NOT NULL DEFAULT 'eta3',
    trigger_mode              VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment               VARCHAR(32) NOT NULL DEFAULT 'local',
    status                    VARCHAR(32) NOT NULL DEFAULT 'planned',
    config_status             VARCHAR(32) NOT NULL DEFAULT 'planned',
    profile_check_status      VARCHAR(32) NOT NULL DEFAULT 'planned',
    profile_update_status     VARCHAR(32) NOT NULL DEFAULT 'skipped',
    contract_status           VARCHAR(32) NOT NULL DEFAULT 'unknown',
    endpoint_status           VARCHAR(32) NOT NULL DEFAULT 'planned',
    onboarding_status         VARCHAR(32) NOT NULL DEFAULT 'planned',
    promotion_status          VARCHAR(32) NOT NULL DEFAULT 'planned',
    recommendation            VARCHAR(32) NOT NULL DEFAULT 'research_only',
    recommended_role          VARCHAR(32) NOT NULL DEFAULT 'research_only',
    dataset_codes             TEXT[] NOT NULL DEFAULT '{}',
    enabled_dataset_codes     TEXT[] NOT NULL DEFAULT '{}',
    missing_dataset_codes     TEXT[] NOT NULL DEFAULT '{}',
    canary_symbols            TEXT[] NOT NULL DEFAULT '{}',
    required_windows          INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    shard_size                INTEGER NOT NULL DEFAULT 500,
    max_symbols               INTEGER,
    allow_live                BOOLEAN NOT NULL DEFAULT FALSE,
    require_live              BOOLEAN NOT NULL DEFAULT FALSE,
    allow_profile_write       BOOLEAN NOT NULL DEFAULT FALSE,
    activate_profile          BOOLEAN NOT NULL DEFAULT FALSE,
    enable_profile_datasets   BOOLEAN NOT NULL DEFAULT FALSE,
    run_endpoint_probes       BOOLEAN NOT NULL DEFAULT TRUE,
    run_onboarding            BOOLEAN NOT NULL DEFAULT TRUE,
    run_benchmarks            BOOLEAN NOT NULL DEFAULT FALSE,
    full_market               BOOLEAN NOT NULL DEFAULT FALSE,
    live_base_url_env         VARCHAR(128) NOT NULL DEFAULT 'QDATA_VENDOR_BASE_URL',
    live_token_env            VARCHAR(128) NOT NULL DEFAULT 'QDATA_VENDOR_TOKEN',
    live_base_url_present     BOOLEAN NOT NULL DEFAULT FALSE,
    live_token_present        BOOLEAN NOT NULL DEFAULT FALSE,
    auth_mode                 VARCHAR(32),
    profile_status            VARCHAR(24),
    profile_contract_ref_present BOOLEAN NOT NULL DEFAULT FALSE,
    redistribution_allowed    BOOLEAN,
    rate_limit_per_min        INTEGER,
    endpoint_probe_count      INTEGER NOT NULL DEFAULT 0,
    endpoint_probe_success_count INTEGER NOT NULL DEFAULT 0,
    endpoint_probe_blocked_count INTEGER NOT NULL DEFAULT 0,
    endpoint_probe_failed_count INTEGER NOT NULL DEFAULT 0,
    onboarding_run_code       VARCHAR(180),
    gate_ids                  BIGINT[] NOT NULL DEFAULT '{}',
    gate_codes                TEXT[] NOT NULL DEFAULT '{}',
    blocking_issues           TEXT[] NOT NULL DEFAULT '{}',
    next_actions              TEXT[] NOT NULL DEFAULT '{}',
    request_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message             TEXT,
    started_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at               TIMESTAMPTZ,
    duration_ms               INTEGER,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (config_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (profile_check_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (profile_update_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (endpoint_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (onboarding_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (promotion_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (contract_status IN ('unknown', 'missing', 'contracted', 'skipped')),
    CHECK (recommendation IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (recommended_role IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (array_length(dataset_codes, 1) IS NOT NULL),
    CHECK (array_length(required_windows, 1) IS NOT NULL),
    CHECK (shard_size > 0),
    CHECK (max_symbols IS NULL OR max_symbols > 0),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (endpoint_probe_count >= 0),
    CHECK (endpoint_probe_success_count >= 0),
    CHECK (endpoint_probe_blocked_count >= 0),
    CHECK (endpoint_probe_failed_count >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.vendor_live_endpoint_probe (
    probe_id                  BIGSERIAL PRIMARY KEY,
    probe_code                VARCHAR(180) NOT NULL UNIQUE,
    closure_id                BIGINT NOT NULL REFERENCES qmeta.vendor_live_closure_run(closure_id) ON DELETE CASCADE,
    dataset_id                BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id                 BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    status                    VARCHAR(32) NOT NULL DEFAULT 'planned',
    auth_status               VARCHAR(32) NOT NULL DEFAULT 'planned',
    schema_status             VARCHAR(32) NOT NULL DEFAULT 'planned',
    endpoint_path             VARCHAR(256) NOT NULL,
    method                    VARCHAR(16) NOT NULL DEFAULT 'GET',
    live_requested            BOOLEAN NOT NULL DEFAULT FALSE,
    live_executed             BOOLEAN NOT NULL DEFAULT FALSE,
    http_status_code          INTEGER,
    row_count                 INTEGER,
    expected_fields           TEXT[] NOT NULL DEFAULT '{}',
    observed_fields           TEXT[] NOT NULL DEFAULT '{}',
    missing_fields            TEXT[] NOT NULL DEFAULT '{}',
    latency_ms                INTEGER,
    request_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message             TEXT,
    started_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at               TIMESTAMPTZ,
    duration_ms               INTEGER,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (auth_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (schema_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (method IN ('GET', 'POST')),
    CHECK (http_status_code IS NULL OR http_status_code >= 100),
    CHECK (row_count IS NULL OR row_count >= 0),
    CHECK (latency_ms IS NULL OR latency_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_live_closure_lookup
    ON qmeta.vendor_live_closure_run(source_id, started_at DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_live_closure_status
    ON qmeta.vendor_live_closure_run(status, recommendation, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_live_probe_closure
    ON qmeta.vendor_live_endpoint_probe(closure_id, dataset_id, status);

CREATE INDEX IF NOT EXISTS idx_vendor_live_probe_status
    ON qmeta.vendor_live_endpoint_probe(status, schema_status, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_live_pilot_run (
    pilot_id                 BIGSERIAL PRIMARY KEY,
    pilot_code               VARCHAR(180) NOT NULL UNIQUE,
    source_id                BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id        BIGINT REFERENCES qmeta.source_system(source_id),
    closure_id               BIGINT REFERENCES qmeta.vendor_live_closure_run(closure_id) ON DELETE SET NULL,
    closure_code             VARCHAR(180),
    requested_by             VARCHAR(128) NOT NULL DEFAULT 'theta3',
    trigger_mode             VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment              VARCHAR(32) NOT NULL DEFAULT 'local',
    pilot_scope              VARCHAR(32) NOT NULL DEFAULT 'canary',
    status                   VARCHAR(32) NOT NULL DEFAULT 'planned',
    closure_status           VARCHAR(32) NOT NULL DEFAULT 'planned',
    endpoint_status          VARCHAR(32) NOT NULL DEFAULT 'planned',
    onboarding_status        VARCHAR(32) NOT NULL DEFAULT 'planned',
    benchmark_status         VARCHAR(32) NOT NULL DEFAULT 'skipped',
    signoff_status           VARCHAR(32) NOT NULL DEFAULT 'not_ready',
    recommendation           VARCHAR(32) NOT NULL DEFAULT 'research_only',
    recommended_role         VARCHAR(32) NOT NULL DEFAULT 'research_only',
    risk_level               VARCHAR(16) NOT NULL DEFAULT 'unknown',
    dataset_codes            TEXT[] NOT NULL DEFAULT '{}',
    canary_symbols           TEXT[] NOT NULL DEFAULT '{}',
    required_windows         INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    shard_size               INTEGER NOT NULL DEFAULT 500,
    max_symbols              INTEGER,
    allow_live               BOOLEAN NOT NULL DEFAULT FALSE,
    require_live             BOOLEAN NOT NULL DEFAULT FALSE,
    run_endpoint_probes      BOOLEAN NOT NULL DEFAULT TRUE,
    run_onboarding           BOOLEAN NOT NULL DEFAULT TRUE,
    run_benchmarks           BOOLEAN NOT NULL DEFAULT FALSE,
    full_market              BOOLEAN NOT NULL DEFAULT FALSE,
    live_base_url_present    BOOLEAN NOT NULL DEFAULT FALSE,
    live_token_present       BOOLEAN NOT NULL DEFAULT FALSE,
    dataset_result_count     INTEGER NOT NULL DEFAULT 0,
    dataset_success_count    INTEGER NOT NULL DEFAULT 0,
    dataset_warning_count    INTEGER NOT NULL DEFAULT 0,
    dataset_blocked_count    INTEGER NOT NULL DEFAULT 0,
    dataset_failed_count     INTEGER NOT NULL DEFAULT 0,
    blocking_issues          TEXT[] NOT NULL DEFAULT '{}',
    next_actions             TEXT[] NOT NULL DEFAULT '{}',
    request_payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message            TEXT,
    started_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at              TIMESTAMPTZ,
    duration_ms              INTEGER,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (pilot_scope IN ('canary', 'full_market')),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (closure_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (endpoint_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (onboarding_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (benchmark_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (signoff_status IN ('not_ready', 'pending_review', 'approved', 'rejected', 'skipped')),
    CHECK (recommendation IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (recommended_role IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (risk_level IN ('unknown', 'low', 'medium', 'high', 'critical')),
    CHECK (array_length(dataset_codes, 1) IS NOT NULL),
    CHECK (array_length(required_windows, 1) IS NOT NULL),
    CHECK (shard_size > 0),
    CHECK (max_symbols IS NULL OR max_symbols > 0),
    CHECK (dataset_result_count >= 0),
    CHECK (dataset_success_count >= 0),
    CHECK (dataset_warning_count >= 0),
    CHECK (dataset_blocked_count >= 0),
    CHECK (dataset_failed_count >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.vendor_live_pilot_dataset_result (
    result_id                BIGSERIAL PRIMARY KEY,
    result_code              VARCHAR(180) NOT NULL UNIQUE,
    pilot_id                 BIGINT NOT NULL REFERENCES qmeta.vendor_live_pilot_run(pilot_id) ON DELETE CASCADE,
    dataset_id               BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    source_id                BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    closure_id               BIGINT REFERENCES qmeta.vendor_live_closure_run(closure_id) ON DELETE SET NULL,
    probe_code               VARCHAR(180),
    gate_code                VARCHAR(180),
    status                   VARCHAR(32) NOT NULL DEFAULT 'planned',
    closure_status           VARCHAR(32) NOT NULL DEFAULT 'planned',
    endpoint_status          VARCHAR(32) NOT NULL DEFAULT 'planned',
    schema_status            VARCHAR(32) NOT NULL DEFAULT 'planned',
    onboarding_status        VARCHAR(32) NOT NULL DEFAULT 'planned',
    gate_status              VARCHAR(32) NOT NULL DEFAULT 'planned',
    benchmark_status         VARCHAR(32) NOT NULL DEFAULT 'skipped',
    recommendation           VARCHAR(32) NOT NULL DEFAULT 'research_only',
    recommended_role         VARCHAR(32) NOT NULL DEFAULT 'research_only',
    risk_level               VARCHAR(16) NOT NULL DEFAULT 'unknown',
    live_requested           BOOLEAN NOT NULL DEFAULT FALSE,
    live_executed            BOOLEAN NOT NULL DEFAULT FALSE,
    row_count                INTEGER,
    missing_fields           TEXT[] NOT NULL DEFAULT '{}',
    blocking_issues          TEXT[] NOT NULL DEFAULT '{}',
    next_actions             TEXT[] NOT NULL DEFAULT '{}',
    evidence                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message            TEXT,
    started_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at              TIMESTAMPTZ,
    duration_ms              INTEGER,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (closure_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (endpoint_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (schema_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (onboarding_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (gate_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (benchmark_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (recommendation IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (recommended_role IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (risk_level IN ('unknown', 'low', 'medium', 'high', 'critical')),
    CHECK (row_count IS NULL OR row_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_live_pilot_lookup
    ON qmeta.vendor_live_pilot_run(source_id, started_at DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_live_pilot_status
    ON qmeta.vendor_live_pilot_run(status, signoff_status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_live_pilot_result_lookup
    ON qmeta.vendor_live_pilot_dataset_result(pilot_id, dataset_id, status);

CREATE INDEX IF NOT EXISTS idx_vendor_live_pilot_result_status
    ON qmeta.vendor_live_pilot_dataset_result(status, risk_level, started_at DESC);

-- A 股量化数据平台 Iota-3：免费源联盟 Free Source Fabric

CREATE TABLE IF NOT EXISTS qmeta.free_source_fabric_run (
    fabric_id                       BIGSERIAL PRIMARY KEY,
    fabric_code                     VARCHAR(180) NOT NULL UNIQUE,
    requested_by                    VARCHAR(128) NOT NULL DEFAULT 'iota3',
    trigger_mode                    VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                     VARCHAR(32) NOT NULL DEFAULT 'local',
    fabric_scope                    VARCHAR(32) NOT NULL DEFAULT 'canary',
    status                          VARCHAR(32) NOT NULL DEFAULT 'planned',
    recommendation                  VARCHAR(32) NOT NULL DEFAULT 'research_only',
    recommended_role                VARCHAR(32) NOT NULL DEFAULT 'research_only',
    risk_level                      VARCHAR(16) NOT NULL DEFAULT 'unknown',
    baseline_source_code            VARCHAR(64),
    dataset_codes                   TEXT[] NOT NULL DEFAULT '{}',
    source_codes                    TEXT[] NOT NULL DEFAULT '{}',
    canary_symbols                  TEXT[] NOT NULL DEFAULT '{}',
    start_date                      DATE NOT NULL,
    end_date                        DATE NOT NULL,
    allow_external                  BOOLEAN NOT NULL DEFAULT FALSE,
    require_external                BOOLEAN NOT NULL DEFAULT FALSE,
    require_commercial_clearance    BOOLEAN NOT NULL DEFAULT FALSE,
    min_source_count                INTEGER NOT NULL DEFAULT 2,
    min_coverage_rate               NUMERIC(10, 6) NOT NULL DEFAULT 0.950000,
    max_conflict_rate_bps           NUMERIC(18, 6) NOT NULL DEFAULT 5.000000,
    source_count                    INTEGER NOT NULL DEFAULT 0,
    executable_source_count         INTEGER NOT NULL DEFAULT 0,
    external_source_count           INTEGER NOT NULL DEFAULT 0,
    usable_source_count             INTEGER NOT NULL DEFAULT 0,
    dataset_result_count            INTEGER NOT NULL DEFAULT 0,
    dataset_success_count           INTEGER NOT NULL DEFAULT 0,
    dataset_warning_count           INTEGER NOT NULL DEFAULT 0,
    dataset_blocked_count           INTEGER NOT NULL DEFAULT 0,
    dataset_failed_count            INTEGER NOT NULL DEFAULT 0,
    license_review_required_count   INTEGER NOT NULL DEFAULT 0,
    commercial_blocker_count        INTEGER NOT NULL DEFAULT 0,
    coverage_rate                   NUMERIC(10, 6),
    conflict_rate_bps               NUMERIC(18, 6),
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    next_actions                    TEXT[] NOT NULL DEFAULT '{}',
    request_payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    started_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                     TIMESTAMPTZ,
    duration_ms                     INTEGER,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'api', 'smoke', 'demo')),
    CHECK (fabric_scope IN ('canary', 'full_market')),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (recommendation IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (recommended_role IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (risk_level IN ('unknown', 'low', 'medium', 'high', 'critical')),
    CHECK (array_length(dataset_codes, 1) IS NOT NULL),
    CHECK (array_length(source_codes, 1) IS NOT NULL),
    CHECK (start_date <= end_date),
    CHECK (min_source_count > 0),
    CHECK (min_coverage_rate >= 0 AND min_coverage_rate <= 1),
    CHECK (max_conflict_rate_bps >= 0),
    CHECK (source_count >= 0),
    CHECK (executable_source_count >= 0),
    CHECK (external_source_count >= 0),
    CHECK (usable_source_count >= 0),
    CHECK (dataset_result_count >= 0),
    CHECK (dataset_success_count >= 0),
    CHECK (dataset_warning_count >= 0),
    CHECK (dataset_blocked_count >= 0),
    CHECK (dataset_failed_count >= 0),
    CHECK (license_review_required_count >= 0),
    CHECK (commercial_blocker_count >= 0),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate_bps IS NULL OR conflict_rate_bps >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.free_source_fabric_dataset_result (
    result_id                       BIGSERIAL PRIMARY KEY,
    result_code                     VARCHAR(180) NOT NULL UNIQUE,
    fabric_id                       BIGINT NOT NULL REFERENCES qmeta.free_source_fabric_run(fabric_id) ON DELETE CASCADE,
    dataset_id                      BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    status                          VARCHAR(32) NOT NULL DEFAULT 'planned',
    coverage_status                 VARCHAR(32) NOT NULL DEFAULT 'planned',
    consistency_status              VARCHAR(32) NOT NULL DEFAULT 'planned',
    license_status                  VARCHAR(32) NOT NULL DEFAULT 'unknown',
    freshness_status                VARCHAR(32) NOT NULL DEFAULT 'planned',
    recommendation                  VARCHAR(32) NOT NULL DEFAULT 'research_only',
    recommended_role                VARCHAR(32) NOT NULL DEFAULT 'research_only',
    risk_level                      VARCHAR(16) NOT NULL DEFAULT 'unknown',
    baseline_source_code            VARCHAR(64),
    source_codes                    TEXT[] NOT NULL DEFAULT '{}',
    executed_sources                TEXT[] NOT NULL DEFAULT '{}',
    blocked_sources                 TEXT[] NOT NULL DEFAULT '{}',
    missing_sources                 TEXT[] NOT NULL DEFAULT '{}',
    license_blocking_sources        TEXT[] NOT NULL DEFAULT '{}',
    source_count                    INTEGER NOT NULL DEFAULT 0,
    usable_source_count             INTEGER NOT NULL DEFAULT 0,
    expected_row_count              INTEGER,
    baseline_row_count              INTEGER,
    row_count                       INTEGER,
    coverage_rate                   NUMERIC(10, 6),
    conflict_rate_bps               NUMERIC(18, 6),
    max_abs_value_diff              NUMERIC(28, 10),
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    next_actions                    TEXT[] NOT NULL DEFAULT '{}',
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    started_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                     TIMESTAMPTZ,
    duration_ms                     INTEGER,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (coverage_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (consistency_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (freshness_status IN ('planned', 'success', 'warning', 'failed', 'blocked', 'skipped')),
    CHECK (license_status IN ('unknown', 'local_smoke', 'official_public', 'research_only', 'review_required', 'blocked')),
    CHECK (recommendation IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (recommended_role IN ('reject', 'research_only', 'backup', 'primary_candidate')),
    CHECK (risk_level IN ('unknown', 'low', 'medium', 'high', 'critical')),
    CHECK (source_count >= 0),
    CHECK (usable_source_count >= 0),
    CHECK (expected_row_count IS NULL OR expected_row_count >= 0),
    CHECK (baseline_row_count IS NULL OR baseline_row_count >= 0),
    CHECK (row_count IS NULL OR row_count >= 0),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate_bps IS NULL OR conflict_rate_bps >= 0),
    CHECK (max_abs_value_diff IS NULL OR max_abs_value_diff >= 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_fabric_run_lookup
    ON qmeta.free_source_fabric_run(started_at DESC, status, fabric_scope);

CREATE INDEX IF NOT EXISTS idx_free_source_fabric_run_status
    ON qmeta.free_source_fabric_run(status, recommendation, risk_level, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_fabric_result_lookup
    ON qmeta.free_source_fabric_dataset_result(fabric_id, dataset_id, status);

CREATE INDEX IF NOT EXISTS idx_free_source_fabric_result_status
    ON qmeta.free_source_fabric_dataset_result(status, license_status, risk_level, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.free_source_reliability_snapshot (
    snapshot_id                       BIGSERIAL PRIMARY KEY,
    snapshot_code                     VARCHAR(180) NOT NULL UNIQUE,
    source_id                         BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                        BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    as_of_date                        DATE NOT NULL,
    lookback_hours                    INTEGER NOT NULL DEFAULT 24,
    status                            VARCHAR(32) NOT NULL DEFAULT 'no_data',
    recommended_role                  VARCHAR(32) NOT NULL DEFAULT 'research_only',
    reliability_score                 NUMERIC(8, 4) NOT NULL DEFAULT 0.0000,
    success_rate                      NUMERIC(10, 6),
    coverage_rate                     NUMERIC(10, 6),
    conflict_rate_bps                 NUMERIC(18, 6),
    observation_count                 INTEGER NOT NULL DEFAULT 0,
    success_count                     INTEGER NOT NULL DEFAULT 0,
    warning_count                     INTEGER NOT NULL DEFAULT 0,
    failed_count                      INTEGER NOT NULL DEFAULT 0,
    blocked_count                     INTEGER NOT NULL DEFAULT 0,
    consecutive_failure_count         INTEGER NOT NULL DEFAULT 0,
    license_status                    VARCHAR(32) NOT NULL DEFAULT 'unknown',
    commercial_clearance              VARCHAR(32) NOT NULL DEFAULT 'blocked',
    last_success_at                   TIMESTAMPTZ,
    last_failure_at                   TIMESTAMPTZ,
    degradation_reasons               TEXT[] NOT NULL DEFAULT '{}',
    recovery_actions                  TEXT[] NOT NULL DEFAULT '{}',
    evidence                          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (lookback_hours > 0),
    CHECK (status IN ('no_data', 'ready', 'watch', 'degraded', 'rejected')),
    CHECK (recommended_role IN ('validator', 'backup', 'research_only', 'degraded', 'reject')),
    CHECK (reliability_score >= 0 AND reliability_score <= 100),
    CHECK (success_rate IS NULL OR (success_rate >= 0 AND success_rate <= 1)),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate_bps IS NULL OR conflict_rate_bps >= 0),
    CHECK (observation_count >= 0),
    CHECK (success_count >= 0),
    CHECK (warning_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (blocked_count >= 0),
    CHECK (consecutive_failure_count >= 0),
    CHECK (license_status IN ('unknown', 'local_smoke', 'official_public', 'research_only', 'review_required', 'blocked')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked'))
);

CREATE INDEX IF NOT EXISTS idx_free_source_reliability_lookup
    ON qmeta.free_source_reliability_snapshot(as_of_date DESC, status, reliability_score DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_reliability_source_dataset
    ON qmeta.free_source_reliability_snapshot(source_id, dataset_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_reliability_role
    ON qmeta.free_source_reliability_snapshot(recommended_role, status, reliability_score DESC);

-- Lambda-5: free source recovery orchestration, retry, alert and review.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery'));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery'));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery'));

ALTER TABLE qmeta.alert_event
    DROP CONSTRAINT IF EXISTS alert_event_alert_type_check;

ALTER TABLE qmeta.alert_event
    ADD CONSTRAINT alert_event_alert_type_check
    CHECK (alert_type IN (
        'missing_run',
        'pipeline_status',
        'pipeline_late',
        'completeness_below_sla',
        'conflict_rate_above_sla',
        'api_error_rate_above_sla',
        'duration_above_sla',
        'vendor_score_below_sla',
        'vendor_conflict_rate_above_sla',
        'vendor_failure_rate_above_sla',
        'vendor_latency_above_sla',
        'provider_error_count_above_sla',
        'budget_threshold_warning',
        'budget_exceeded',
        'budget_blocked',
        'budget_usage_spike',
        'runtime_metric_warning',
        'runtime_metric_critical',
        'runtime_capacity_warning',
        'runtime_capacity_critical',
        'runtime_daily_degraded',
        'free_source_recovery_required'
    ));

CREATE TABLE IF NOT EXISTS qmeta.free_source_recovery_run (
    recovery_run_id                BIGSERIAL PRIMARY KEY,
    recovery_code                  VARCHAR(180) NOT NULL UNIQUE,
    requested_by                   VARCHAR(128) NOT NULL DEFAULT 'lambda5',
    trigger_mode                   VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                    VARCHAR(32) NOT NULL DEFAULT 'local',
    as_of_date                     DATE NOT NULL,
    lookback_hours                 INTEGER NOT NULL DEFAULT 24,
    dry_run                        BOOLEAN NOT NULL DEFAULT FALSE,
    status                         VARCHAR(32) NOT NULL DEFAULT 'planned',
    snapshot_count                 INTEGER NOT NULL DEFAULT 0,
    action_count                   INTEGER NOT NULL DEFAULT 0,
    retry_action_count             INTEGER NOT NULL DEFAULT 0,
    alert_action_count             INTEGER NOT NULL DEFAULT 0,
    manual_review_action_count     INTEGER NOT NULL DEFAULT 0,
    suppressed_action_count        INTEGER NOT NULL DEFAULT 0,
    blocked_action_count           INTEGER NOT NULL DEFAULT 0,
    created_alert_count            INTEGER NOT NULL DEFAULT 0,
    blocking_issues                TEXT[] NOT NULL DEFAULT '{}',
    next_actions                   TEXT[] NOT NULL DEFAULT '{}',
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                  TEXT,
    started_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                    TIMESTAMPTZ,
    duration_ms                    INTEGER,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (lookback_hours > 0),
    CHECK (status IN ('planned', 'success', 'warning', 'failed', 'skipped')),
    CHECK (snapshot_count >= 0),
    CHECK (action_count >= 0),
    CHECK (retry_action_count >= 0),
    CHECK (alert_action_count >= 0),
    CHECK (manual_review_action_count >= 0),
    CHECK (suppressed_action_count >= 0),
    CHECK (blocked_action_count >= 0),
    CHECK (created_alert_count >= 0),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE TABLE IF NOT EXISTS qmeta.free_source_recovery_action (
    action_id                      BIGSERIAL PRIMARY KEY,
    action_code                    VARCHAR(180) NOT NULL UNIQUE,
    recovery_run_id                BIGINT NOT NULL REFERENCES qmeta.free_source_recovery_run(recovery_run_id) ON DELETE CASCADE,
    snapshot_id                    BIGINT REFERENCES qmeta.free_source_reliability_snapshot(snapshot_id) ON DELETE SET NULL,
    source_id                      BIGINT REFERENCES qmeta.source_system(source_id),
    dataset_id                     BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    action_type                    VARCHAR(32) NOT NULL,
    status                         VARCHAR(32) NOT NULL DEFAULT 'planned',
    severity                       VARCHAR(16) NOT NULL DEFAULT 'low',
    reason_code                    VARCHAR(96) NOT NULL,
    recommended_role               VARCHAR(32) NOT NULL DEFAULT 'research_only',
    reliability_score              NUMERIC(8, 4),
    retry_after_minutes            INTEGER,
    next_retry_at                  TIMESTAMPTZ,
    alert_id                       BIGINT REFERENCES qmeta.alert_event(alert_id) ON DELETE SET NULL,
    degradation_reasons            TEXT[] NOT NULL DEFAULT '{}',
    recovery_actions               TEXT[] NOT NULL DEFAULT '{}',
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                  TEXT,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (action_type IN ('retry_canary', 'create_alert', 'manual_review', 'observe', 'suppress')),
    CHECK (status IN ('planned', 'skipped', 'scheduled', 'alerted', 'review_required', 'suppressed', 'failed', 'success')),
    CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    CHECK (reliability_score IS NULL OR (reliability_score >= 0 AND reliability_score <= 100)),
    CHECK (retry_after_minutes IS NULL OR retry_after_minutes > 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_run_lookup
    ON qmeta.free_source_recovery_run(started_at DESC, status, trigger_mode);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_action_run
    ON qmeta.free_source_recovery_action(recovery_run_id, status, action_type);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_action_source_dataset
    ON qmeta.free_source_recovery_action(source_id, dataset_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_action_severity
    ON qmeta.free_source_recovery_action(severity, status, created_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'mu_free_source_recovery_30m', 'free_source_recovery', 1800, 600, 900, 300,
    '{"free_source_lookback_hours":72,"free_source_max_actions":50,"free_source_min_retry_score":75.0,"free_source_write_alerts":true}'::jsonb,
    '{"owner":"lambda5","purpose":"schedule retry, alert and manual review actions from Kappa-5 free-source reliability scores"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;

-- Rho-5: post-promotion shadow monitoring, rollback and degradation drill.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_post_promotion_monitor_run (
    monitor_id                      BIGSERIAL PRIMARY KEY,
    monitor_code                    VARCHAR(180) NOT NULL UNIQUE,
    promotion_id                    BIGINT REFERENCES qmeta.vendor_primary_promotion_run(promotion_id) ON DELETE SET NULL,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    as_of_date                      DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                    VARCHAR(128) NOT NULL DEFAULT 'rho5',
    trigger_mode                    VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                     VARCHAR(32) NOT NULL DEFAULT 'local',
    monitor_scope                   VARCHAR(32) NOT NULL DEFAULT 'post_promotion',
    status                          VARCHAR(32) NOT NULL DEFAULT 'no_applied_promotion',
    rollback_mode                   VARCHAR(32) NOT NULL DEFAULT 'review_only',
    require_applied_promotion       BOOLEAN NOT NULL DEFAULT TRUE,
    rollback_allowed                BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_applied                BOOLEAN NOT NULL DEFAULT FALSE,
    dataset_count                   INTEGER NOT NULL DEFAULT 0,
    healthy_dataset_count           INTEGER NOT NULL DEFAULT 0,
    warning_dataset_count           INTEGER NOT NULL DEFAULT 0,
    rollback_recommended_count      INTEGER NOT NULL DEFAULT 0,
    rolled_back_dataset_count       INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count           INTEGER NOT NULL DEFAULT 0,
    no_applied_dataset_count        INTEGER NOT NULL DEFAULT 0,
    shadow_window_hours             INTEGER NOT NULL DEFAULT 24,
    max_conflict_rate_bps           NUMERIC(10, 4) NOT NULL DEFAULT 5.0000,
    max_failure_rate                NUMERIC(8, 6) NOT NULL DEFAULT 0.010000,
    max_stale_minutes               INTEGER NOT NULL DEFAULT 90,
    current_primary_source_codes    TEXT[] NOT NULL DEFAULT '{}',
    previous_primary_source_codes   TEXT[] NOT NULL DEFAULT '{}',
    monitor_score                   NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    required_actions                TEXT[] NOT NULL DEFAULT '{}',
    request_payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    started_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                     TIMESTAMPTZ,
    duration_ms                     INTEGER,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (monitor_scope IN ('shadow', 'post_promotion', 'rollback_drill')),
    CHECK (status IN ('healthy', 'warning', 'rollback_recommended', 'rolled_back', 'blocked', 'no_applied_promotion')),
    CHECK (rollback_mode IN ('review_only', 'dry_run', 'apply')),
    CHECK (dataset_count >= 0),
    CHECK (healthy_dataset_count >= 0),
    CHECK (warning_dataset_count >= 0),
    CHECK (rollback_recommended_count >= 0),
    CHECK (rolled_back_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (no_applied_dataset_count >= 0),
    CHECK (shadow_window_hours > 0),
    CHECK (max_conflict_rate_bps >= 0),
    CHECK (max_failure_rate >= 0),
    CHECK (max_stale_minutes >= 0),
    CHECK (monitor_score >= 0 AND monitor_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_monitor_lookup
    ON qmeta.vendor_post_promotion_monitor_run(source_id, as_of_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_monitor_status
    ON qmeta.vendor_post_promotion_monitor_run(status, monitor_scope, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_monitor_promotion
    ON qmeta.vendor_post_promotion_monitor_run(promotion_id, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_post_promotion_dataset_monitor (
    result_id                       BIGSERIAL PRIMARY KEY,
    result_code                     VARCHAR(180) NOT NULL UNIQUE,
    monitor_id                      BIGINT NOT NULL REFERENCES qmeta.vendor_post_promotion_monitor_run(monitor_id) ON DELETE CASCADE,
    promotion_id                    BIGINT REFERENCES qmeta.vendor_primary_promotion_run(promotion_id) ON DELETE SET NULL,
    promotion_result_id             BIGINT REFERENCES qmeta.vendor_primary_promotion_dataset_result(result_id) ON DELETE SET NULL,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                      BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    previous_primary_source_id      BIGINT REFERENCES qmeta.source_system(source_id),
    current_priority_id             BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    previous_priority_id            BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    as_of_date                      DATE NOT NULL DEFAULT CURRENT_DATE,
    monitor_scope                   VARCHAR(32) NOT NULL DEFAULT 'post_promotion',
    status                          VARCHAR(32) NOT NULL DEFAULT 'no_applied_promotion',
    rollback_mode                   VARCHAR(32) NOT NULL DEFAULT 'review_only',
    rollback_allowed                BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_applied                BOOLEAN NOT NULL DEFAULT FALSE,
    promotion_status                VARCHAR(32),
    promotion_role                  VARCHAR(32),
    routing_change_applied          BOOLEAN NOT NULL DEFAULT FALSE,
    current_primary_source_code     VARCHAR(64),
    current_priority                INTEGER,
    previous_primary_source_code    VARCHAR(64),
    previous_priority               INTEGER,
    target_priority                 INTEGER NOT NULL DEFAULT 0,
    shadow_status                   VARCHAR(32) NOT NULL DEFAULT 'not_available',
    shadow_conflict_rate_bps        NUMERIC(10, 4) NOT NULL DEFAULT 0,
    shadow_failure_rate             NUMERIC(8, 6) NOT NULL DEFAULT 0,
    shadow_latency_p95_ms           NUMERIC(12, 4),
    stale_minutes                   INTEGER NOT NULL DEFAULT 0,
    monitor_score                   NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    required_actions                TEXT[] NOT NULL DEFAULT '{}',
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (monitor_scope IN ('shadow', 'post_promotion', 'rollback_drill')),
    CHECK (status IN ('healthy', 'warning', 'rollback_recommended', 'rolled_back', 'blocked', 'no_applied_promotion')),
    CHECK (rollback_mode IN ('review_only', 'dry_run', 'apply')),
    CHECK (promotion_role IS NULL OR promotion_role IN ('blocked', 'validator', 'backup', 'primary')),
    CHECK (current_priority IS NULL OR current_priority >= 0),
    CHECK (previous_priority IS NULL OR previous_priority >= 0),
    CHECK (target_priority >= 0),
    CHECK (shadow_conflict_rate_bps >= 0),
    CHECK (shadow_failure_rate >= 0),
    CHECK (stale_minutes >= 0),
    CHECK (monitor_score >= 0 AND monitor_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_result_lookup
    ON qmeta.vendor_post_promotion_dataset_monitor(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_result_monitor
    ON qmeta.vendor_post_promotion_dataset_monitor(monitor_id, status, result_id DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_post_promotion_result_promotion
    ON qmeta.vendor_post_promotion_dataset_monitor(promotion_id, promotion_result_id);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'rho5_post_promotion_monitor_1h', 'vendor_post_promotion_monitor', 3600, 600, 600, 300,
    '{"rho5_monitor_scope":"post_promotion","rho5_require_applied_promotion":true,"rho5_apply_rollback":false,"rho5_shadow_window_hours":24,"rho5_max_conflict_rate_bps":5.0,"rho5_max_failure_rate":0.01,"rho5_max_stale_minutes":90}'::jsonb,
    '{"owner":"rho5","purpose":"monitor Pi-5 primary-source promotions with shadow reconciliation, rollback recommendation and review-only rollback drill by default"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;

-- Xi-5: free source admission matrix for licensing, redistribution and production-role control.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review'
    ));

CREATE TABLE IF NOT EXISTS qmeta.free_source_admission_profile (
    profile_id                    BIGSERIAL PRIMARY KEY,
    source_id                     BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    profile_code                  VARCHAR(180) NOT NULL UNIQUE,
    provider_name                 VARCHAR(128) NOT NULL,
    license_type                  VARCHAR(32) NOT NULL DEFAULT 'unknown',
    license_status                VARCHAR(32) NOT NULL DEFAULT 'unknown',
    commercial_clearance          VARCHAR(32) NOT NULL DEFAULT 'blocked',
    redistribution_allowed        VARCHAR(16) NOT NULL DEFAULT 'unknown',
    contract_status               VARCHAR(32) NOT NULL DEFAULT 'none',
    contract_ref                  VARCHAR(180),
    terms_review_status           VARCHAR(32) NOT NULL DEFAULT 'missing',
    api_terms_url                 TEXT,
    rate_limit_per_min            INTEGER,
    daily_quota                   INTEGER,
    max_allowed_role              VARCHAR(32) NOT NULL DEFAULT 'research_only',
    status                        VARCHAR(32) NOT NULL DEFAULT 'active',
    reviewed_by                   VARCHAR(128),
    reviewed_at                   TIMESTAMPTZ,
    expires_at                    TIMESTAMPTZ,
    evidence                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id),
    CHECK (license_type IN ('unknown', 'local_fixture', 'open_source', 'official_public', 'exchange_public', 'announcement_public', 'free_tier', 'paid_contract')),
    CHECK (license_status IN ('unknown', 'local_smoke', 'official_public', 'research_only', 'review_required', 'blocked', 'contracted', 'approved')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (contract_status IN ('none', 'draft', 'active', 'expired', 'terminated')),
    CHECK (terms_review_status IN ('missing', 'pending', 'approved', 'rejected', 'expired')),
    CHECK (max_allowed_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (status IN ('active', 'inactive', 'expired', 'blocked')),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_profile_source
    ON qmeta.free_source_admission_profile(source_id, status);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_profile_clearance
    ON qmeta.free_source_admission_profile(commercial_clearance, redistribution_allowed, contract_status, terms_review_status);

CREATE TABLE IF NOT EXISTS qmeta.free_source_admission_snapshot (
    admission_id                  BIGSERIAL PRIMARY KEY,
    snapshot_code                 VARCHAR(180) NOT NULL UNIQUE,
    source_id                     BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                    BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    profile_id                    BIGINT REFERENCES qmeta.free_source_admission_profile(profile_id) ON DELETE SET NULL,
    reliability_snapshot_id       BIGINT REFERENCES qmeta.free_source_reliability_snapshot(snapshot_id) ON DELETE SET NULL,
    as_of_date                    DATE NOT NULL,
    requested_by                  VARCHAR(128) NOT NULL DEFAULT 'xi5',
    trigger_mode                  VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                   VARCHAR(32) NOT NULL DEFAULT 'local',
    status                        VARCHAR(32) NOT NULL DEFAULT 'no_data',
    admission_role                VARCHAR(32) NOT NULL DEFAULT 'blocked',
    max_allowed_role              VARCHAR(32) NOT NULL DEFAULT 'research_only',
    license_type                  VARCHAR(32) NOT NULL DEFAULT 'unknown',
    license_status                VARCHAR(32) NOT NULL DEFAULT 'unknown',
    commercial_clearance          VARCHAR(32) NOT NULL DEFAULT 'blocked',
    redistribution_allowed        VARCHAR(16) NOT NULL DEFAULT 'unknown',
    contract_status               VARCHAR(32) NOT NULL DEFAULT 'none',
    contract_ref                  VARCHAR(180),
    terms_review_status           VARCHAR(32) NOT NULL DEFAULT 'missing',
    api_terms_url                 TEXT,
    rate_limit_per_min            INTEGER,
    daily_quota                   INTEGER,
    reliability_status            VARCHAR(32) NOT NULL DEFAULT 'no_data',
    reliability_score             NUMERIC(8, 4) NOT NULL DEFAULT 0,
    success_rate                  NUMERIC(10, 6),
    coverage_rate                 NUMERIC(10, 6),
    conflict_rate_bps             NUMERIC(18, 6),
    observation_count             INTEGER NOT NULL DEFAULT 0,
    reliability_snapshot_code     VARCHAR(180),
    latest_fabric_code            VARCHAR(180),
    latest_fabric_status          VARCHAR(32),
    blocking_issues               TEXT[] NOT NULL DEFAULT '{}',
    required_actions              TEXT[] NOT NULL DEFAULT '{}',
    evidence                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                 TEXT,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('approved', 'conditional', 'review_required', 'blocked', 'no_data')),
    CHECK (admission_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (max_allowed_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (license_type IN ('unknown', 'local_fixture', 'open_source', 'official_public', 'exchange_public', 'announcement_public', 'free_tier', 'paid_contract')),
    CHECK (license_status IN ('unknown', 'local_smoke', 'official_public', 'research_only', 'review_required', 'blocked', 'contracted', 'approved')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (contract_status IN ('none', 'draft', 'active', 'expired', 'terminated')),
    CHECK (terms_review_status IN ('missing', 'pending', 'approved', 'rejected', 'expired')),
    CHECK (reliability_status IN ('no_data', 'ready', 'watch', 'degraded', 'rejected')),
    CHECK (reliability_score >= 0 AND reliability_score <= 100),
    CHECK (success_rate IS NULL OR (success_rate >= 0 AND success_rate <= 1)),
    CHECK (coverage_rate IS NULL OR (coverage_rate >= 0 AND coverage_rate <= 1)),
    CHECK (conflict_rate_bps IS NULL OR conflict_rate_bps >= 0),
    CHECK (observation_count >= 0),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_snapshot_lookup
    ON qmeta.free_source_admission_snapshot(as_of_date DESC, status, admission_role);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_snapshot_source_dataset
    ON qmeta.free_source_admission_snapshot(source_id, dataset_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_admission_snapshot_license
    ON qmeta.free_source_admission_snapshot(commercial_clearance, redistribution_allowed, contract_status, terms_review_status, as_of_date DESC);

INSERT INTO qmeta.free_source_admission_profile (
    source_id, profile_code, provider_name, license_type, license_status,
    commercial_clearance, redistribution_allowed, contract_status, terms_review_status,
    max_allowed_role, evidence, updated_at
)
SELECT
    ss.source_id,
    'xi5-profile-' || ss.source_code,
    seed.provider_name,
    seed.license_type,
    seed.license_status,
    seed.commercial_clearance,
    seed.redistribution_allowed,
    seed.contract_status,
    seed.terms_review_status,
    seed.max_allowed_role,
    jsonb_build_object('seeded_by', '0038', 'policy_note', seed.policy_note),
    now()
FROM (
    VALUES
        ('csv', 'csv', 'local_fixture', 'local_smoke', 'blocked', 'no', 'none', 'missing', 'validator', 'local fixture can validate pipelines but cannot serve production clients'),
        ('csv_mirror', 'csv_mirror', 'local_fixture', 'local_smoke', 'blocked', 'no', 'none', 'missing', 'validator', 'local mirror fixture can validate deterministic comparisons only'),
        ('akshare', 'akshare', 'open_source', 'research_only', 'blocked', 'no', 'none', 'pending', 'validator', 'public web aggregation requires upstream commercial-use review'),
        ('baostock', 'baostock', 'open_source', 'research_only', 'blocked', 'no', 'none', 'pending', 'validator', 'free research source requires redistribution and commercial-use review'),
        ('tushare_free', 'tushare_free', 'free_tier', 'review_required', 'blocked', 'unknown', 'none', 'pending', 'validator', 'free quota tier requires points, frequency and commercial terms review'),
        ('cninfo_public', 'cninfo_public', 'announcement_public', 'review_required', 'review_required', 'unknown', 'none', 'pending', 'backup', 'public announcement source requires cache and redistribution review'),
        ('sse_public', 'sse_public', 'exchange_public', 'official_public', 'review_required', 'unknown', 'none', 'pending', 'backup', 'official exchange public pages require reuse and caching terms review'),
        ('szse_public', 'szse_public', 'exchange_public', 'official_public', 'review_required', 'unknown', 'none', 'pending', 'backup', 'official exchange public pages require reuse and caching terms review'),
        ('nbs_public', 'nbs_public', 'official_public', 'official_public', 'review_required', 'unknown', 'none', 'pending', 'backup', 'official public macro source requires terms and attribution review')
) AS seed(source_code, provider_name, license_type, license_status, commercial_clearance, redistribution_allowed, contract_status, terms_review_status, max_allowed_role, policy_note)
JOIN qmeta.source_system ss ON ss.source_code = seed.source_code
ON CONFLICT (source_id) DO UPDATE SET
    provider_name = EXCLUDED.provider_name,
    license_type = EXCLUDED.license_type,
    license_status = EXCLUDED.license_status,
    commercial_clearance = EXCLUDED.commercial_clearance,
    redistribution_allowed = EXCLUDED.redistribution_allowed,
    contract_status = EXCLUDED.contract_status,
    terms_review_status = EXCLUDED.terms_review_status,
    max_allowed_role = EXCLUDED.max_allowed_role,
    evidence = qmeta.free_source_admission_profile.evidence || EXCLUDED.evidence,
    updated_at = now();

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'xi_free_source_admission_review_6h', 'free_source_admission_review', 21600, 600, 600, 300,
    '{"xi5_lookback_days":30,"xi5_min_validator_score":55,"xi5_min_backup_score":75,"xi5_min_primary_score":90,"xi5_min_coverage_rate":0.95,"xi5_max_conflict_rate_bps":5}'::jsonb,
    '{"owner":"xi5","purpose":"review free-source licensing, redistribution, contract, quota and reliability evidence before any production role"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;

-- Nu-5: free source recovery health snapshots, SLA guardrails and runbook evidence.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health'
    ));

CREATE TABLE IF NOT EXISTS qmeta.free_source_recovery_health_snapshot (
    snapshot_id                   BIGSERIAL PRIMARY KEY,
    snapshot_code                 VARCHAR(180) NOT NULL UNIQUE,
    requested_by                  VARCHAR(128) NOT NULL DEFAULT 'nu5',
    trigger_mode                  VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                   VARCHAR(32) NOT NULL DEFAULT 'local',
    status                        VARCHAR(32) NOT NULL DEFAULT 'healthy',
    as_of_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    lookback_hours                INTEGER NOT NULL DEFAULT 24,
    approval_sla_hours            INTEGER NOT NULL DEFAULT 4,
    max_backlog_actions           INTEGER NOT NULL DEFAULT 50,
    max_failure_rate              NUMERIC(8, 4) NOT NULL DEFAULT 0.5000,
    max_stale_minutes             INTEGER NOT NULL DEFAULT 90,
    schedule_code                 VARCHAR(160) NOT NULL DEFAULT 'mu_free_source_recovery_execute_30m',
    pending_action_count          INTEGER NOT NULL DEFAULT 0,
    pending_retry_count           INTEGER NOT NULL DEFAULT 0,
    pending_manual_review_count   INTEGER NOT NULL DEFAULT 0,
    execution_count               INTEGER NOT NULL DEFAULT 0,
    recovered_count               INTEGER NOT NULL DEFAULT 0,
    failed_count                  INTEGER NOT NULL DEFAULT 0,
    suppressed_count              INTEGER NOT NULL DEFAULT 0,
    review_requested_count        INTEGER NOT NULL DEFAULT 0,
    blocked_count                 INTEGER NOT NULL DEFAULT 0,
    failure_rate                  NUMERIC(8, 4) NOT NULL DEFAULT 0,
    approval_pending_count        INTEGER NOT NULL DEFAULT 0,
    approval_overdue_count        INTEGER NOT NULL DEFAULT 0,
    backlog_count                 INTEGER NOT NULL DEFAULT 0,
    stale_schedule_count          INTEGER NOT NULL DEFAULT 0,
    recent_worker_run_count       INTEGER NOT NULL DEFAULT 0,
    latest_worker_status          VARCHAR(32),
    latest_schedule_status        VARCHAR(32),
    latest_execution_status       VARCHAR(32),
    health_issues                 TEXT[] NOT NULL DEFAULT '{}',
    runbook_actions               TEXT[] NOT NULL DEFAULT '{}',
    evidence                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                 TEXT,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('healthy', 'warning', 'critical', 'failed', 'skipped')),
    CHECK (lookback_hours > 0),
    CHECK (approval_sla_hours > 0),
    CHECK (max_backlog_actions >= 0),
    CHECK (max_failure_rate >= 0 AND max_failure_rate <= 1),
    CHECK (max_stale_minutes > 0),
    CHECK (pending_action_count >= 0),
    CHECK (pending_retry_count >= 0),
    CHECK (pending_manual_review_count >= 0),
    CHECK (execution_count >= 0),
    CHECK (recovered_count >= 0),
    CHECK (failed_count >= 0),
    CHECK (suppressed_count >= 0),
    CHECK (review_requested_count >= 0),
    CHECK (blocked_count >= 0),
    CHECK (failure_rate >= 0 AND failure_rate <= 1),
    CHECK (approval_pending_count >= 0),
    CHECK (approval_overdue_count >= 0),
    CHECK (backlog_count >= 0),
    CHECK (stale_schedule_count >= 0),
    CHECK (recent_worker_run_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_health_lookup
    ON qmeta.free_source_recovery_health_snapshot(as_of_at DESC, status);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_health_sla
    ON qmeta.free_source_recovery_health_snapshot(approval_overdue_count, backlog_count, stale_schedule_count, as_of_at DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_health_schedule
    ON qmeta.free_source_recovery_health_snapshot(schedule_code, as_of_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'nu_free_source_recovery_health_15m', 'free_source_recovery_health', 900, 300, 300, 120,
    '{"nu5_lookback_hours":24,"nu5_approval_sla_hours":4,"nu5_max_backlog_actions":50,"nu5_max_failure_rate":0.5,"nu5_max_stale_minutes":90}'::jsonb,
    '{"owner":"nu5","purpose":"snapshot Mu-5 recovery health, approval SLA, backlog, failure rate and stale scheduler risk"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;

-- Mu-5: free source recovery execution, approval notification and writeback

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery', 'free_source_recovery_execute'));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery', 'free_source_recovery_execute'));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN ('usage_rollup', 'alert_dispatch', 'vendor_benchmark_schedule', 'free_source_recovery', 'free_source_recovery_execute'));

ALTER TABLE qmeta.free_source_recovery_action
    DROP CONSTRAINT IF EXISTS free_source_recovery_action_status_check;

ALTER TABLE qmeta.free_source_recovery_action
    ADD CONSTRAINT free_source_recovery_action_status_check
    CHECK (status IN (
        'planned',
        'skipped',
        'scheduled',
        'alerted',
        'review_required',
        'review_requested',
        'notified',
        'recovered',
        'suppressed',
        'failed',
        'success',
        'blocked'
    ));

CREATE TABLE IF NOT EXISTS qmeta.free_source_recovery_execution (
    execution_id                  BIGSERIAL PRIMARY KEY,
    execution_code                VARCHAR(180) NOT NULL UNIQUE,
    action_id                     BIGINT NOT NULL REFERENCES qmeta.free_source_recovery_action(action_id) ON DELETE CASCADE,
    recovery_run_id               BIGINT REFERENCES qmeta.free_source_recovery_run(recovery_run_id) ON DELETE SET NULL,
    execution_type                VARCHAR(32) NOT NULL,
    trigger_mode                  VARCHAR(32) NOT NULL DEFAULT 'manual',
    status                        VARCHAR(32) NOT NULL DEFAULT 'planned',
    requested_by                  VARCHAR(128) NOT NULL DEFAULT 'mu5',
    environment                   VARCHAR(32) NOT NULL DEFAULT 'local',
    dry_run                       BOOLEAN NOT NULL DEFAULT FALSE,
    source_id                     BIGINT REFERENCES qmeta.source_system(source_id),
    dataset_id                    BIGINT REFERENCES qmeta.dataset_catalog(dataset_id),
    fabric_id                     BIGINT REFERENCES qmeta.free_source_fabric_run(fabric_id) ON DELETE SET NULL,
    fabric_code                   VARCHAR(180),
    iota5_pool_status             VARCHAR(32),
    automation_run_id             BIGINT REFERENCES qmeta.automation_run(automation_run_id) ON DELETE SET NULL,
    automation_action_id          BIGINT REFERENCES qmeta.automation_action(automation_action_id) ON DELETE SET NULL,
    approval_id                   BIGINT REFERENCES qmeta.automation_approval(approval_id) ON DELETE SET NULL,
    approval_code                 VARCHAR(260),
    wecom_receipt_id              BIGINT REFERENCES qmeta.automation_live_provider_receipt(receipt_id) ON DELETE SET NULL,
    wecom_receipt_code            VARCHAR(180),
    result_summary                JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                 TEXT,
    started_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                   TIMESTAMPTZ,
    duration_ms                   INTEGER,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (execution_type IN ('retry_canary', 'manual_review', 'observe', 'suppress')),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('planned', 'running', 'recovered', 'failed', 'suppressed', 'review_requested', 'notified', 'blocked', 'skipped')),
    CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_lookup
    ON qmeta.free_source_recovery_execution(started_at DESC, status, execution_type);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_action
    ON qmeta.free_source_recovery_execution(action_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_source_dataset
    ON qmeta.free_source_recovery_execution(source_id, dataset_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_approval
    ON qmeta.free_source_recovery_execution(approval_code);

CREATE INDEX IF NOT EXISTS idx_free_source_recovery_execution_wecom
    ON qmeta.free_source_recovery_execution(wecom_receipt_code);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'mu_free_source_recovery_execute_30m', 'free_source_recovery_execute', 1800, 900, 900, 300,
    '{"mu5_max_actions":20,"mu5_start_date":"2024-01-04","mu5_end_date":"2024-01-04","mu5_execute_retry_canary":true,"mu5_request_manual_review":true,"mu5_notify_wecom":true,"mu5_allow_wecom_external":false,"mu5_baostock_timeout_seconds":3.0}'::jsonb,
    '{"owner":"mu5","purpose":"execute Lambda-5 retry canary and manual-review recovery actions with audit writeback"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;

-- Omicron-5: authorized primary vendor procurement, contract and entitlement readiness.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review'
    ));

INSERT INTO qmeta.source_system (
    source_code, source_name, source_type, license_scope, update_frequency, latency_level, owner, is_active
) VALUES (
    'vendor_http',
    'Commercial HTTP Vendor',
    'vendor',
    'commercial contract required; token value comes from environment',
    'daily',
    'L3',
    'platform-data',
    TRUE
)
ON CONFLICT (source_code) DO UPDATE SET
    source_name = EXCLUDED.source_name,
    source_type = EXCLUDED.source_type,
    license_scope = EXCLUDED.license_scope,
    update_frequency = EXCLUDED.update_frequency,
    latency_level = EXCLUDED.latency_level,
    owner = EXCLUDED.owner,
    is_active = TRUE,
    updated_at = now();

INSERT INTO qmeta.dataset_catalog (
    dataset_code, dataset_name, asset_type, frequency, storage_layer, pit_required, description, is_active
)
SELECT
    seed.dataset_code,
    seed.dataset_name,
    seed.asset_type,
    seed.frequency,
    seed.storage_layer,
    seed.pit_required,
    seed.description,
    TRUE
FROM (
    VALUES
        ('daily_bar', 'A-share daily bar', 'stock', 'daily', 'clickhouse', FALSE, 'Daily OHLCV market bars for quantitative research and production routing'),
        ('security_master', 'Security master', 'stock', 'daily', 'postgresql', TRUE, 'A-share instrument identity, listing status and name history'),
        ('trading_calendar', 'Trading calendar', 'market', 'daily', 'postgresql', FALSE, 'Exchange trading day and session calendar'),
        ('adjustment_factor', 'Adjustment factor', 'stock', 'daily', 'postgresql', TRUE, 'Forward/backward adjustment factors for price normalization'),
        ('limit_price_daily', 'Daily limit price', 'stock', 'daily', 'postgresql', FALSE, 'Daily limit-up and limit-down price constraints'),
        ('financial_metric_pit', 'PIT financial metric', 'stock', 'quarterly', 'postgresql', TRUE, 'Point-in-time financial metrics with announce and ingest time'),
        ('financial_statement_pit', 'PIT financial statement', 'stock', 'quarterly', 'postgresql', TRUE, 'Point-in-time financial statements with announce and ingest time')
) AS seed(dataset_code, dataset_name, asset_type, frequency, storage_layer, pit_required, description)
ON CONFLICT (dataset_code) DO UPDATE SET
    dataset_name = COALESCE(qmeta.dataset_catalog.dataset_name, EXCLUDED.dataset_name),
    asset_type = COALESCE(qmeta.dataset_catalog.asset_type, EXCLUDED.asset_type),
    frequency = COALESCE(qmeta.dataset_catalog.frequency, EXCLUDED.frequency),
    storage_layer = COALESCE(qmeta.dataset_catalog.storage_layer, EXCLUDED.storage_layer),
    pit_required = qmeta.dataset_catalog.pit_required OR EXCLUDED.pit_required,
    description = COALESCE(qmeta.dataset_catalog.description, EXCLUDED.description),
    is_active = TRUE,
    updated_at = now();

CREATE TABLE IF NOT EXISTS qmeta.vendor_contract_profile (
    contract_id                    BIGSERIAL PRIMARY KEY,
    contract_code                  VARCHAR(180) NOT NULL UNIQUE,
    source_id                      BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    profile_id                     BIGINT REFERENCES qmeta.vendor_integration_profile(profile_id) ON DELETE SET NULL,
    provider_name                  VARCHAR(128) NOT NULL,
    vendor_account_code            VARCHAR(128),
    procurement_status             VARCHAR(32) NOT NULL DEFAULT 'review_required',
    contract_status                VARCHAR(32) NOT NULL DEFAULT 'draft',
    commercial_clearance           VARCHAR(32) NOT NULL DEFAULT 'review_required',
    redistribution_allowed         VARCHAR(16) NOT NULL DEFAULT 'unknown',
    production_use_allowed         BOOLEAN NOT NULL DEFAULT FALSE,
    contract_ref                   VARCHAR(180),
    contract_owner                 VARCHAR(128),
    legal_owner                    VARCHAR(128),
    business_owner                 VARCHAR(128),
    contract_start_date            DATE,
    contract_end_date              DATE,
    sla_tier                       VARCHAR(32) NOT NULL DEFAULT 'unknown',
    sla_uptime_pct                 NUMERIC(6, 3),
    support_sla_hours              INTEGER,
    rate_limit_per_min             INTEGER,
    daily_quota                    BIGINT,
    monthly_quota                  BIGINT,
    billing_model                  VARCHAR(32) NOT NULL DEFAULT 'unknown',
    billing_currency               VARCHAR(16) NOT NULL DEFAULT 'CNY',
    monthly_fee                    NUMERIC(20, 6),
    unit_cost                      NUMERIC(20, 8),
    data_scope                     TEXT[] NOT NULL DEFAULT '{}',
    status                         VARCHAR(32) NOT NULL DEFAULT 'active',
    reviewed_by                    VARCHAR(128),
    reviewed_at                    TIMESTAMPTZ,
    next_review_at                 TIMESTAMPTZ,
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (procurement_status IN ('draft', 'review_required', 'active', 'suspended', 'expired', 'terminated', 'blocked')),
    CHECK (contract_status IN ('none', 'draft', 'active', 'expired', 'terminated')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (sla_tier IN ('unknown', 'bronze', 'silver', 'gold', 'platinum', 'enterprise')),
    CHECK (billing_model IN ('unknown', 'free_trial', 'fixed', 'usage', 'tiered', 'enterprise')),
    CHECK (status IN ('active', 'inactive', 'expired', 'blocked')),
    CHECK (contract_end_date IS NULL OR contract_start_date IS NULL OR contract_end_date >= contract_start_date),
    CHECK (sla_uptime_pct IS NULL OR (sla_uptime_pct >= 0 AND sla_uptime_pct <= 100)),
    CHECK (support_sla_hours IS NULL OR support_sla_hours >= 0),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0),
    CHECK (monthly_quota IS NULL OR monthly_quota > 0),
    CHECK (monthly_fee IS NULL OR monthly_fee >= 0),
    CHECK (unit_cost IS NULL OR unit_cost >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_profile_source
    ON qmeta.vendor_contract_profile(source_id, status, procurement_status);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_profile_contract_status
    ON qmeta.vendor_contract_profile(contract_status, commercial_clearance, redistribution_allowed, production_use_allowed);

CREATE TABLE IF NOT EXISTS qmeta.vendor_contract_dataset_entitlement (
    entitlement_id                 BIGSERIAL PRIMARY KEY,
    entitlement_code               VARCHAR(180) NOT NULL UNIQUE,
    contract_id                    BIGINT NOT NULL REFERENCES qmeta.vendor_contract_profile(contract_id) ON DELETE CASCADE,
    source_id                      BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                     BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    entitlement_status             VARCHAR(32) NOT NULL DEFAULT 'review_required',
    allowed_role                   VARCHAR(32) NOT NULL DEFAULT 'validator',
    commercial_use_allowed         BOOLEAN NOT NULL DEFAULT FALSE,
    redistribution_allowed         VARCHAR(16) NOT NULL DEFAULT 'unknown',
    production_use_allowed         BOOLEAN NOT NULL DEFAULT FALSE,
    delivery_mode                  VARCHAR(32) NOT NULL DEFAULT 'api',
    frequency                      VARCHAR(32),
    latency_level                  VARCHAR(16),
    endpoint_path                  VARCHAR(256),
    schema_status                  VARCHAR(32) NOT NULL DEFAULT 'pending',
    field_mapping_status           VARCHAR(32) NOT NULL DEFAULT 'pending',
    rate_limit_per_min             INTEGER,
    daily_quota                    BIGINT,
    max_delay_minutes              INTEGER,
    sla_uptime_pct                 NUMERIC(6, 3),
    effective_from                 DATE,
    effective_to                   DATE,
    blocking_issues                TEXT[] NOT NULL DEFAULT '{}',
    required_actions               TEXT[] NOT NULL DEFAULT '{}',
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                         VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contract_id, dataset_id),
    CHECK (entitlement_status IN ('active', 'review_required', 'blocked', 'expired', 'suspended')),
    CHECK (allowed_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (delivery_mode IN ('api', 'file', 'sftp', 'websocket', 'manual', 'unknown')),
    CHECK (latency_level IS NULL OR latency_level IN ('L0', 'L1', 'L2', 'L3', 'L4')),
    CHECK (schema_status IN ('missing', 'pending', 'mapped', 'validated', 'rejected')),
    CHECK (field_mapping_status IN ('missing', 'pending', 'mapped', 'validated', 'rejected')),
    CHECK (status IN ('active', 'inactive', 'expired', 'blocked')),
    CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0),
    CHECK (max_delay_minutes IS NULL OR max_delay_minutes >= 0),
    CHECK (sla_uptime_pct IS NULL OR (sla_uptime_pct >= 0 AND sla_uptime_pct <= 100))
);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_entitlement_dataset
    ON qmeta.vendor_contract_dataset_entitlement(source_id, dataset_id, entitlement_status, allowed_role);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_entitlement_rights
    ON qmeta.vendor_contract_dataset_entitlement(commercial_use_allowed, redistribution_allowed, production_use_allowed, schema_status);

CREATE TABLE IF NOT EXISTS qmeta.vendor_procurement_readiness_snapshot (
    snapshot_id                    BIGSERIAL PRIMARY KEY,
    snapshot_code                  VARCHAR(180) NOT NULL UNIQUE,
    source_id                      BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                     BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    contract_id                    BIGINT REFERENCES qmeta.vendor_contract_profile(contract_id) ON DELETE SET NULL,
    entitlement_id                 BIGINT REFERENCES qmeta.vendor_contract_dataset_entitlement(entitlement_id) ON DELETE SET NULL,
    profile_id                     BIGINT REFERENCES qmeta.vendor_integration_profile(profile_id) ON DELETE SET NULL,
    as_of_date                     DATE NOT NULL,
    requested_by                   VARCHAR(128) NOT NULL DEFAULT 'omicron5',
    trigger_mode                   VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                    VARCHAR(32) NOT NULL DEFAULT 'local',
    status                         VARCHAR(32) NOT NULL DEFAULT 'no_contract',
    procurement_role               VARCHAR(32) NOT NULL DEFAULT 'blocked',
    readiness_score                NUMERIC(8, 4) NOT NULL DEFAULT 0,
    procurement_status             VARCHAR(32) NOT NULL DEFAULT 'review_required',
    contract_status                VARCHAR(32) NOT NULL DEFAULT 'none',
    commercial_clearance           VARCHAR(32) NOT NULL DEFAULT 'review_required',
    redistribution_allowed         VARCHAR(16) NOT NULL DEFAULT 'unknown',
    contract_production_use_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    entitlement_status             VARCHAR(32) NOT NULL DEFAULT 'review_required',
    entitlement_allowed_role       VARCHAR(32) NOT NULL DEFAULT 'validator',
    entitlement_commercial_use_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    entitlement_redistribution_allowed VARCHAR(16) NOT NULL DEFAULT 'unknown',
    entitlement_production_use_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    contract_ref                   VARCHAR(180),
    contract_end_date              DATE,
    next_review_at                 TIMESTAMPTZ,
    rate_limit_per_min             INTEGER,
    daily_quota                    BIGINT,
    monthly_quota                  BIGINT,
    sla_uptime_pct                 NUMERIC(6, 3),
    max_delay_minutes              INTEGER,
    vendor_profile_status          VARCHAR(32),
    pi_readiness_status            VARCHAR(32),
    pi_recommendation              VARCHAR(32),
    live_gate_status               VARCHAR(32),
    onboarding_status              VARCHAR(32),
    live_closure_status            VARCHAR(32),
    live_pilot_status              VARCHAR(32),
    latest_review_code             VARCHAR(180),
    latest_gate_code               VARCHAR(180),
    latest_onboarding_code         VARCHAR(180),
    latest_closure_code            VARCHAR(180),
    latest_pilot_code              VARCHAR(180),
    blocking_issues                TEXT[] NOT NULL DEFAULT '{}',
    required_actions               TEXT[] NOT NULL DEFAULT '{}',
    evidence                       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                  TEXT,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (status IN ('ready', 'conditional', 'review_required', 'blocked', 'no_contract')),
    CHECK (procurement_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (readiness_score >= 0 AND readiness_score <= 100),
    CHECK (procurement_status IN ('draft', 'review_required', 'active', 'suspended', 'expired', 'terminated', 'blocked')),
    CHECK (contract_status IN ('none', 'draft', 'active', 'expired', 'terminated')),
    CHECK (commercial_clearance IN ('clear', 'review_required', 'blocked')),
    CHECK (redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (entitlement_status IN ('active', 'review_required', 'blocked', 'expired', 'suspended')),
    CHECK (entitlement_allowed_role IN ('blocked', 'research_only', 'validator', 'backup', 'primary_candidate')),
    CHECK (entitlement_redistribution_allowed IN ('yes', 'no', 'unknown')),
    CHECK (rate_limit_per_min IS NULL OR rate_limit_per_min > 0),
    CHECK (daily_quota IS NULL OR daily_quota > 0),
    CHECK (monthly_quota IS NULL OR monthly_quota > 0),
    CHECK (sla_uptime_pct IS NULL OR (sla_uptime_pct >= 0 AND sla_uptime_pct <= 100)),
    CHECK (max_delay_minutes IS NULL OR max_delay_minutes >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_procurement_readiness_lookup
    ON qmeta.vendor_procurement_readiness_snapshot(as_of_date DESC, status, procurement_role);

CREATE INDEX IF NOT EXISTS idx_vendor_procurement_readiness_source_dataset
    ON qmeta.vendor_procurement_readiness_snapshot(source_id, dataset_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_procurement_readiness_contract
    ON qmeta.vendor_procurement_readiness_snapshot(contract_status, commercial_clearance, redistribution_allowed, entitlement_status, as_of_date DESC);

INSERT INTO qmeta.vendor_contract_profile (
    contract_code, source_id, profile_id, provider_name, procurement_status,
    contract_status, commercial_clearance, redistribution_allowed,
    production_use_allowed, contract_owner, legal_owner, business_owner,
    sla_tier, rate_limit_per_min, data_scope, evidence, updated_at
)
SELECT
    'omicron5-contract-vendor_http-draft',
    ss.source_id,
    vip.profile_id,
    'Commercial HTTP Vendor',
    'review_required',
    'draft',
    'review_required',
    'unknown',
    FALSE,
    'platform-data',
    'legal',
    'quant-business',
    'unknown',
    COALESCE(vip.rate_limit_per_min, 120),
    ARRAY['daily_bar', 'security_master', 'trading_calendar', 'adjustment_factor', 'limit_price_daily', 'financial_metric_pit', 'financial_statement_pit']::text[],
    '{"seeded_by":"0039","policy_note":"template only; cannot become primary until active contract, redistribution rights, production use, SLA, quota and dataset entitlement are recorded"}'::jsonb,
    now()
FROM qmeta.source_system ss
LEFT JOIN qmeta.vendor_integration_profile vip ON vip.source_id = ss.source_id AND vip.provider_name = 'vendor_http'
WHERE ss.source_code = 'vendor_http'
ON CONFLICT (contract_code) DO UPDATE SET
    profile_id = COALESCE(qmeta.vendor_contract_profile.profile_id, EXCLUDED.profile_id),
    provider_name = COALESCE(qmeta.vendor_contract_profile.provider_name, EXCLUDED.provider_name),
    rate_limit_per_min = COALESCE(qmeta.vendor_contract_profile.rate_limit_per_min, EXCLUDED.rate_limit_per_min),
    data_scope = CASE
        WHEN qmeta.vendor_contract_profile.data_scope = '{}'::text[] THEN EXCLUDED.data_scope
        ELSE qmeta.vendor_contract_profile.data_scope
    END,
    evidence = qmeta.vendor_contract_profile.evidence || EXCLUDED.evidence,
    updated_at = now();

INSERT INTO qmeta.vendor_contract_dataset_entitlement (
    entitlement_code, contract_id, source_id, dataset_id, entitlement_status,
    allowed_role, commercial_use_allowed, redistribution_allowed,
    production_use_allowed, delivery_mode, frequency, latency_level,
    endpoint_path, schema_status, field_mapping_status, rate_limit_per_min,
    max_delay_minutes, blocking_issues, required_actions, evidence, updated_at
)
SELECT
    'omicron5-entitlement-vendor_http-' || dc.dataset_code,
    vcp.contract_id,
    vcp.source_id,
    dc.dataset_id,
    'review_required',
    'primary_candidate',
    FALSE,
    'unknown',
    FALSE,
    seed.delivery_mode,
    dc.frequency,
    'L3',
    seed.endpoint_path,
    'pending',
    'pending',
    COALESCE(vcp.rate_limit_per_min, 120),
    seed.max_delay_minutes,
    ARRAY[
        'contract_not_active',
        'commercial_use_not_cleared',
        'redistribution_unknown',
        'production_use_not_allowed',
        'dataset_schema_not_validated'
    ]::text[],
    ARRAY[
        'Attach signed master data contract and mark contract_status=active.',
        'Record commercial use, redistribution/cache and production-use rights for this dataset.',
        'Record production quota, rate limit and SLA before any primary routing.',
        'Validate endpoint schema and field mapping with Eta-3/Theta-3 evidence.'
    ]::text[],
    jsonb_build_object('seeded_by', '0039', 'dataset_code', dc.dataset_code, 'policy_note', 'desired primary scope template; blocked until rights are active'),
    now()
FROM (
    VALUES
        ('daily_bar', 'api', '/daily', 1440),
        ('security_master', 'api', '/securities', 1440),
        ('trading_calendar', 'api', '/trading-calendar', 1440),
        ('adjustment_factor', 'api', '/adjustment-factor', 1440),
        ('limit_price_daily', 'api', '/limit-price', 1440),
        ('financial_metric_pit', 'api', '/financial-metrics', 10080),
        ('financial_statement_pit', 'api', '/financial-statements', 10080)
) AS seed(dataset_code, delivery_mode, endpoint_path, max_delay_minutes)
JOIN qmeta.dataset_catalog dc ON dc.dataset_code = seed.dataset_code
JOIN qmeta.vendor_contract_profile vcp ON vcp.contract_code = 'omicron5-contract-vendor_http-draft'
ON CONFLICT (entitlement_code) DO UPDATE SET
    frequency = COALESCE(qmeta.vendor_contract_dataset_entitlement.frequency, EXCLUDED.frequency),
    endpoint_path = COALESCE(qmeta.vendor_contract_dataset_entitlement.endpoint_path, EXCLUDED.endpoint_path),
    max_delay_minutes = COALESCE(qmeta.vendor_contract_dataset_entitlement.max_delay_minutes, EXCLUDED.max_delay_minutes),
    evidence = qmeta.vendor_contract_dataset_entitlement.evidence || EXCLUDED.evidence,
    updated_at = now();

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'omicron5_vendor_contract_readiness_6h', 'vendor_contract_readiness_review', 21600, 600, 600, 300,
    '{"omicron5_min_sla_uptime_pct":99.5,"omicron5_min_rate_limit_per_min":60,"omicron5_require_live_evidence":false}'::jsonb,
    '{"owner":"omicron5","purpose":"review authorized vendor contract, dataset entitlements, SLA, quota and live evidence before primary-source procurement"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;

-- Pi-5: authorized primary vendor production promotion guardrail.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_primary_promotion_run (
    promotion_id                    BIGSERIAL PRIMARY KEY,
    promotion_code                  VARCHAR(180) NOT NULL UNIQUE,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    as_of_date                      DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                    VARCHAR(128) NOT NULL DEFAULT 'pi5',
    trigger_mode                    VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                     VARCHAR(32) NOT NULL DEFAULT 'local',
    promotion_scope                 VARCHAR(32) NOT NULL DEFAULT 'full_market',
    status                          VARCHAR(32) NOT NULL DEFAULT 'blocked',
    apply_mode                      VARCHAR(32) NOT NULL DEFAULT 'review_only',
    routing_change_allowed          BOOLEAN NOT NULL DEFAULT FALSE,
    routing_change_applied          BOOLEAN NOT NULL DEFAULT FALSE,
    dataset_count                   INTEGER NOT NULL DEFAULT 0,
    approved_dataset_count          INTEGER NOT NULL DEFAULT 0,
    pending_dataset_count           INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count           INTEGER NOT NULL DEFAULT 0,
    applied_dataset_count           INTEGER NOT NULL DEFAULT 0,
    canary_ready_count              INTEGER NOT NULL DEFAULT 0,
    full_market_ready_count         INTEGER NOT NULL DEFAULT 0,
    signoff_ready_count             INTEGER NOT NULL DEFAULT 0,
    required_windows                INTEGER[] NOT NULL DEFAULT ARRAY[5, 20, 60],
    require_full_market             BOOLEAN NOT NULL DEFAULT TRUE,
    require_signoff                 BOOLEAN NOT NULL DEFAULT TRUE,
    target_priority                 INTEGER NOT NULL DEFAULT 0,
    current_primary_source_codes    TEXT[] NOT NULL DEFAULT '{}',
    promotion_score                 NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    required_actions                TEXT[] NOT NULL DEFAULT '{}',
    request_payload                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    started_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                     TIMESTAMPTZ,
    duration_ms                     INTEGER,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (promotion_scope IN ('canary', 'full_market')),
    CHECK (status IN ('blocked', 'canary_required', 'full_market_required', 'pending_signoff', 'approved_for_primary', 'applied')),
    CHECK (apply_mode IN ('review_only', 'dry_run', 'apply')),
    CHECK (dataset_count >= 0),
    CHECK (approved_dataset_count >= 0),
    CHECK (pending_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (applied_dataset_count >= 0),
    CHECK (canary_ready_count >= 0),
    CHECK (full_market_ready_count >= 0),
    CHECK (signoff_ready_count >= 0),
    CHECK (array_length(required_windows, 1) IS NOT NULL),
    CHECK (target_priority >= 0),
    CHECK (promotion_score >= 0 AND promotion_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_promotion_run_lookup
    ON qmeta.vendor_primary_promotion_run(source_id, as_of_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_promotion_run_status
    ON qmeta.vendor_primary_promotion_run(status, promotion_scope, started_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_primary_promotion_dataset_result (
    result_id                       BIGSERIAL PRIMARY KEY,
    result_code                     VARCHAR(180) NOT NULL UNIQUE,
    promotion_id                    BIGINT NOT NULL REFERENCES qmeta.vendor_primary_promotion_run(promotion_id) ON DELETE CASCADE,
    source_id                       BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                      BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id               BIGINT REFERENCES qmeta.source_system(source_id),
    procurement_snapshot_id         BIGINT REFERENCES qmeta.vendor_procurement_readiness_snapshot(snapshot_id) ON DELETE SET NULL,
    procurement_snapshot_code       VARCHAR(180),
    readiness_review_id             BIGINT REFERENCES qmeta.vendor_readiness_review(review_id) ON DELETE SET NULL,
    readiness_review_code           VARCHAR(180),
    canary_pilot_id                 BIGINT REFERENCES qmeta.vendor_live_pilot_run(pilot_id) ON DELETE SET NULL,
    canary_pilot_code               VARCHAR(180),
    full_market_pilot_id            BIGINT REFERENCES qmeta.vendor_live_pilot_run(pilot_id) ON DELETE SET NULL,
    full_market_pilot_code          VARCHAR(180),
    current_priority_id             BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    current_primary_source_code     VARCHAR(64),
    current_priority                INTEGER,
    target_priority                 INTEGER NOT NULL DEFAULT 0,
    status                          VARCHAR(32) NOT NULL DEFAULT 'blocked',
    promotion_role                  VARCHAR(32) NOT NULL DEFAULT 'blocked',
    routing_change_allowed          BOOLEAN NOT NULL DEFAULT FALSE,
    routing_change_applied          BOOLEAN NOT NULL DEFAULT FALSE,
    procurement_status              VARCHAR(32),
    procurement_role                VARCHAR(32),
    readiness_status                VARCHAR(32),
    readiness_recommendation        VARCHAR(32),
    readiness_recommended_role      VARCHAR(32),
    canary_status                   VARCHAR(32),
    canary_signoff_status           VARCHAR(32),
    canary_recommendation           VARCHAR(32),
    canary_risk_level               VARCHAR(16),
    full_market_status              VARCHAR(32),
    full_market_signoff_status      VARCHAR(32),
    full_market_recommendation      VARCHAR(32),
    full_market_risk_level          VARCHAR(16),
    promotion_score                 NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                 TEXT[] NOT NULL DEFAULT '{}',
    required_actions                TEXT[] NOT NULL DEFAULT '{}',
    evidence                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('blocked', 'canary_required', 'full_market_required', 'pending_signoff', 'approved_for_primary', 'applied')),
    CHECK (promotion_role IN ('blocked', 'validator', 'backup', 'primary')),
    CHECK (target_priority >= 0),
    CHECK (current_priority IS NULL OR current_priority >= 0),
    CHECK (promotion_score >= 0 AND promotion_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_promotion_result_lookup
    ON qmeta.vendor_primary_promotion_dataset_result(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_promotion_result_evidence
    ON qmeta.vendor_primary_promotion_dataset_result(procurement_snapshot_id, readiness_review_id, canary_pilot_id, full_market_pilot_id);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'pi5_vendor_primary_promotion_6h', 'vendor_primary_promotion_review', 21600, 600, 600, 300,
    '{"pi5_promotion_scope":"full_market","pi5_require_full_market":true,"pi5_require_signoff":true,"pi5_apply_routing":false,"pi5_target_priority":0}'::jsonb,
    '{"owner":"pi5","purpose":"review authorized vendor evidence before primary-source routing promotion; default is review-only"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;

-- Sigma-5: primary vendor production SLA, capacity, cost and scheduler stability.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_primary_stability_snapshot (
    snapshot_id                                BIGSERIAL PRIMARY KEY,
    snapshot_code                              VARCHAR(180) NOT NULL UNIQUE,
    source_id                                  BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id                          BIGINT REFERENCES qmeta.source_system(source_id),
    promotion_id                               BIGINT REFERENCES qmeta.vendor_primary_promotion_run(promotion_id) ON DELETE SET NULL,
    post_promotion_monitor_id                  BIGINT REFERENCES qmeta.vendor_post_promotion_monitor_run(monitor_id) ON DELETE SET NULL,
    as_of_at                                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of_date                                 DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                               VARCHAR(128) NOT NULL DEFAULT 'sigma5',
    trigger_mode                               VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                                VARCHAR(32) NOT NULL DEFAULT 'local',
    monitor_scope                              VARCHAR(32) NOT NULL DEFAULT 'primary_source',
    status                                     VARCHAR(32) NOT NULL DEFAULT 'no_primary_promotion',
    stability_role                             VARCHAR(32) NOT NULL DEFAULT 'watch',
    lookback_hours                             INTEGER NOT NULL DEFAULT 24,
    capacity_window_days                       INTEGER NOT NULL DEFAULT 7,
    min_success_rate                           NUMERIC(8, 6) NOT NULL DEFAULT 0.995000,
    max_error_rate                             NUMERIC(8, 6) NOT NULL DEFAULT 0.005000,
    max_latency_p95_ms                         NUMERIC(12, 4) NOT NULL DEFAULT 2000,
    max_timeout_rate                           NUMERIC(8, 6) NOT NULL DEFAULT 0.010000,
    max_cost_units                             NUMERIC(18, 6) NOT NULL DEFAULT 500,
    max_scheduler_lag_minutes                  INTEGER NOT NULL DEFAULT 90,
    max_backlog_count                          INTEGER NOT NULL DEFAULT 50,
    max_post_promotion_no_applied_count        INTEGER NOT NULL DEFAULT 0,
    dataset_count                              INTEGER NOT NULL DEFAULT 0,
    primary_dataset_count                      INTEGER NOT NULL DEFAULT 0,
    healthy_dataset_count                      INTEGER NOT NULL DEFAULT 0,
    warning_dataset_count                      INTEGER NOT NULL DEFAULT 0,
    critical_dataset_count                     INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count                      INTEGER NOT NULL DEFAULT 0,
    no_primary_dataset_count                   INTEGER NOT NULL DEFAULT 0,
    api_request_count                          BIGINT NOT NULL DEFAULT 0,
    api_failed_count                           BIGINT NOT NULL DEFAULT 0,
    api_error_rate                             NUMERIC(10, 6) NOT NULL DEFAULT 0,
    api_success_rate                           NUMERIC(10, 6) NOT NULL DEFAULT 1,
    api_timeout_count                          BIGINT NOT NULL DEFAULT 0,
    api_timeout_rate                           NUMERIC(10, 6) NOT NULL DEFAULT 0,
    api_latency_p95_ms                         NUMERIC(12, 4) NOT NULL DEFAULT 0,
    rows_returned_count                        BIGINT NOT NULL DEFAULT 0,
    cost_units                                 NUMERIC(18, 6) NOT NULL DEFAULT 0,
    worker_run_count                           INTEGER NOT NULL DEFAULT 0,
    worker_failed_count                        INTEGER NOT NULL DEFAULT 0,
    worker_warning_count                       INTEGER NOT NULL DEFAULT 0,
    scheduler_lag_minutes                      INTEGER NOT NULL DEFAULT 0,
    backlog_count                              INTEGER NOT NULL DEFAULT 0,
    post_promotion_monitor_count               INTEGER NOT NULL DEFAULT 0,
    post_promotion_no_applied_count            INTEGER NOT NULL DEFAULT 0,
    post_promotion_rollback_recommended_count  INTEGER NOT NULL DEFAULT 0,
    open_capacity_alert_count                  INTEGER NOT NULL DEFAULT 0,
    open_critical_capacity_alert_count         INTEGER NOT NULL DEFAULT 0,
    stability_score                            NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                            TEXT[] NOT NULL DEFAULT '{}',
    required_actions                           TEXT[] NOT NULL DEFAULT '{}',
    request_payload                            JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                           JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                              TEXT,
    started_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                                TIMESTAMPTZ,
    duration_ms                                INTEGER,
    created_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (monitor_scope IN ('primary_source', 'all_datasets', 'full_market')),
    CHECK (status IN ('healthy', 'warning', 'critical', 'blocked', 'no_primary_promotion')),
    CHECK (stability_role IN ('primary', 'watch', 'degraded', 'blocked')),
    CHECK (lookback_hours > 0),
    CHECK (capacity_window_days > 0),
    CHECK (min_success_rate >= 0 AND min_success_rate <= 1),
    CHECK (max_error_rate >= 0 AND max_error_rate <= 1),
    CHECK (max_latency_p95_ms >= 0),
    CHECK (max_timeout_rate >= 0 AND max_timeout_rate <= 1),
    CHECK (max_cost_units >= 0),
    CHECK (max_scheduler_lag_minutes >= 0),
    CHECK (max_backlog_count >= 0),
    CHECK (max_post_promotion_no_applied_count >= 0),
    CHECK (dataset_count >= 0),
    CHECK (primary_dataset_count >= 0),
    CHECK (healthy_dataset_count >= 0),
    CHECK (warning_dataset_count >= 0),
    CHECK (critical_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (no_primary_dataset_count >= 0),
    CHECK (api_request_count >= 0),
    CHECK (api_failed_count >= 0),
    CHECK (api_timeout_count >= 0),
    CHECK (rows_returned_count >= 0),
    CHECK (cost_units >= 0),
    CHECK (worker_run_count >= 0),
    CHECK (worker_failed_count >= 0),
    CHECK (worker_warning_count >= 0),
    CHECK (scheduler_lag_minutes >= 0),
    CHECK (backlog_count >= 0),
    CHECK (post_promotion_monitor_count >= 0),
    CHECK (post_promotion_no_applied_count >= 0),
    CHECK (post_promotion_rollback_recommended_count >= 0),
    CHECK (open_capacity_alert_count >= 0),
    CHECK (open_critical_capacity_alert_count >= 0),
    CHECK (stability_score >= 0 AND stability_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_snapshot_lookup
    ON qmeta.vendor_primary_stability_snapshot(source_id, as_of_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_snapshot_status
    ON qmeta.vendor_primary_stability_snapshot(status, stability_role, as_of_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_snapshot_promotion
    ON qmeta.vendor_primary_stability_snapshot(promotion_id, post_promotion_monitor_id);

CREATE TABLE IF NOT EXISTS qmeta.vendor_primary_stability_dataset_snapshot (
    dataset_snapshot_id              BIGSERIAL PRIMARY KEY,
    dataset_snapshot_code            VARCHAR(180) NOT NULL UNIQUE,
    snapshot_id                      BIGINT NOT NULL REFERENCES qmeta.vendor_primary_stability_snapshot(snapshot_id) ON DELETE CASCADE,
    source_id                        BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                       BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id                BIGINT REFERENCES qmeta.source_system(source_id),
    current_priority_id              BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    as_of_date                       DATE NOT NULL DEFAULT CURRENT_DATE,
    monitor_scope                    VARCHAR(32) NOT NULL DEFAULT 'primary_source',
    status                           VARCHAR(32) NOT NULL DEFAULT 'no_primary_promotion',
    stability_role                   VARCHAR(32) NOT NULL DEFAULT 'watch',
    entitlement_status               VARCHAR(32),
    allowed_role                     VARCHAR(32),
    production_use_allowed           BOOLEAN NOT NULL DEFAULT FALSE,
    schema_status                    VARCHAR(32),
    current_primary_source_code      VARCHAR(64),
    current_priority                 INTEGER,
    is_primary_route                 BOOLEAN NOT NULL DEFAULT FALSE,
    promotion_status                 VARCHAR(32),
    promotion_result_status          VARCHAR(32),
    post_promotion_status            VARCHAR(32),
    api_request_count                BIGINT NOT NULL DEFAULT 0,
    api_failed_count                 BIGINT NOT NULL DEFAULT 0,
    api_error_rate                   NUMERIC(10, 6) NOT NULL DEFAULT 0,
    api_success_rate                 NUMERIC(10, 6) NOT NULL DEFAULT 1,
    api_timeout_count                BIGINT NOT NULL DEFAULT 0,
    api_timeout_rate                 NUMERIC(10, 6) NOT NULL DEFAULT 0,
    api_latency_p95_ms               NUMERIC(12, 4) NOT NULL DEFAULT 0,
    rows_returned_count              BIGINT NOT NULL DEFAULT 0,
    cost_units                       NUMERIC(18, 6) NOT NULL DEFAULT 0,
    stability_score                  NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                  TEXT[] NOT NULL DEFAULT '{}',
    required_actions                 TEXT[] NOT NULL DEFAULT '{}',
    evidence                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                    TEXT,
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (monitor_scope IN ('primary_source', 'all_datasets', 'full_market')),
    CHECK (status IN ('healthy', 'warning', 'critical', 'blocked', 'no_primary_promotion')),
    CHECK (stability_role IN ('primary', 'watch', 'degraded', 'blocked')),
    CHECK (current_priority IS NULL OR current_priority >= 0),
    CHECK (api_request_count >= 0),
    CHECK (api_failed_count >= 0),
    CHECK (api_timeout_count >= 0),
    CHECK (rows_returned_count >= 0),
    CHECK (cost_units >= 0),
    CHECK (stability_score >= 0 AND stability_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_dataset_lookup
    ON qmeta.vendor_primary_stability_dataset_snapshot(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_dataset_snapshot
    ON qmeta.vendor_primary_stability_dataset_snapshot(snapshot_id, status, dataset_snapshot_id DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_primary_stability_dataset_role
    ON qmeta.vendor_primary_stability_dataset_snapshot(stability_role, is_primary_route, created_at DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'sigma5_vendor_primary_stability_1h', 'vendor_primary_stability_monitor', 3600, 600, 600, 300,
    '{"sigma5_monitor_scope":"primary_source","sigma5_lookback_hours":24,"sigma5_capacity_window_days":7,"sigma5_min_success_rate":0.995,"sigma5_max_error_rate":0.005,"sigma5_max_latency_p95_ms":2000,"sigma5_max_timeout_rate":0.01,"sigma5_max_cost_units":500,"sigma5_max_scheduler_lag_minutes":90,"sigma5_max_backlog_count":50,"sigma5_max_post_promotion_no_applied_count":0}'::jsonb,
    '{"owner":"sigma5","purpose":"monitor primary vendor production SLA, API capacity, cost envelope and scheduler stability after Pi-5/Rho-5"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;

-- Tau-5: primary vendor cost optimization, route weight planning and budget stress.

ALTER TABLE qmeta.worker_task_run
    DROP CONSTRAINT IF EXISTS worker_task_run_task_name_check;

ALTER TABLE qmeta.worker_task_run
    ADD CONSTRAINT worker_task_run_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer'
    ));

ALTER TABLE qmeta.worker_schedule
    DROP CONSTRAINT IF EXISTS worker_schedule_task_name_check;

ALTER TABLE qmeta.worker_schedule
    ADD CONSTRAINT worker_schedule_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer'
    ));

ALTER TABLE qmeta.worker_schedule_tick
    DROP CONSTRAINT IF EXISTS worker_schedule_tick_task_name_check;

ALTER TABLE qmeta.worker_schedule_tick
    ADD CONSTRAINT worker_schedule_tick_task_name_check
    CHECK (task_name IN (
        'usage_rollup',
        'alert_dispatch',
        'vendor_benchmark_schedule',
        'free_source_recovery',
        'free_source_recovery_execute',
        'free_source_recovery_health',
        'free_source_admission_review',
        'vendor_contract_readiness_review',
        'vendor_primary_promotion_review',
        'vendor_post_promotion_monitor',
        'vendor_primary_stability_monitor',
        'vendor_cost_optimizer'
    ));

CREATE TABLE IF NOT EXISTS qmeta.vendor_cost_optimization_snapshot (
    optimization_id                         BIGSERIAL PRIMARY KEY,
    optimization_code                       VARCHAR(180) NOT NULL UNIQUE,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    primary_source_id                       BIGINT REFERENCES qmeta.source_system(source_id),
    stability_snapshot_id                   BIGINT REFERENCES qmeta.vendor_primary_stability_snapshot(snapshot_id) ON DELETE SET NULL,
    as_of_at                                TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of_date                              DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_by                            VARCHAR(128) NOT NULL DEFAULT 'tau5',
    trigger_mode                            VARCHAR(32) NOT NULL DEFAULT 'manual',
    environment                             VARCHAR(32) NOT NULL DEFAULT 'local',
    optimization_scope                      VARCHAR(32) NOT NULL DEFAULT 'primary_source',
    status                                  VARCHAR(32) NOT NULL DEFAULT 'watch',
    optimization_role                       VARCHAR(32) NOT NULL DEFAULT 'cost_watch',
    lookback_hours                          INTEGER NOT NULL DEFAULT 24,
    forecast_window_days                    INTEGER NOT NULL DEFAULT 30,
    monthly_budget_amount                   NUMERIC(24, 8) NOT NULL DEFAULT 10000,
    max_budget_usage_pct                    NUMERIC(10, 6) NOT NULL DEFAULT 0.850000,
    max_daily_quota_usage_pct               NUMERIC(10, 6) NOT NULL DEFAULT 0.850000,
    max_monthly_quota_usage_pct             NUMERIC(10, 6) NOT NULL DEFAULT 0.850000,
    min_stability_score                     NUMERIC(8, 4) NOT NULL DEFAULT 70,
    cost_safety_margin_pct                  NUMERIC(10, 6) NOT NULL DEFAULT 0.150000,
    default_unit_cost                       NUMERIC(20, 8) NOT NULL DEFAULT 0.01000000,
    stress_multipliers                      JSONB NOT NULL DEFAULT '[1,5,10]'::jsonb,
    dataset_count                           INTEGER NOT NULL DEFAULT 0,
    optimized_dataset_count                 INTEGER NOT NULL DEFAULT 0,
    watch_dataset_count                     INTEGER NOT NULL DEFAULT 0,
    over_budget_dataset_count               INTEGER NOT NULL DEFAULT 0,
    quota_risk_dataset_count                INTEGER NOT NULL DEFAULT 0,
    blocked_dataset_count                   INTEGER NOT NULL DEFAULT 0,
    no_primary_dataset_count                INTEGER NOT NULL DEFAULT 0,
    current_request_count                   BIGINT NOT NULL DEFAULT 0,
    forecast_request_count                  BIGINT NOT NULL DEFAULT 0,
    forecast_row_count                      BIGINT NOT NULL DEFAULT 0,
    current_cost_units                      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    forecast_cost_units                     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    monthly_fee                             NUMERIC(24, 8) NOT NULL DEFAULT 0,
    projected_monthly_cost                  NUMERIC(24, 8) NOT NULL DEFAULT 0,
    projected_budget_usage_pct              NUMERIC(12, 8) NOT NULL DEFAULT 0,
    daily_quota                             BIGINT NOT NULL DEFAULT 0,
    monthly_quota                           BIGINT NOT NULL DEFAULT 0,
    projected_daily_request_count           BIGINT NOT NULL DEFAULT 0,
    projected_monthly_request_count         BIGINT NOT NULL DEFAULT 0,
    projected_daily_quota_usage_pct         NUMERIC(12, 8) NOT NULL DEFAULT 0,
    projected_monthly_quota_usage_pct       NUMERIC(12, 8) NOT NULL DEFAULT 0,
    quota_exhaustion_days                   NUMERIC(12, 4),
    recommended_primary_weight_pct          NUMERIC(8, 4) NOT NULL DEFAULT 0,
    recommended_backup_weight_pct           NUMERIC(8, 4) NOT NULL DEFAULT 100,
    recommended_free_source_weight_pct      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    optimization_score                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                         TEXT[] NOT NULL DEFAULT '{}',
    required_actions                        TEXT[] NOT NULL DEFAULT '{}',
    request_payload                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    details                                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                           TEXT,
    started_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                             TIMESTAMPTZ,
    duration_ms                             INTEGER,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (trigger_mode IN ('manual', 'scheduled', 'once', 'smoke', 'api')),
    CHECK (optimization_scope IN ('primary_source', 'all_datasets', 'full_market')),
    CHECK (status IN ('optimized', 'watch', 'over_budget', 'quota_risk', 'blocked', 'no_primary_promotion')),
    CHECK (optimization_role IN ('primary_mix', 'cost_watch', 'budget_guard', 'blocked', 'watch')),
    CHECK (lookback_hours > 0),
    CHECK (forecast_window_days > 0),
    CHECK (monthly_budget_amount > 0),
    CHECK (max_budget_usage_pct >= 0 AND max_budget_usage_pct <= 10),
    CHECK (max_daily_quota_usage_pct >= 0 AND max_daily_quota_usage_pct <= 10),
    CHECK (max_monthly_quota_usage_pct >= 0 AND max_monthly_quota_usage_pct <= 10),
    CHECK (min_stability_score >= 0 AND min_stability_score <= 100),
    CHECK (cost_safety_margin_pct >= 0 AND cost_safety_margin_pct <= 1),
    CHECK (default_unit_cost >= 0),
    CHECK (dataset_count >= 0),
    CHECK (optimized_dataset_count >= 0),
    CHECK (watch_dataset_count >= 0),
    CHECK (over_budget_dataset_count >= 0),
    CHECK (quota_risk_dataset_count >= 0),
    CHECK (blocked_dataset_count >= 0),
    CHECK (no_primary_dataset_count >= 0),
    CHECK (current_request_count >= 0),
    CHECK (forecast_request_count >= 0),
    CHECK (forecast_row_count >= 0),
    CHECK (current_cost_units >= 0),
    CHECK (forecast_cost_units >= 0),
    CHECK (monthly_fee >= 0),
    CHECK (projected_monthly_cost >= 0),
    CHECK (daily_quota >= 0),
    CHECK (monthly_quota >= 0),
    CHECK (projected_daily_request_count >= 0),
    CHECK (projected_monthly_request_count >= 0),
    CHECK (quota_exhaustion_days IS NULL OR quota_exhaustion_days >= 0),
    CHECK (recommended_primary_weight_pct >= 0 AND recommended_primary_weight_pct <= 100),
    CHECK (recommended_backup_weight_pct >= 0 AND recommended_backup_weight_pct <= 100),
    CHECK (recommended_free_source_weight_pct >= 0 AND recommended_free_source_weight_pct <= 100),
    CHECK (optimization_score >= 0 AND optimization_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_cost_optimization_lookup
    ON qmeta.vendor_cost_optimization_snapshot(source_id, as_of_date DESC, status);

CREATE INDEX IF NOT EXISTS idx_vendor_cost_optimization_status
    ON qmeta.vendor_cost_optimization_snapshot(status, optimization_role, as_of_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_cost_optimization_stability
    ON qmeta.vendor_cost_optimization_snapshot(stability_snapshot_id, as_of_at DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_route_weight_plan (
    plan_id                                 BIGSERIAL PRIMARY KEY,
    plan_code                               VARCHAR(180) NOT NULL UNIQUE,
    optimization_id                         BIGINT NOT NULL REFERENCES qmeta.vendor_cost_optimization_snapshot(optimization_id) ON DELETE CASCADE,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                              BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    primary_source_id                       BIGINT REFERENCES qmeta.source_system(source_id),
    backup_source_id                        BIGINT REFERENCES qmeta.source_system(source_id),
    current_priority_id                     BIGINT REFERENCES qmeta.source_priority(priority_id) ON DELETE SET NULL,
    stability_snapshot_id                   BIGINT REFERENCES qmeta.vendor_primary_stability_snapshot(snapshot_id) ON DELETE SET NULL,
    as_of_date                              DATE NOT NULL DEFAULT CURRENT_DATE,
    status                                  VARCHAR(32) NOT NULL DEFAULT 'watch',
    plan_role                               VARCHAR(32) NOT NULL DEFAULT 'watch',
    current_primary_source_code             VARCHAR(64),
    current_priority                        INTEGER,
    is_primary_route                        BOOLEAN NOT NULL DEFAULT FALSE,
    stability_status                        VARCHAR(32),
    stability_score                         NUMERIC(8, 4) NOT NULL DEFAULT 0,
    contract_status                         VARCHAR(32),
    entitlement_status                      VARCHAR(32),
    production_use_allowed                  BOOLEAN NOT NULL DEFAULT FALSE,
    billing_model                           VARCHAR(32),
    billing_currency                        VARCHAR(16) NOT NULL DEFAULT 'CNY',
    unit_cost                               NUMERIC(20, 8) NOT NULL DEFAULT 0,
    monthly_fee_allocated                   NUMERIC(24, 8) NOT NULL DEFAULT 0,
    current_request_count                   BIGINT NOT NULL DEFAULT 0,
    forecast_request_count                  BIGINT NOT NULL DEFAULT 0,
    forecast_row_count                      BIGINT NOT NULL DEFAULT 0,
    current_cost_units                      NUMERIC(24, 8) NOT NULL DEFAULT 0,
    forecast_cost_units                     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    allocated_budget_amount                 NUMERIC(24, 8) NOT NULL DEFAULT 0,
    projected_budget_usage_pct              NUMERIC(12, 8) NOT NULL DEFAULT 0,
    daily_quota                             BIGINT NOT NULL DEFAULT 0,
    monthly_quota                           BIGINT NOT NULL DEFAULT 0,
    projected_daily_request_count           BIGINT NOT NULL DEFAULT 0,
    projected_monthly_request_count         BIGINT NOT NULL DEFAULT 0,
    projected_daily_quota_usage_pct         NUMERIC(12, 8) NOT NULL DEFAULT 0,
    projected_monthly_quota_usage_pct       NUMERIC(12, 8) NOT NULL DEFAULT 0,
    quota_exhaustion_days                   NUMERIC(12, 4),
    recommended_primary_weight_pct          NUMERIC(8, 4) NOT NULL DEFAULT 0,
    recommended_backup_weight_pct           NUMERIC(8, 4) NOT NULL DEFAULT 100,
    recommended_free_source_weight_pct      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    routing_change_allowed                  BOOLEAN NOT NULL DEFAULT FALSE,
    optimization_score                      NUMERIC(8, 4) NOT NULL DEFAULT 0,
    blocking_issues                         TEXT[] NOT NULL DEFAULT '{}',
    required_actions                        TEXT[] NOT NULL DEFAULT '{}',
    evidence                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                           TEXT,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('optimized', 'watch', 'over_budget', 'quota_risk', 'blocked', 'no_primary_promotion')),
    CHECK (plan_role IN ('primary', 'backup_mix', 'validator_only', 'blocked', 'watch')),
    CHECK (current_priority IS NULL OR current_priority >= 0),
    CHECK (stability_score >= 0 AND stability_score <= 100),
    CHECK (unit_cost >= 0),
    CHECK (monthly_fee_allocated >= 0),
    CHECK (current_request_count >= 0),
    CHECK (forecast_request_count >= 0),
    CHECK (forecast_row_count >= 0),
    CHECK (current_cost_units >= 0),
    CHECK (forecast_cost_units >= 0),
    CHECK (allocated_budget_amount >= 0),
    CHECK (daily_quota >= 0),
    CHECK (monthly_quota >= 0),
    CHECK (projected_daily_request_count >= 0),
    CHECK (projected_monthly_request_count >= 0),
    CHECK (quota_exhaustion_days IS NULL OR quota_exhaustion_days >= 0),
    CHECK (recommended_primary_weight_pct >= 0 AND recommended_primary_weight_pct <= 100),
    CHECK (recommended_backup_weight_pct >= 0 AND recommended_backup_weight_pct <= 100),
    CHECK (recommended_free_source_weight_pct >= 0 AND recommended_free_source_weight_pct <= 100),
    CHECK (optimization_score >= 0 AND optimization_score <= 100)
);

CREATE INDEX IF NOT EXISTS idx_vendor_route_weight_plan_lookup
    ON qmeta.vendor_route_weight_plan(source_id, dataset_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_route_weight_plan_optimization
    ON qmeta.vendor_route_weight_plan(optimization_id, status, plan_id DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_route_weight_plan_weight
    ON qmeta.vendor_route_weight_plan(plan_role, recommended_primary_weight_pct DESC, projected_budget_usage_pct DESC);

CREATE TABLE IF NOT EXISTS qmeta.vendor_budget_stress_dataset_snapshot (
    stress_id                               BIGSERIAL PRIMARY KEY,
    stress_code                             VARCHAR(180) NOT NULL UNIQUE,
    optimization_id                         BIGINT NOT NULL REFERENCES qmeta.vendor_cost_optimization_snapshot(optimization_id) ON DELETE CASCADE,
    plan_id                                 BIGINT REFERENCES qmeta.vendor_route_weight_plan(plan_id) ON DELETE CASCADE,
    source_id                               BIGINT NOT NULL REFERENCES qmeta.source_system(source_id),
    dataset_id                              BIGINT NOT NULL REFERENCES qmeta.dataset_catalog(dataset_id),
    as_of_date                              DATE NOT NULL DEFAULT CURRENT_DATE,
    stress_multiplier                       NUMERIC(12, 4) NOT NULL DEFAULT 1,
    status                                  VARCHAR(32) NOT NULL DEFAULT 'watch',
    forecast_request_count                  BIGINT NOT NULL DEFAULT 0,
    forecast_cost_units                     NUMERIC(24, 8) NOT NULL DEFAULT 0,
    projected_budget_usage_pct              NUMERIC(12, 8) NOT NULL DEFAULT 0,
    projected_daily_request_count           BIGINT NOT NULL DEFAULT 0,
    projected_monthly_request_count         BIGINT NOT NULL DEFAULT 0,
    projected_daily_quota_usage_pct         NUMERIC(12, 8) NOT NULL DEFAULT 0,
    projected_monthly_quota_usage_pct       NUMERIC(12, 8) NOT NULL DEFAULT 0,
    quota_exhaustion_days                   NUMERIC(12, 4),
    recommended_action                      VARCHAR(64) NOT NULL DEFAULT 'review',
    blocking_issues                         TEXT[] NOT NULL DEFAULT '{}',
    required_actions                        TEXT[] NOT NULL DEFAULT '{}',
    evidence                                JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message                           TEXT,
    created_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (stress_multiplier > 0),
    CHECK (status IN ('optimized', 'watch', 'over_budget', 'quota_risk', 'blocked', 'no_primary_promotion')),
    CHECK (forecast_request_count >= 0),
    CHECK (forecast_cost_units >= 0),
    CHECK (projected_daily_request_count >= 0),
    CHECK (projected_monthly_request_count >= 0),
    CHECK (quota_exhaustion_days IS NULL OR quota_exhaustion_days >= 0)
);

CREATE INDEX IF NOT EXISTS idx_vendor_budget_stress_dataset_lookup
    ON qmeta.vendor_budget_stress_dataset_snapshot(source_id, dataset_id, stress_multiplier, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vendor_budget_stress_dataset_optimization
    ON qmeta.vendor_budget_stress_dataset_snapshot(optimization_id, status, stress_id DESC);

INSERT INTO qmeta.worker_schedule (
    schedule_code, task_name, frequency_seconds, max_runtime_seconds,
    lock_timeout_seconds, retry_backoff_seconds, task_args, details
) VALUES (
    'tau5_vendor_cost_optimizer_6h', 'vendor_cost_optimizer', 21600, 600, 600, 300,
    '{"tau5_optimization_scope":"primary_source","tau5_lookback_hours":24,"tau5_forecast_window_days":30,"tau5_monthly_budget_amount":10000,"tau5_max_budget_usage_pct":0.85,"tau5_max_daily_quota_usage_pct":0.85,"tau5_max_monthly_quota_usage_pct":0.85,"tau5_min_stability_score":70,"tau5_cost_safety_margin_pct":0.15,"tau5_default_unit_cost":0.01,"tau5_stress_multipliers":[1,5,10]}'::jsonb,
    '{"owner":"tau5","purpose":"optimize primary vendor cost, route weights, quota pressure and budget stress after Sigma-5 stability checks"}'::jsonb
)
ON CONFLICT (schedule_code) DO NOTHING;

-- Upsilon-5 route execution metadata is shared with the standalone migration
-- to keep fresh schema builds and incremental upgrades aligned.
\ir migrations/0044_postgresql_vendor_upsilon5_route_execution.sql

-- Phi-5 runtime route decision audit is shared with the standalone migration
-- so active route-weight policies are visible in fresh schema builds.
\ir migrations/0045_postgresql_vendor_phi5_route_policy_runtime.sql

-- Chi-5 route feedback, circuit breaker and recovery probe state is shared
-- with the standalone migration so fresh builds can avoid unhealthy sources.
\ir migrations/0046_postgresql_vendor_chi5_route_feedback.sql

-- Psi-5 route incident automation is shared with the standalone migration so
-- fresh builds can create route incident actions from Chi-5 signals.
\ir migrations/0047_postgresql_automation_psi5_route_incident.sql
\ir migrations/0048_postgresql_automation_omega5_route_incident_control.sql
\ir migrations/0049_postgresql_automation_alpha6_route_incident_control_health.sql
\ir migrations/0050_postgresql_automation_beta6_route_incident_operations.sql
\ir migrations/0051_postgresql_automation_gamma6_route_incident_approval_api.sql
\ir migrations/0052_postgresql_automation_delta6_route_incident_approval_governance.sql
\ir migrations/0053_postgresql_automation_epsilon6_route_incident_approval_resilience.sql
\ir migrations/0054_postgresql_automation_zeta6_route_incident_approval_release.sql
\ir migrations/0055_postgresql_vendor_eta6_production_source_closure.sql
