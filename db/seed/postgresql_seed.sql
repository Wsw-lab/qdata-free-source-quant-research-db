-- 最小本地联调种子数据
-- 覆盖 SQL backend smoke 所需的 PostgreSQL 侧主数据、PIT、指数、行业、因子元数据和质量数据。

BEGIN;

INSERT INTO qmeta.source_system (
    source_id, source_code, source_name, source_type, license_scope, update_frequency, latency_level, owner
) VALUES
    (1, 'mock_exchange', '本地模拟交易所数据源', 'exchange', 'local smoke only', 'daily', 'L4', 'qdata'),
    (2, 'mock_vendor', '本地模拟数据商', 'vendor', 'local smoke only', 'daily', 'L4', 'qdata'),
    (3, 'mock_index_provider', '本地模拟指数源', 'index_provider', 'local smoke only', 'daily', 'L4', 'qdata')
ON CONFLICT (source_code) DO UPDATE SET
    source_name = EXCLUDED.source_name,
    source_type = EXCLUDED.source_type,
    license_scope = EXCLUDED.license_scope,
    update_frequency = EXCLUDED.update_frequency,
    latency_level = EXCLUDED.latency_level,
    owner = EXCLUDED.owner,
    updated_at = now();

INSERT INTO qmeta.dataset_catalog (
    dataset_id, dataset_code, dataset_name, asset_type, frequency, storage_layer, primary_source_id, pit_required, description
) VALUES
    (1, 'security_master', '证券主数据', 'stock', NULL, 'postgresql', 2, TRUE, '本地 smoke PIT 主数据'),
    (2, 'trading_calendar', '交易日历', NULL, '1d', 'postgresql', 1, FALSE, '本地 smoke 交易日历'),
    (3, 'daily_bar', '日线行情', 'stock', '1d', 'clickhouse', 2, FALSE, '本地 smoke 日线'),
    (4, 'minute_bar', '分钟线行情', 'stock', '1m', 'clickhouse', 2, FALSE, '本地 smoke 分钟线'),
    (5, 'adjustment_factor', '复权因子', 'stock', '1d', 'postgresql', 2, FALSE, '本地 smoke 复权因子'),
    (6, 'limit_price_daily', '涨跌停和交易约束', 'stock', '1d', 'postgresql', 2, FALSE, '本地 smoke 交易约束'),
    (7, 'financial_metric_pit', 'PIT 财务指标', 'stock', 'quarterly', 'postgresql', 2, TRUE, '本地 smoke 财务指标'),
    (8, 'financial_statement_pit', 'PIT 财务报表', 'stock', 'quarterly', 'postgresql', 2, TRUE, '本地 smoke 财务报表'),
    (9, 'index_member_pit', 'PIT 指数成分', 'stock', 'daily', 'postgresql', 3, TRUE, '本地 smoke 指数成分'),
    (10, 'industry_membership_pit', 'PIT 行业分类', 'stock', 'daily', 'postgresql', 2, TRUE, '本地 smoke 行业分类'),
    (11, 'factor_value_daily', '日频因子值', 'stock', '1d', 'clickhouse', 2, TRUE, '本地 smoke 因子值'),
    (12, 'universe_member_pit', 'PIT 股票池成员', 'stock', 'daily', 'postgresql', 2, TRUE, '本地 smoke 股票池成员')
ON CONFLICT (dataset_code) DO UPDATE SET
    dataset_name = EXCLUDED.dataset_name,
    asset_type = EXCLUDED.asset_type,
    frequency = EXCLUDED.frequency,
    storage_layer = EXCLUDED.storage_layer,
    primary_source_id = EXCLUDED.primary_source_id,
    pit_required = EXCLUDED.pit_required,
    description = EXCLUDED.description,
    updated_at = now();

