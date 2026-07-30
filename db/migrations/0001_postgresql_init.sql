-- 中国量化金融数据底座核心数据模型 DDL
-- 说明：
-- 1. PostgreSQL 负责主数据、元数据、PIT 数据、权限审计和事件状态。
-- 2. ClickHouse 负责行情、分钟线、因子值等大规模时间序列。
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
    CHECK (current_status IN ('prelisted', 'active', 'suspended', 'delisted', 'terminated', 'unknown'))
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
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
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
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
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
    source_id           BIGINT REFERENCES qmeta.source_system(source_id),
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

-- ============================================================
-- ClickHouse: market data and factor time series
