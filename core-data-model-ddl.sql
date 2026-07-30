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
        'runtime_daily_degraded'
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
        'runtime_daily_degraded'
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
        'runtime_daily_degraded'
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
ORDER BY (security_id, trade_date);

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
ORDER BY (security_id, trade_date, bar_time);

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
ORDER BY (factor_id, trade_date, security_id, factor_version_id);

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