INSERT INTO qmeta.data_batch (
    batch_id, dataset_id, source_id, batch_code, trade_date, natural_date, started_at, finished_at, status, raw_uri, row_count
) VALUES
    (1, 1, 2, 'seed-security-master-20240102', '2018-06-11', '2018-06-11', '2018-06-11 17:59:59+08', '2018-06-11 18:00:01+08', 'success', 'seed://security_master', 3),
    (2, 3, 2, 'seed-daily-bar-20240102', '2024-01-02', '2024-01-02', '2024-01-02 18:00:00+08', '2024-01-02 18:00:01+08', 'success', 'seed://daily_bar', 5),
    (3, 7, 2, 'seed-financial-metric-20210331', '2021-03-31', '2021-04-29', '2021-04-27 19:29:00+08', '2021-04-29 00:01:00+08', 'success', 'seed://financial_metric_pit/2021-03-31', 2),
    (4, 5, 2, 'seed-adjustment-factor-20240102', '2024-01-02', '2024-01-02', '2024-01-02 17:59:59+08', '2024-01-02 18:00:01+08', 'success', 'seed://adjustment_factor/2024-01-02', 3),
    (5, 5, 2, 'seed-adjustment-factor-20240103', '2024-01-03', '2024-01-03', '2024-01-03 17:59:59+08', '2024-01-03 18:00:01+08', 'success', 'seed://adjustment_factor/2024-01-03', 2),
    (6, 8, 2, 'seed-financial-statement-20210331', '2021-03-31', '2021-04-28', '2021-04-27 19:29:00+08', '2021-04-28 00:01:00+08', 'success', 'seed://financial_statement_pit/2021-03-31', 2),
    (7, 8, 2, 'seed-financial-statement-20210630', '2021-06-30', '2021-08-03', '2021-08-02 19:29:00+08', '2021-08-03 00:01:00+08', 'success', 'seed://financial_statement_pit/2021-06-30', 1),
    (8, 9, 3, 'seed-index-member-20231211', '2023-12-11', '2023-12-01', '2023-12-01 17:59:00+08', '2023-12-01 18:01:00+08', 'success', 'seed://index_member_pit/2023-12-11', 3),
    (9, 10, 2, 'seed-industry-membership-20211213', '2021-12-13', '2021-12-10', '2021-12-10 17:59:00+08', '2021-12-10 18:01:00+08', 'success', 'seed://industry_membership_pit/2021-12-13', 3),
    (10, 12, 2, 'seed-universe-member-20240102', '2024-01-02', '2024-01-02', '2024-01-02 17:59:00+08', '2024-01-02 18:01:00+08', 'success', 'seed://universe_member_pit/2024-01-02', 2),
    (11, 6, 2, 'seed-limit-price-20240102', '2024-01-02', '2024-01-02', '2024-01-02 17:59:00+08', '2024-01-02 18:01:00+08', 'success', 'seed://limit_price_daily/2024-01-02', 3),
    (12, 6, 2, 'seed-limit-price-20240103', '2024-01-03', '2024-01-03', '2024-01-03 17:59:00+08', '2024-01-03 18:01:00+08', 'success', 'seed://limit_price_daily/2024-01-03', 2),
    (13, 11, 2, 'seed-factor-momentum-20240102', '2024-01-02', '2024-01-02', '2024-01-02 18:29:00+08', '2024-01-02 18:31:00+08', 'success', 'seed://factor_value_daily/momentum_20d/2024-01-02', 2),
    (14, 11, 2, 'seed-factor-roe-20240102', '2024-01-02', '2024-01-02', '2024-01-02 18:29:00+08', '2024-01-02 18:31:00+08', 'success', 'seed://factor_value_daily/roe_ttm/2024-01-02', 2)
ON CONFLICT (batch_code) DO UPDATE SET
    dataset_id = EXCLUDED.dataset_id,
    source_id = EXCLUDED.source_id,
    trade_date = EXCLUDED.trade_date,
    natural_date = EXCLUDED.natural_date,
    started_at = EXCLUDED.started_at,
    finished_at = EXCLUDED.finished_at,
    status = EXCLUDED.status,
    row_count = EXCLUDED.row_count,
    raw_uri = EXCLUDED.raw_uri;

