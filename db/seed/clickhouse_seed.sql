-- 最小本地联调种子数据
-- 覆盖 SQL backend smoke 所需的 ClickHouse 侧行情、分钟线、因子时间序列。

INSERT INTO qts.daily_bar (
    security_id, trade_date, open, high, low, close, pre_close, volume, amount, vwap,
    turnover_rate, limit_up, limit_down, is_suspended, source_id, batch_id, data_version,
    ingest_time, quality_flag
) VALUES
    (1000001, '2024-01-02', 1680.00, 1702.00, 1670.00, 1698.00, 1675.00, 12500000.0, 21000000000.0, 1680.00, 0.0135, 1842.50, 1507.50, 0, 2, 2, 2, '2024-01-02 18:00:00.000', 'normal'),
    (1000001, '2024-01-03', 1696.00, 1710.00, 1688.00, 1705.00, 1698.00, 11200000.0, 19096000000.0, 1705.00, 0.0121, 1867.80, 1528.20, 0, 2, 2, 2, '2024-01-03 18:00:00.000', 'normal'),
    (1000002, '2024-01-02', 9.45, 9.62, 9.38, 9.58, 9.44, 86000000.0, 820000000.0, 9.53, 0.0044, 10.38, 8.50, 0, 2, 2, 2, '2024-01-02 18:00:00.000', 'normal'),
    (1000002, '2024-01-03', 9.56, 9.72, 9.50, 9.66, 9.58, 78000000.0, 752000000.0, 9.64, 0.0040, 10.54, 8.62, 0, 2, 2, 2, '2024-01-03 18:00:00.000', 'normal'),
    (1000003, '2024-01-02', 158.20, 162.50, 157.30, 161.80, 157.90, 42000000.0, 6750000000.0, 160.71, 0.0128, 189.48, 126.32, 0, 2, 2, 2, '2024-01-02 18:00:00.000', 'normal');

INSERT INTO qts.minute_bar (
    security_id, trade_date, bar_time, open, high, low, close, volume, amount, vwap,
    source_id, batch_id, data_version, ingest_time, quality_flag
) VALUES
    (1000001, '2024-01-02', '2024-01-02 09:31:00.000', 1680.00, 1685.00, 1679.50, 1684.00, 120000.0, 202080000.0, 1684.00, 2, 2, 2, '2024-01-02 18:00:00.000', 'normal'),
    (1000001, '2024-01-02', '2024-01-02 09:32:00.000', 1684.00, 1686.00, 1681.00, 1682.00, 98000.0, 164836000.0, 1682.00, 2, 2, 2, '2024-01-02 18:00:00.000', 'normal');

INSERT INTO qts.factor_value_daily (
    factor_id, factor_version_id, security_id, trade_date, factor_value, universe_id,
    calc_time, data_version, quality_flag
) VALUES
    (1, 1, 1000001, '2024-01-02', 0.032, 800, '2024-01-02 18:30:00.000', 2, 'normal'),
    (1, 1, 1000002, '2024-01-02', -0.011, 800, '2024-01-02 18:30:00.000', 2, 'normal'),
    (2, 2, 1000001, '2024-01-02', 0.283, 800, '2024-01-02 18:30:00.000', 3, 'normal'),
    (2, 2, 1000002, '2024-01-02', 0.104, 800, '2024-01-02 18:30:00.000', 3, 'normal');

INSERT INTO qts.factor_quality_daily (
    factor_id, factor_version_id, trade_date, universe_id, coverage_rate, missing_rate,
    outlier_rate, mean_value, std_value, min_value, max_value, calc_time
) VALUES
    (1, 1, '2024-01-02', 800, 1.0, 0.0, 0.0, 0.0105, 0.0304, -0.011, 0.032, '2024-01-02 18:31:00.000'),
    (2, 2, '2024-01-02', 800, 1.0, 0.0, 0.0, 0.1935, 0.1266, 0.104, 0.283, '2024-01-02 18:31:00.000');

INSERT INTO qts.market_data_health_daily (
    dataset_code, trade_date, expected_rows, actual_rows, missing_rows, duplicate_rows,
    abnormal_rows, completeness_rate, latest_ingest_time, status, details
) VALUES
    ('daily_bar', '2024-01-02', 3, 3, 0, 0, 0, 1.0, '2024-01-02 18:00:00.000', 'pass', '{"note":"seed data"}'),
    ('minute_bar', '2024-01-02', 2, 2, 0, 0, 0, 1.0, '2024-01-02 18:00:00.000', 'pass', '{"note":"seed data"}');