INSERT INTO qmeta.dataset_version (
    data_version, dataset_id, version_code, batch_id, valid_from, status, description
) VALUES
    (1, 1, 'security_master:seed-v1', 1, '2018-06-11 18:00:01+08', 'active', '本地 smoke PIT 证券主数据版本'),
    (2, 3, 'daily_bar:seed-v1', 2, '2024-01-02 18:00:00+08', 'active', '本地 smoke 日线版本'),
    (3, 7, 'financial_metric_pit:seed-v1', 3, '2021-04-29 00:01:00+08', 'active', '本地 smoke 财务指标版本'),
    (4, 5, 'adjustment_factor:seed-20240102-v1', 4, '2024-01-02 18:00:01+08', 'superseded', '本地 smoke 复权因子 2024-01-02 版本'),
    (5, 5, 'adjustment_factor:seed-20240103-v1', 5, '2024-01-03 18:00:01+08', 'active', '本地 smoke 复权因子 2024-01-03 版本'),
    (6, 8, 'financial_statement_pit:seed-20210331-v1', 6, '2021-04-28 00:01:00+08', 'superseded', '本地 smoke 财务报表 2021Q1 版本'),
    (7, 8, 'financial_statement_pit:seed-20210630-v1', 7, '2021-08-03 00:01:00+08', 'active', '本地 smoke 财务报表 2021Q2 版本'),
    (8, 9, 'index_member_pit:seed-v1', 8, '2023-12-01 18:01:00+08', 'active', '本地 smoke 指数成分版本'),
    (9, 10, 'industry_membership_pit:seed-v1', 9, '2021-12-10 18:01:00+08', 'active', '本地 smoke 行业分类版本'),
    (10, 12, 'universe_member_pit:seed-v1', 10, '2024-01-02 18:01:00+08', 'active', '本地 smoke 股票池成员版本'),
    (11, 6, 'limit_price_daily:seed-20240102-v1', 11, '2024-01-02 18:01:00+08', 'superseded', '本地 smoke 交易约束 2024-01-02 版本'),
    (12, 6, 'limit_price_daily:seed-20240103-v1', 12, '2024-01-03 18:01:00+08', 'active', '本地 smoke 交易约束 2024-01-03 版本'),
    (13, 11, 'factor_value_daily:momentum-20240102-v1', 13, '2024-01-02 18:31:00+08', 'active', '本地 smoke 动量因子值版本'),
    (14, 11, 'factor_value_daily:roe-20240102-v1', 14, '2024-01-02 18:31:00+08', 'active', '本地 smoke ROE 因子值版本')
ON CONFLICT (version_code) DO UPDATE SET
    dataset_id = EXCLUDED.dataset_id,
    batch_id = EXCLUDED.batch_id,
    valid_from = EXCLUDED.valid_from,
    status = EXCLUDED.status,
    description = EXCLUDED.description;

INSERT INTO qmeta.security_master (
    security_id, asset_type, exchange, current_symbol, current_name, currency, list_date, delist_date, current_status, primary_source_id
) VALUES
    (1000001, 'stock', 'SH', '600519', '贵州茅台', 'CNY', '2001-08-27', NULL, 'active', 2),
    (1000002, 'stock', 'SZ', '000001', '平安银行', 'CNY', '1991-04-03', NULL, 'active', 2),
    (1000003, 'stock', 'SZ', '300750', '宁德时代', 'CNY', '2018-06-11', NULL, 'active', 2)
ON CONFLICT (asset_type, exchange, current_symbol) DO UPDATE SET
    current_name = EXCLUDED.current_name,
    currency = EXCLUDED.currency,
    list_date = EXCLUDED.list_date,
    delist_date = EXCLUDED.delist_date,
    current_status = EXCLUDED.current_status,
    primary_source_id = EXCLUDED.primary_source_id,
    updated_at = now();

INSERT INTO qmeta.security_identifier_history (
    security_id, symbol, exchange, identifier_type, start_date, end_date,
    announce_time, ingest_time, source_id, batch_id, revision_id, created_at
) VALUES
    (1000001, '600519', 'SH', 'trade_symbol', '2001-08-27', NULL, '2001-08-27 09:00:00+08', '2018-06-11 18:00:00+08', 2, 1, 1, '2018-06-11 18:00:00+08'),
    (1000002, '000001', 'SZ', 'trade_symbol', '1991-04-03', NULL, '1991-04-03 09:00:00+08', '2018-06-11 18:00:00+08', 2, 1, 1, '2018-06-11 18:00:00+08'),
    (1000003, '300750', 'SZ', 'trade_symbol', '2018-06-11', NULL, '2018-06-11 09:00:00+08', '2018-06-11 18:00:00+08', 2, 1, 1, '2018-06-11 18:00:00+08')
ON CONFLICT (security_id, identifier_type, symbol, start_date, revision_id) DO UPDATE SET
    end_date = EXCLUDED.end_date,
    announce_time = EXCLUDED.announce_time,
    ingest_time = EXCLUDED.ingest_time,
    source_id = EXCLUDED.source_id,
    batch_id = EXCLUDED.batch_id,
    created_at = EXCLUDED.created_at;

INSERT INTO qmeta.security_name_history (
    security_id, name, start_date, end_date, announce_time, ingest_time,
    source_id, batch_id, revision_id, created_at
) VALUES
    (1000001, '贵州茅台', '2001-08-27', NULL, '2001-08-27 09:00:00+08', '2018-06-11 18:00:00+08', 2, 1, 1, '2018-06-11 18:00:00+08'),
    (1000002, '平安银行', '1991-04-03', NULL, '1991-04-03 09:00:00+08', '2018-06-11 18:00:00+08', 2, 1, 1, '2018-06-11 18:00:00+08'),
    (1000003, '宁德时代', '2018-06-11', NULL, '2018-06-11 09:00:00+08', '2018-06-11 18:00:00+08', 2, 1, 1, '2018-06-11 18:00:00+08')
ON CONFLICT (security_id, start_date, revision_id) DO UPDATE SET
    name = EXCLUDED.name,
    end_date = EXCLUDED.end_date,
    announce_time = EXCLUDED.announce_time,
    ingest_time = EXCLUDED.ingest_time,
    source_id = EXCLUDED.source_id,
    batch_id = EXCLUDED.batch_id,
    created_at = EXCLUDED.created_at;

INSERT INTO qmeta.security_status_history (
    security_id, status, start_date, end_date, reason, announce_time,
    ingest_time, source_id, batch_id, revision_id, created_at
) VALUES
    (1000001, 'active', '2001-08-27', NULL, 'seed active status', '2001-08-27 09:00:00+08', '2018-06-11 18:00:00+08', 2, 1, 1, '2018-06-11 18:00:00+08'),
    (1000002, 'active', '1991-04-03', NULL, 'seed active status', '1991-04-03 09:00:00+08', '2018-06-11 18:00:00+08', 2, 1, 1, '2018-06-11 18:00:00+08'),
    (1000003, 'active', '2018-06-11', NULL, 'seed active status', '2018-06-11 09:00:00+08', '2018-06-11 18:00:00+08', 2, 1, 1, '2018-06-11 18:00:00+08')
ON CONFLICT (security_id, status, start_date, revision_id) DO UPDATE SET
    end_date = EXCLUDED.end_date,
    reason = EXCLUDED.reason,
    announce_time = EXCLUDED.announce_time,
    ingest_time = EXCLUDED.ingest_time,
    source_id = EXCLUDED.source_id,
    batch_id = EXCLUDED.batch_id,
    created_at = EXCLUDED.created_at;

INSERT INTO qmeta.trading_calendar (
    exchange, trade_date, is_open, session_type, pretrade_date, next_trade_date, open_time, close_time, source_id
) VALUES
    ('SH', '2024-01-02', TRUE, 'full_day', '2023-12-29', '2024-01-03', '09:30', '15:00', 1),
    ('SH', '2024-01-03', TRUE, 'full_day', '2024-01-02', '2024-01-04', '09:30', '15:00', 1),
    ('SZ', '2024-01-02', TRUE, 'full_day', '2023-12-29', '2024-01-03', '09:30', '15:00', 1),
    ('SZ', '2024-01-03', TRUE, 'full_day', '2024-01-02', '2024-01-04', '09:30', '15:00', 1)
ON CONFLICT (exchange, trade_date) DO UPDATE SET
    is_open = EXCLUDED.is_open,
    session_type = EXCLUDED.session_type,
    pretrade_date = EXCLUDED.pretrade_date,
    next_trade_date = EXCLUDED.next_trade_date,
    open_time = EXCLUDED.open_time,
    close_time = EXCLUDED.close_time,
    source_id = EXCLUDED.source_id,
    updated_at = now();

INSERT INTO qmeta.adjustment_factor (
    security_id, trade_date, factor_forward, factor_backward, ex_right_type,
    announce_time, effective_time, ingest_time, source_id, batch_id, revision_id
) VALUES
    (1000001, '2024-01-02', 0.532100000000, 12.872300000000, 'none', '2024-01-02 18:00:00+08', '2024-01-02 18:00:00+08', '2024-01-02 18:00:01+08', 2, 4, 1),
    (1000001, '2024-01-03', 0.532100000000, 12.872300000000, 'none', '2024-01-03 18:00:00+08', '2024-01-03 18:00:00+08', '2024-01-03 18:00:01+08', 2, 5, 1),
    (1000002, '2024-01-02', 1.123400000000, 5.031200000000, 'none', '2024-01-02 18:00:00+08', '2024-01-02 18:00:00+08', '2024-01-02 18:00:01+08', 2, 4, 1),
    (1000002, '2024-01-03', 1.123400000000, 5.031200000000, 'none', '2024-01-03 18:00:00+08', '2024-01-03 18:00:00+08', '2024-01-03 18:00:01+08', 2, 5, 1),
    (1000003, '2024-01-02', 0.884200000000, 1.733100000000, 'none', '2024-01-02 18:00:00+08', '2024-01-02 18:00:00+08', '2024-01-02 18:00:01+08', 2, 4, 1)
ON CONFLICT DO NOTHING;

INSERT INTO qmeta.limit_price_daily (
    security_id, trade_date, limit_up, limit_down, limit_rule, is_st, is_new_listing,
    source_id, batch_id, ingest_time, revision_id
) VALUES
    (1000001, '2024-01-02', 1842.500000, 1507.500000, 'main_10pct', FALSE, FALSE, 2, 11, '2024-01-02 18:00:00+08', 1),
    (1000001, '2024-01-03', 1867.800000, 1528.200000, 'main_10pct', FALSE, FALSE, 2, 12, '2024-01-03 18:00:00+08', 1),
    (1000002, '2024-01-02', 10.380000, 8.500000, 'main_10pct', FALSE, FALSE, 2, 11, '2024-01-02 18:00:00+08', 1),
    (1000002, '2024-01-03', 10.540000, 8.620000, 'main_10pct', FALSE, FALSE, 2, 12, '2024-01-03 18:00:00+08', 1),
    (1000003, '2024-01-02', 189.480000, 126.320000, 'gem_20pct', FALSE, FALSE, 2, 11, '2024-01-02 18:00:00+08', 1)
ON CONFLICT DO NOTHING;

INSERT INTO qpit.financial_statement_pit (
    security_id, report_period, statement_type, period_type, field_name, field_value, unit,
    announce_time, effective_time, ingest_time, source_id, batch_id, revision_id, is_restated, quality_flag
) VALUES
    (1000001, '2021-03-31', 'income_statement', 'ttm', 'revenue', 27271000000.00000000, 'CNY', '2021-04-27 19:30:00+08', '2021-04-28 00:00:00+08', '2021-04-27 19:31:00+08', 2, 6, 1, FALSE, 'normal'),
    (1000001, '2021-03-31', 'income_statement', 'ttm', 'net_profit_parent', 13954000000.00000000, 'CNY', '2021-04-27 19:30:00+08', '2021-04-28 00:00:00+08', '2021-04-27 19:31:00+08', 2, 6, 1, FALSE, 'normal'),
    (1000001, '2021-06-30', 'income_statement', 'ttm', 'revenue', 50722000000.00000000, 'CNY', '2021-08-02 19:30:00+08', '2021-08-03 00:00:00+08', '2021-08-02 19:31:00+08', 2, 7, 1, FALSE, 'normal')
ON CONFLICT DO NOTHING;

INSERT INTO qpit.financial_metric_pit (
    security_id, report_period, metric_name, metric_value, metric_unit, metric_scope,
    announce_time, effective_time, ingest_time, source_id, batch_id, revision_id, is_restated, quality_flag
) VALUES
    (1000001, '2021-03-31', 'roe_ttm', 0.28300000, 'ratio', 'ttm', '2021-04-27 19:30:00+08', '2021-04-28 00:00:00+08', '2021-04-27 19:31:00+08', 2, 3, 1, FALSE, 'normal'),
    (1000002, '2021-03-31', 'roe_ttm', 0.10400000, 'ratio', 'ttm', '2021-04-28 19:30:00+08', '2021-04-29 00:00:00+08', '2021-04-28 19:31:00+08', 2, 3, 1, FALSE, 'normal')
ON CONFLICT DO NOTHING;

INSERT INTO qmeta.index_master (
    index_id, index_code, exchange, index_name, provider, currency, base_date, launch_date
) VALUES
    (300, '000300.SH', 'SH', '沪深300', 'CSI', 'CNY', '2004-12-31', '2005-04-08'),
    (852, '000852.SH', 'SH', '中证1000', 'CSI', 'CNY', '2004-12-31', '2014-10-17')
ON CONFLICT (index_code, provider) DO UPDATE SET
    index_name = EXCLUDED.index_name,
    exchange = EXCLUDED.exchange,
    updated_at = now();

INSERT INTO qpit.index_member_pit (
    index_id, security_id, effective_date, end_date, weight, announce_time,
    ingest_time, source_id, batch_id, revision_id
) VALUES
    (300, 1000001, '2023-12-11', NULL, 0.0612000000, '2023-12-01 18:00:00+08', '2023-12-01 18:00:30+08', 3, 8, 1),
    (300, 1000002, '2023-12-11', NULL, 0.0048000000, '2023-12-01 18:00:00+08', '2023-12-01 18:00:30+08', 3, 8, 1),
    (852, 1000003, '2023-12-11', NULL, 0.0081000000, '2023-12-01 18:00:00+08', '2023-12-01 18:00:30+08', 3, 8, 1)
ON CONFLICT DO NOTHING;

INSERT INTO qmeta.industry_system (
    industry_system_id, system_code, system_name, provider, version
) VALUES
    (1, 'sw', '申万行业分类', 'SW', '2021')
ON CONFLICT (system_code) DO UPDATE SET
    system_name = EXCLUDED.system_name,
    provider = EXCLUDED.provider,
    version = EXCLUDED.version,
    updated_at = now();

INSERT INTO qmeta.industry_category (
    industry_id, industry_system_id, industry_code, industry_name, level, parent_industry_id, start_date, end_date
) VALUES
    (101, 1, '801120', '食品饮料', 1, NULL, '2021-12-13', NULL),
    (102, 1, '801780', '银行', 1, NULL, '2021-12-13', NULL),
    (103, 1, '801730', '电力设备', 1, NULL, '2021-12-13', NULL)
ON CONFLICT (industry_system_id, industry_code, level) DO UPDATE SET
    industry_name = EXCLUDED.industry_name,
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date;

INSERT INTO qmeta.industry_category_history (
    industry_id, industry_system_id, industry_code, industry_name, level,
    parent_industry_id, start_date, end_date, announce_time, ingest_time,
    source_id, batch_id, revision_id, created_at
) VALUES
    (101, 1, '801120', '食品饮料', 1, NULL, '2021-12-13', NULL, '2021-12-10 18:00:00+08', '2021-12-10 18:00:30+08', 2, 9, 1, '2021-12-10 18:00:30+08'),
    (102, 1, '801780', '银行', 1, NULL, '2021-12-13', NULL, '2021-12-10 18:00:00+08', '2021-12-10 18:00:30+08', 2, 9, 1, '2021-12-10 18:00:30+08'),
    (103, 1, '801730', '电力设备', 1, NULL, '2021-12-13', NULL, '2021-12-10 18:00:00+08', '2021-12-10 18:00:30+08', 2, 9, 1, '2021-12-10 18:00:30+08')
ON CONFLICT (industry_id, start_date, revision_id) DO UPDATE SET
    industry_system_id = EXCLUDED.industry_system_id,
    industry_code = EXCLUDED.industry_code,
    industry_name = EXCLUDED.industry_name,
    level = EXCLUDED.level,
    parent_industry_id = EXCLUDED.parent_industry_id,
    end_date = EXCLUDED.end_date,
    announce_time = EXCLUDED.announce_time,
    ingest_time = EXCLUDED.ingest_time,
    source_id = EXCLUDED.source_id,
    batch_id = EXCLUDED.batch_id,
    created_at = EXCLUDED.created_at;

INSERT INTO qpit.industry_membership_pit (
    security_id, industry_system_id, industry_id, effective_date, end_date,
    announce_time, ingest_time, source_id, batch_id, revision_id
) VALUES
    (1000001, 1, 101, '2021-12-13', NULL, '2021-12-10 18:00:00+08', '2021-12-10 18:00:30+08', 2, 9, 1),
    (1000002, 1, 102, '2021-12-13', NULL, '2021-12-10 18:00:00+08', '2021-12-10 18:00:30+08', 2, 9, 1),
    (1000003, 1, 103, '2021-12-13', NULL, '2021-12-10 18:00:00+08', '2021-12-10 18:00:30+08', 2, 9, 1)
ON CONFLICT DO NOTHING;

INSERT INTO qmeta.universe_definition (
    universe_id, universe_code, universe_name, universe_type, description, owner
) VALUES
    (800, 'zz800', '中证800 本地模拟股票池', 'manual', '本地 smoke 股票池', 'qdata')
ON CONFLICT (universe_code) DO UPDATE SET
    universe_name = EXCLUDED.universe_name,
    description = EXCLUDED.description,
    updated_at = now();

INSERT INTO qpit.universe_member_pit (
    universe_id, security_id, effective_date, end_date, weight, announce_time,
    ingest_time, revision_id, source_id, batch_id
) VALUES
    (800, 1000001, '2024-01-02', NULL, 0.6000000000, '2024-01-02 18:00:00+08', '2024-01-02 18:00:30+08', 1, 2, 10),
    (800, 1000002, '2024-01-02', NULL, 0.4000000000, '2024-01-02 18:00:00+08', '2024-01-02 18:00:30+08', 1, 2, 10)
ON CONFLICT DO NOTHING;

INSERT INTO qmeta.factor_definition (
    factor_id, factor_code, factor_name, factor_type, frequency, description, owner, default_direction, is_pit_safe, status
) VALUES
    (1, 'momentum_20d', '20日动量', 'price_volume', '1d', '本地 smoke 动量因子', 'qdata', 1, TRUE, 'published'),
    (2, 'roe_ttm', 'ROE TTM', 'fundamental', '1d', '本地 smoke 基本面因子', 'qdata', 1, TRUE, 'published')
ON CONFLICT (factor_code) DO UPDATE SET
    factor_name = EXCLUDED.factor_name,
    factor_type = EXCLUDED.factor_type,
    frequency = EXCLUDED.frequency,
    description = EXCLUDED.description,
    owner = EXCLUDED.owner,
    default_direction = EXCLUDED.default_direction,
    is_pit_safe = EXCLUDED.is_pit_safe,
    status = EXCLUDED.status,
    updated_at = now();

INSERT INTO qmeta.factor_version (
    factor_version_id, factor_id, version_code, code_repo, code_commit, input_datasets, input_data_versions, parameter_json, published_at, status
) VALUES
    (1, 1, 'v1', 'local://factor/momentum_20d', 'seed', '["daily_bar"]'::jsonb, '["daily_bar:seed-v1"]'::jsonb, '{"window": 20}'::jsonb, '2024-01-02 18:00:00+08', 'published'),
    (2, 2, 'v1', 'local://factor/roe_ttm', 'seed', '["financial_metric_pit"]'::jsonb, '["financial_metric_pit:seed-v1"]'::jsonb, '{}'::jsonb, '2024-01-02 18:00:00+08', 'published')
ON CONFLICT (factor_id, version_code) DO UPDATE SET
    code_repo = EXCLUDED.code_repo,
    code_commit = EXCLUDED.code_commit,
    input_datasets = EXCLUDED.input_datasets,
    input_data_versions = EXCLUDED.input_data_versions,
    parameter_json = EXCLUDED.parameter_json,
    published_at = EXCLUDED.published_at,
    status = EXCLUDED.status;

INSERT INTO qmeta.data_quality_check_result (
    dataset_id, batch_id, check_date, check_name, check_type, status, severity,
    metric_value, threshold_value, affected_rows, details
) VALUES
    (3, 2, '2024-01-02', 'daily_bar_completeness', 'completeness', 'pass', 'info', 1.00000000, 0.99900000, 0, '{"note": "seed data"}'::jsonb),
    (4, 2, '2024-01-02', 'minute_bar_gap_check', 'completeness', 'warning', 'medium', 0.99500000, 0.99900000, 2, '{"note": "seed warning example"}'::jsonb);

SELECT setval(pg_get_serial_sequence('qmeta.source_system', 'source_id'), GREATEST((SELECT MAX(source_id) FROM qmeta.source_system), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.dataset_catalog', 'dataset_id'), GREATEST((SELECT MAX(dataset_id) FROM qmeta.dataset_catalog), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.data_batch', 'batch_id'), GREATEST((SELECT MAX(batch_id) FROM qmeta.data_batch), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.dataset_version', 'data_version'), GREATEST((SELECT MAX(data_version) FROM qmeta.dataset_version), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.security_master', 'security_id'), GREATEST((SELECT MAX(security_id) FROM qmeta.security_master), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.index_master', 'index_id'), GREATEST((SELECT MAX(index_id) FROM qmeta.index_master), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.industry_system', 'industry_system_id'), GREATEST((SELECT MAX(industry_system_id) FROM qmeta.industry_system), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.industry_category', 'industry_id'), GREATEST((SELECT MAX(industry_id) FROM qmeta.industry_category), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.universe_definition', 'universe_id'), GREATEST((SELECT MAX(universe_id) FROM qmeta.universe_definition), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.factor_definition', 'factor_id'), GREATEST((SELECT MAX(factor_id) FROM qmeta.factor_definition), 1), TRUE);
SELECT setval(pg_get_serial_sequence('qmeta.factor_version', 'factor_version_id'), GREATEST((SELECT MAX(factor_version_id) FROM qmeta.factor_version), 1), TRUE);

COMMIT;
