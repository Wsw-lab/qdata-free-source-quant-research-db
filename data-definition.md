# 核心数据字段口径文档

## 1. 文档目标

本文用于定义 A 股量化数据底座 MVP 核心数据集的字段含义、数据来源、更新频率、单位、时间口径、空值含义和待确认事项。

存储结构以 `db/migrations/0001_postgresql_init.sql`（PostgreSQL）和
`db/migrations/0002_clickhouse_init.sql`（ClickHouse）为 canonical fresh-install
定义；已有环境只应用对应数据库的后续版本化迁移。本文定义业务口径，不作为可执行 DDL。

## 2. 通用字段口径

| 字段名 | 中文含义 | 类型 | 口径 | 样例 |
|---|---|---|---|---|
| `security_id` | 证券内部唯一 ID | BIGINT | 系统生成，证券生命周期内稳定，不随代码和简称变更而变化 | `1000001` |
| `symbol` | 交易代码 | STRING | 带交易所后缀或在接口层统一展示为标准代码 | `600519.SH` |
| `exchange` | 交易所 | STRING | 上交所、深交所、北交所等 | `SH`, `SZ`, `BJ` |
| `asset_type` | 资产类型 | STRING | 股票、ETF、可转债、指数等 | `stock` |
| `trade_date` | 交易日 | DATE | 交易所交易日，不等同自然日 | `2026-07-23` |
| `natural_date` | 自然日期 | DATE | 采集或事件发生的自然日期 | `2026-07-23` |
| `report_period` | 报告期 | DATE | 财务报告对应期末日期 | `2026-03-31` |
| `announce_time` | 外部披露时间 | TIMESTAMP | 交易所、上市公司或数据源对外披露时间 | `2026-04-29 19:30:00` |
| `effective_time` | 生效时间 | TIMESTAMP | 事件、分类、成分、规则实际生效时间 | `2026-05-06 09:30:00` |
| `ingest_time` | 入库时间 | TIMESTAMP | 本系统首次接收或写入该版本数据的时间 | `2026-04-29 19:31:12` |
| `vendor_time` | 供应商时间 | TIMESTAMP | 数据供应商返回或标记的更新时间 | `2026-04-29 19:30:30` |
| `batch_id` | 采集批次 ID | BIGINT | 对应一次采集、回补或修正任务 | `98231` |
| `revision_id` | 修订版本 | BIGINT | 同一业务事实的版本号，从 1 开始递增 | `2` |
| `source_id` | 数据源 ID | BIGINT | 对应 `source_system` | `3` |
| `data_version` | 数据版本 | BIGINT | 可复现实验和审计使用的数据版本 | `202607230001` |
| `quality_flag` | 质量标记 | STRING | 标记正常、缺失、异常、多源冲突等 | `normal` |

## 3. 时间口径

### 3.1 Point-in-Time 查询口径

当接口参数中使用 `asof_date` 或 `asof_time` 时，系统只能返回满足以下条件的数据：

- `announce_time <= asof_time`。
- `effective_time <= asof_time`，如该字段适用。
- `ingest_time <= asof_time`，当查询模式要求系统可见时。
- 未被后续版本在该时点前召回或覆盖。

### 3.2 三种查询模式

| 模式 | 含义 | 适用场景 |
|---|---|---|
| `latest` | 返回当前最新版本 | 展示、日常分析 |
| `asof` | 返回历史时点当时可见版本 | 回测、因子研究 |
| `vintage` | 返回指定数据版本 | 审计、复现实验 |

### 3.3 日期和时区

- 所有交易日期使用中国交易所日历。
- 所有时间戳默认按 `Asia/Shanghai` 解释。
- API 可以返回 ISO 8601 格式。
- 数据库存储应统一使用带时区时间戳或显式记录时区。

## 4. 空值和异常值

| 情况 | 处理方式 | 说明 |
|---|---|---|
| 原始数据缺失 | 字段为 NULL，`quality_flag=missing` | 不用 0 代替缺失 |
| 权限不可见 | 接口返回权限错误或字段置空并说明 | 不能伪装成缺失 |
| 停牌无成交 | 行情价格可保留前值，成交量和成交额为 0 或按源口径记录 | 必须配合 `is_suspended` |
| 新股无历史 | 保持 NULL | 由股票池规则处理 |
| 多源冲突 | 保留主源值并记录冲突 | `quality_flag=vendor_conflict` |
| 异常跳变 | 保留原值并标记异常 | 不直接静默修正 |

## 5. 证券主数据

### 5.1 `security_master`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `security_id` | 内部证券 ID | 系统生成 | 新增证券时 | 生命周期稳定 | `1000001` |
| `asset_type` | 资产类型 | 交易所/数据商 | 日级 | MVP 主要为 `stock`、`index` | `stock` |
| `exchange` | 交易所 | 交易所/数据商 | 日级 | SH/SZ/BJ | `SH` |
| `current_symbol` | 当前代码 | 交易所/数据商 | 日级 | 当前有效交易代码 | `600519` |
| `current_name` | 当前简称 | 交易所/公告/数据商 | 日级 | 当前有效证券简称 | `贵州茅台` |
| `currency` | 交易币种 | 交易所 | 低频 | A 股默认 CNY | `CNY` |
| `list_date` | 上市日期 | 交易所/数据商 | 低频 | 首次上市交易日 | `2001-08-27` |
| `delist_date` | 退市日期 | 交易所/公告 | 低频 | 最后交易日或摘牌日，需确认源口径 | `NULL` |
| `current_status` | 当前状态 | 交易所/数据商 | 日级 | active/suspended/delisted 等 | `active` |

待确认：

- 北交所和老三板证券是否纳入 MVP。
- 退市日期采用最后交易日还是摘牌日。

### 5.2 `security_identifier_history`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `symbol` | 历史代码 | 交易所/数据商 | 日级 | 某时间段有效代码 | `600519` |
| `identifier_type` | 代码类型 | 系统枚举 | 低频 | `trade_symbol`、`isin`、`vendor_symbol` | `trade_symbol` |
| `start_date` | 开始日期 | 交易所/公告 | 事件驱动 | 代码开始有效日期 | `2001-08-27` |
| `end_date` | 结束日期 | 交易所/公告 | 事件驱动 | 代码结束有效日期，当前有效为 NULL | `NULL` |

## 6. 交易日历

### 6.1 `trading_calendar`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `exchange` | 交易所 | 交易所 | 年度/临时 | SH/SZ/BJ | `SH` |
| `trade_date` | 交易日 | 交易所 | 年度/临时 | 自然日维度 | `2026-07-23` |
| `is_open` | 是否开市 | 交易所 | 年度/临时 | 是否有常规交易 | `true` |
| `session_type` | 交易时段类型 | 交易所 | 年度/临时 | full_day/half_day/special | `full_day` |
| `pretrade_date` | 前一交易日 | 系统计算 | 日级 | 同交易所口径 | `2026-07-22` |
| `next_trade_date` | 后一交易日 | 系统计算 | 日级 | 同交易所口径 | `2026-07-24` |

待确认：

- 是否需要单独建午盘休市时段表。
- 是否需要支持港股半日市。

## 7. 行情数据

### 7.1 `daily_bar`

| 字段名 | 中文含义 | 来源 | 更新频率 | 单位 | 口径 | 样例 |
|---|---|---|---|---|---|---|
| `open` | 开盘价 | 行情源 | 日级 | 元 | 未复权原始价格 | `1680.00` |
| `high` | 最高价 | 行情源 | 日级 | 元 | 未复权原始价格 | `1700.00` |
| `low` | 最低价 | 行情源 | 日级 | 元 | 未复权原始价格 | `1668.00` |
| `close` | 收盘价 | 行情源 | 日级 | 元 | 未复权原始价格 | `1698.00` |
| `pre_close` | 前收盘价 | 行情源 | 日级 | 元 | 未复权原始价格 | `1675.00` |
| `volume` | 成交量 | 行情源 | 日级 | 股 | A 股按股存储，接口可转手 | `12500000` |
| `amount` | 成交额 | 行情源 | 日级 | 元 | 含税费前市场成交额 | `21000000000` |
| `vwap` | 成交均价 | 系统计算/行情源 | 日级 | 元 | `amount / volume`，volume 为 0 时 NULL | `1680.12` |
| `turnover_rate` | 换手率 | 行情源/系统计算 | 日级 | 比例 | 使用自由流通股本还是总股本需标记 | `0.0135` |
| `limit_up` | 涨停价 | 交易规则/行情源 | 日级 | 元 | 当日有效涨停价 | `1842.50` |
| `limit_down` | 跌停价 | 交易规则/行情源 | 日级 | 元 | 当日有效跌停价 | `1507.50` |
| `is_suspended` | 是否停牌 | 交易所/行情源 | 日级 | 布尔 | 当日全日停牌为 1 | `0` |

待确认：

- 成交量统一用股还是手。建议底层用股，SDK 支持参数转换。
- 换手率分母使用总股本、流通股本还是自由流通股本。建议字段扩展区分。

### 7.2 `minute_bar`

| 字段名 | 中文含义 | 来源 | 更新频率 | 单位 | 口径 | 样例 |
|---|---|---|---|---|---|---|
| `bar_time` | K 线结束时间 | 行情源 | 分钟级 | 时间 | 建议使用分钟 bar 结束时间 | `2026-07-23 09:31:00` |
| `open` | 分钟开盘价 | 行情源 | 分钟级 | 元 | 未复权原始价格 | `1680.00` |
| `high` | 分钟最高价 | 行情源 | 分钟级 | 元 | 未复权原始价格 | `1683.00` |
| `low` | 分钟最低价 | 行情源 | 分钟级 | 元 | 未复权原始价格 | `1679.00` |
| `close` | 分钟收盘价 | 行情源 | 分钟级 | 元 | 未复权原始价格 | `1682.00` |
| `volume` | 分钟成交量 | 行情源 | 分钟级 | 股 | 该分钟内成交量 | `120000` |
| `amount` | 分钟成交额 | 行情源 | 分钟级 | 元 | 该分钟内成交额 | `201840000` |

待确认：

- 09:25 集合竞价数据是否纳入分钟线。
- 14:57 至 15:00 收盘集合竞价的分钟归属。

### 7.3 `adjustment_factor`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `factor_forward` | 前复权因子 | 行情源/系统计算 | 事件驱动 | 用于历史价格向当前价格口径调整 | `0.532100000000` |
| `factor_backward` | 后复权因子 | 行情源/系统计算 | 事件驱动 | 用于当前价格向历史累计口径调整 | `12.872300000000` |
| `ex_right_type` | 除权除息类型 | 公告/行情源 | 事件驱动 | 分红、送股、转增、配股等 | `cash_dividend` |

注意：

- 复权因子在回测中存在特殊未来函数风险。价格回测使用复权序列可以接受，但交易信号中使用未来分红事件派生信息需要额外检查。

## 8. 交易约束

### 8.1 `suspension_history`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `start_time` | 停牌开始时间 | 交易所/公告 | 事件驱动 | 停牌开始自然时间 | `2026-07-23 09:30:00` |
| `end_time` | 复牌时间 | 交易所/公告 | 事件驱动 | 未复牌为 NULL | `NULL` |
| `suspension_type` | 停牌类型 | 交易所/公告 | 事件驱动 | 全天停牌、临停等 | `full_day` |
| `reason` | 停牌原因 | 交易所/公告 | 事件驱动 | 文本说明 | `重大事项` |

### 8.2 `limit_price_daily`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `limit_up` | 涨停价 | 交易规则/行情源 | 日级 | 当日交易可达最高价格 | `18.52` |
| `limit_down` | 跌停价 | 交易规则/行情源 | 日级 | 当日交易可达最低价格 | `15.16` |
| `limit_rule` | 涨跌幅规则 | 系统枚举 | 日级 | 主板 10%、ST 5%、创业板 20% 等 | `main_10pct` |
| `is_st` | 是否 ST | 交易所/数据商 | 日级 | 当日是否适用 ST 规则 | `false` |
| `is_new_listing` | 是否新股特殊期 | 交易规则 | 日级 | 是否处于新股涨跌幅特殊规则期 | `false` |

## 8.3 采集调度和水位线

### `pipeline_job`

| 字段名 | 中文含义 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|
| `job_code` | 调度任务编码 | 新增/变更任务时 | 稳定唯一，建议包含数据集和 provider | `daily_market_akshare` |
| `provider` | 数据源 provider | 新增/变更任务时 | 对应代码中的 provider 名称 | `akshare` |
| `symbols` | 股票池 | 新增/变更任务时 | 显式同步股票列表，空数组表示 provider 自行决定 | `{600519.SH,000001.SZ}` |
| `provider_config` | provider 参数 | 新增/变更任务时 | JSON，记录复权、文件路径等参数 | `{"adjust": ""}` |
| `retry_limit` | 失败重试次数 | 新增/变更任务时 | 单次 pipeline run 的最大重试次数 | `1` |
| `all_market` | 是否全市场任务 | 新增/变更任务时 | true 表示由 provider 自动解析股票池 | `true` |
| `batch_size` | 分批拉取大小 | 新增/变更任务时 | 0 表示不分批，大于 0 表示每批证券数 | `100` |
| `max_symbols` | 最大证券数 | 新增/变更任务时 | 灰度或 smoke 限量，生产可为空 | `500` |
| `min_completeness` | 最低完整率 | 新增/变更任务时 | 低于阈值时 pipeline 为 partial_success | `0.99` |
| `skip_closed_days` | 是否跳过非交易日 | 新增/变更任务时 | true 表示 provider 判断闭市后 skipped | `true` |
| `sleep_seconds` | 批次间隔秒数 | 新增/变更任务时 | provider 限频保护 | `0.5` |

### `pipeline_run`

| 字段名 | 中文含义 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|
| `trade_date` | 本次生产交易日 | 每次运行 | 本次采集目标交易日 | `2024-01-04` |
| `attempt` | 尝试次数 | 每次运行 | 同一 job/date 从 1 开始递增 | `2` |
| `run_type` | 运行类型 | 每次运行 | manual/scheduled/backfill/retry/dry_run | `manual` |
| `status` | 运行状态 | 每次运行 | running/success/partial_success/failed/skipped | `success` |
| `row_count` | 入库或产出行数 | 每次运行 | 当前阶段为 daily_bar 行数 | `2` |
| `expected_row_count` | 预期行数 | 每次运行 | 全市场或显式股票池预期应有证券数 | `5531` |
| `missing_count` | 缺失证券数 | 每次运行 | expected 中没有日线记录的证券数量 | `12` |
| `missing_symbols` | 缺失证券清单 | 每次运行 | 便于补跑和排查 | `{300750.SZ}` |
| `completeness_rate` | 完整率 | 每次运行 | 实际覆盖证券数 / 预期证券数 | `0.9978` |
| `expected_by_exchange` | 交易所预期数 | 每次运行 | JSON，按 SH/SZ/BJ 拆分 expected | `{"SH": 2200, "SZ": 3000}` |
| `actual_by_exchange` | 交易所实际数 | 每次运行 | JSON，按 SH/SZ/BJ 拆分实际覆盖 | `{"SH": 2198, "SZ": 2990}` |
| `missing_by_exchange` | 交易所缺失清单 | 每次运行 | JSON，按交易所拆分缺失证券 | `{"SZ": ["300750.SZ"]}` |
| `missing_explanations` | 缺失解释 | 每次运行 | JSON，记录 excluded/missing 的原因 | `{"300750.SZ": {"reason": "unexplained_missing"}}` |
| `batch_count` | 批次数 | 每次运行 | 本次 provider 拉取拆分批次数 | `56` |
| `repair_status` | 修复状态 | 每次运行 | none/queued/resolved/ignored | `queued` |
| `quality_passed` | 质量是否通过 | 每次运行 | 严格质量模式下必须为 true 才成功 | `true` |
| `raw_paths` | 标准化快照路径 | 每次运行 | JSON，指向 raw/vendor 文件 | `{"daily_bar": "raw/vendor/..."}` |

### `pipeline_watermark`

| 字段名 | 中文含义 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|
| `last_success_trade_date` | 最后成功交易日 | 成功运行后 | 只有 success 才推进 | `2024-01-04` |
| `last_attempt_trade_date` | 最后尝试交易日 | 失败或成功后 | 记录最近一次实际尝试，不含默认 skip | `2024-01-04` |
| `consecutive_failures` | 连续失败次数 | 失败或成功后 | 成功清零，失败递增 | `0` |

### `pipeline_repair_queue`

| 字段名 | 中文含义 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|
| `repair_id` | 修复项 ID | 自动生成 | 单条修复队列主键 | `1001` |
| `job_id` | 任务 ID | 进入修复队列时 | 对应 `pipeline_job` | `12` |
| `run_id` | 触发运行 ID | 进入/更新队列时 | 最近一次问题 run 或解决 run | `88` |
| `trade_date` | 待修复交易日 | 进入修复队列时 | 问题数据日期 | `2024-01-04` |
| `reason` | 修复原因 | 进入修复队列时 | failed/partial_success/completeness_below_threshold | `completeness_below_threshold` |
| `status` | 队列状态 | 修复流程更新 | open/in_progress/resolved/ignored | `open` |
| `missing_symbols` | 缺失证券清单 | 进入/更新队列时 | 用于补跑和排查 | `{300750.SZ}` |
| `completeness_rate` | 问题运行完整率 | 进入/更新队列时 | 与触发 run 保持一致 | `0.66666667` |
| `details` | 修复上下文 | 进入/更新队列时 | JSON，含交易所拆分和缺失解释 | `{"missing_by_exchange": {"SZ": ["300750.SZ"]}}` |

## 8.4 Delta 行情口径和矩阵出口

### 可交易股票池

每日可交易股票池由 `Client.get_tradable_universe` 或 `scripts/build_tradable_universe.py` 生成，默认排除：

- ST 或 `*ST`。
- 当日停牌。
- 新股特殊期，默认上市不足 30 天。
- 退市整理期。
- 上市天数小于 `min_list_days` 的证券。

结果可写入 `qpit.universe_member_pit`，默认 `universe_code=tradable_a_share`。

`qmeta.universe_definition.universe_type` 决定 PIT 成员选择语义，创建后不可原地修改。
需要改变类型时应创建新的 universe 定义并重新发布成员历史，避免旧快照被重新解释。

### `matrix_export_audit`

| 字段名 | 中文含义 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|
| `export_id` | 导出审计 ID | 每次矩阵导出 | 单次导出的唯一记录 | `101` |
| `dataset_code` | 数据集编码 | 每次矩阵导出 | 当前为 `daily_bar` | `daily_bar` |
| `field_name` | 导出字段 | 每次矩阵导出 | 宽表矩阵的值字段 | `close` |
| `start_date` | 起始日期 | 每次矩阵导出 | 导出窗口左闭 | `2024-01-04` |
| `end_date` | 结束日期 | 每次矩阵导出 | 导出窗口右闭 | `2024-01-04` |
| `symbol_count` | 证券数量 | 每次矩阵导出 | 宽表列数，不含 `trade_date` | `2` |
| `row_count` | 日期行数 | 每次矩阵导出 | 宽表日期行数 | `1` |
| `output_uri` | 输出路径 | 每次矩阵导出 | 本地或对象存储路径 | `raw/exports/close_matrix.csv` |
| `output_format` | 输出格式 | 每次矩阵导出 | csv/parquet | `csv` |
| `request_summary` | 请求摘要 | 每次矩阵导出 | JSON，记录 symbols、adjust 等 | `{"adjust": "forward"}` |

## 9. Point-in-Time 财务数据

### 9.1 `financial_statement_pit`

| 字段名 | 中文含义 | 来源 | 更新频率 | 单位 | 口径 | 样例 |
|---|---|---|---|---|---|---|
| `statement_type` | 报表类型 | 财报/数据商 | 季度/事件 | 枚举 | balance_sheet/income_statement/cash_flow | `income_statement` |
| `period_type` | 期间类型 | 财报/系统计算 | 季度 | 枚举 | 单季、累计、TTM、年度 | `ytd` |
| `field_name` | 字段名 | 系统标准 | 低频 | 枚举/字典 | 标准英文字段 | `revenue` |
| `field_value` | 字段值 | 财报/数据商 | 季度/修订 | 元 | 统一 CNY，保留原币种字段扩展 | `123456789.12` |
| `announce_time` | 披露时间 | 公告/交易所 | 事件驱动 | 时间 | 外部可见时间 | `2026-04-29 19:30:00` |
| `effective_time` | 生效时间 | 系统规则 | 事件驱动 | 时间 | 量化可使用时间，通常不早于披露时间 | `2026-04-30 00:00:00` |
| `revision_id` | 修订版本 | 系统生成 | 修订时 | 版本 | 同报告期同字段递增 | `2` |
| `is_restated` | 是否重述 | 财报/公告 | 修订时 | 布尔 | 是否财报重述或更正 | `true` |

第一批标准字段：

| 标准字段 | 中文含义 | 报表 | 单位 |
|---|---|---|---|
| `revenue` | 营业收入 | 利润表 | 元 |
| `operating_profit` | 营业利润 | 利润表 | 元 |
| `total_profit` | 利润总额 | 利润表 | 元 |
| `net_profit` | 净利润 | 利润表 | 元 |
| `net_profit_parent` | 归母净利润 | 利润表 | 元 |
| `net_profit_deducted` | 扣非归母净利润 | 利润表/指标 | 元 |
| `total_assets` | 总资产 | 资产负债表 | 元 |
| `total_liabilities` | 总负债 | 资产负债表 | 元 |
| `equity_parent` | 归母权益 | 资产负债表 | 元 |
| `cash_and_equivalents` | 货币资金 | 资产负债表 | 元 |
| `operating_cash_flow` | 经营活动现金流净额 | 现金流量表 | 元 |
| `capex` | 资本开支 | 现金流量表/系统计算 | 元 |

待确认：

- 合并报表和母公司报表是否都保留。建议 MVP 先保留合并报表。
- 财务字段采用数据商标准字段还是自建标准字段映射。

### 9.2 `financial_metric_pit`

| 字段名 | 中文含义 | 来源 | 更新频率 | 单位 | 口径 | 样例 |
|---|---|---|---|---|---|---|
| `metric_name` | 指标名 | 系统标准 | 低频 | 枚举 | 标准英文字段 | `roe_ttm` |
| `metric_value` | 指标值 | 系统计算/数据商 | 季度 | 比例/元 | 需记录计算公式 | `0.1823` |
| `metric_scope` | 指标范围 | 系统枚举 | 季度 | 枚举 | single_quarter/ytd/ttm/annual | `ttm` |

第一批指标：

| 指标 | 中文含义 | 公式或口径 |
|---|---|---|
| `gross_margin` | 毛利率 | 毛利 / 营业收入 |
| `net_margin` | 净利率 | 归母净利润 / 营业收入 |
| `roe_ttm` | ROE TTM | TTM 归母净利润 / 平均归母权益 |
| `roa_ttm` | ROA TTM | TTM 净利润 / 平均总资产 |
| `debt_to_asset` | 资产负债率 | 总负债 / 总资产 |
| `eps` | 每股收益 | 财报披露或系统计算 |
| `ocf_to_profit` | 经营现金流/净利润 | 经营现金流 / 净利润 |

## 10. 业绩预告和快报

### 10.1 `earnings_forecast_pit`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `forecast_type` | 预告类型 | 公告/数据商 | 事件驱动 | 预增、预减、扭亏、续亏等 | `increase` |
| `net_profit_lower` | 净利润下限 | 公告/数据商 | 事件驱动 | 单位元 | `100000000` |
| `net_profit_upper` | 净利润上限 | 公告/数据商 | 事件驱动 | 单位元 | `120000000` |
| `yoy_lower` | 同比下限 | 公告/数据商 | 事件驱动 | 比例 | `0.20` |
| `yoy_upper` | 同比上限 | 公告/数据商 | 事件驱动 | 比例 | `0.40` |

待确认：

- 预告净利润采用归母净利润还是净利润。建议优先归母净利润并在字段名中明确。

### 10.2 `earnings_express_pit`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `revenue` | 营业收入 | 业绩快报 | 事件驱动 | 元 | `1000000000` |
| `net_profit_parent` | 归母净利润 | 业绩快报 | 事件驱动 | 元 | `150000000` |
| `eps` | 每股收益 | 业绩快报 | 事件驱动 | 元/股 | `0.36` |
| `roe` | 净资产收益率 | 业绩快报 | 事件驱动 | 比例 | `0.08` |

## 11. 指数和行业

### 11.1 `index_member_pit`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `index_id` | 指数 ID | 系统生成 | 低频 | 对应指数主表 | `300001` |
| `security_id` | 成分证券 ID | 指数公司/数据商 | 调仓/日级 | 指数成分股 | `1000001` |
| `effective_date` | 生效日期 | 指数公司/数据商 | 调仓 | 成分开始生效日期 | `2026-06-15` |
| `end_date` | 结束日期 | 指数公司/数据商 | 调仓 | 成分结束日期，当前有效为 NULL | `NULL` |
| `weight` | 权重 | 指数公司/数据商 | 调仓/日级 | 比例，0 到 1 | `0.0123` |

待确认：

- 权重是调仓权重、收盘权重还是实时权重。MVP 建议先支持调仓和日频收盘权重。

### 11.2 `industry_membership_pit`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `industry_system_id` | 行业体系 ID | 系统生成 | 低频 | 申万、中信等体系 | `1` |
| `industry_id` | 行业 ID | 系统生成 | 调整时 | 具体行业分类 | `101010` |
| `effective_date` | 生效日期 | 行业分类源 | 调整时 | 行业归属开始日期 | `2021-12-13` |
| `end_date` | 结束日期 | 行业分类源 | 调整时 | 行业归属结束日期，当前有效为 NULL | `NULL` |

待确认：

- 行业调整公告日和实际生效日是否可同时获取。若不能，需在 `quality_flag` 标记。

## 12. 事件数据

### 12.1 `corporate_event_pit`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `event_type` | 事件类型 | 公告/解析引擎 | 事件驱动 | 分红、回购、减持、定增等 | `buyback` |
| `event_time` | 事件发生时间 | 公告/解析引擎 | 事件驱动 | 事件自身发生或开始时间 | `2026-07-23 00:00:00` |
| `event_payload` | 事件结构化内容 | 解析引擎 | 事件驱动 | JSON，按事件类型定义字段 | `{"amount": 100000000}` |
| `confidence` | 解析置信度 | 解析引擎 | 事件驱动 | 0 到 1 | `0.92` |
| `source_doc_id` | 来源文档 ID | 公告系统 | 事件驱动 | 可追溯 PDF/HTML | `cninfo-xxx` |

MVP 第一批事件：

- 分红送转。
- 业绩预告。
- 业绩快报。
- 回购。
- 减持。
- 增持。
- 定增。

## 13. 因子数据

### 13.1 `factor_definition`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `factor_code` | 因子代码 | 研究员/系统 | 新增因子时 | 全局唯一英文代码 | `momentum_20d` |
| `factor_name` | 因子名称 | 研究员/系统 | 新增因子时 | 中文或英文名称 | `20日动量` |
| `factor_type` | 因子类型 | 研究员/系统 | 新增因子时 | 技术、基本面、估值等 | `price_volume` |
| `frequency` | 频率 | 研究员/系统 | 新增因子时 | 1d、1m 等 | `1d` |
| `default_direction` | 默认方向 | 研究员 | 调整时 | 1 为越大越好，-1 为越小越好，0 为无方向 | `1` |
| `is_pit_safe` | 是否通过 PIT 检查 | 系统检查 | 发布时 | 是否可用于严格历史回测 | `true` |
| `status` | 因子状态 | 系统 | 流程驱动 | draft/testing/published | `published` |

### 13.2 `factor_value_daily`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `factor_id` | 因子 ID | 系统生成 | 新增因子时 | 对应因子定义 | `10` |
| `factor_version_id` | 因子版本 ID | 系统生成 | 发布时 | 对应代码和参数版本 | `1003` |
| `trade_date` | 因子日期 | 计算任务 | 日级 | 因子在该交易日可用 | `2026-07-23` |
| `factor_value` | 因子值 | 计算任务 | 日级 | 原始值，不默认标准化 | `0.1234` |
| `universe_id` | 股票池 ID | 计算任务 | 日级 | 可为空，表示全市场 | `300001` |
| `calc_time` | 计算时间 | 系统 | 计算时 | 因子值生成时间 | `2026-07-23 18:00:00` |

`factor_value_daily` 使用普通 `MergeTree` 保存冲突证据。同一因子、证券、交易日、
因子版本、`data_version` 与 `calc_time` 若出现多条记录，存储层不得静默去重；查询层必须
将其判为不可确定并 fail closed。正常重算应发布新的可追溯数据版本，而不是依赖后台合并覆盖。

待确认：

- 因子值是否保存原始值、去极值值、标准化值三套。建议 MVP 先保存原始值，衍生值另建因子或扩展字段。

## 14. 数据质量

### 14.1 `data_quality_check_result`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `check_name` | 检查名称 | 系统 | 每批/每日 | 唯一可读检查名称 | `daily_bar_completeness` |
| `check_type` | 检查类型 | 系统 | 每批/每日 | 完整性、唯一性、一致性等 | `completeness` |
| `status` | 检查状态 | 系统 | 每批/每日 | pass/warning/failed/skipped | `pass` |
| `severity` | 严重级别 | 系统 | 每批/每日 | info 到 critical | `high` |
| `metric_value` | 指标值 | 系统计算 | 每批/每日 | 检查产生的数值 | `0.9998` |
| `threshold_value` | 阈值 | 系统配置 | 每批/每日 | 判定阈值 | `0.9990` |
| `affected_rows` | 影响行数 | 系统计算 | 每批/每日 | 异常或受影响行数 | `12` |

第一批检查：

- 日线完整性。
- 分钟线断点。
- OHLC 合法性。
- 价格涨跌幅异常。
- 成交量成交额异常。
- 复权因子跳变。
- 财务字段缺失。
- 指数成分数量异常。
- 行业归属缺失。
- 因子覆盖率突降。

## 15. 查询审计

### 15.1 `query_audit_log`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `user_id` | 用户 ID | 鉴权系统 | 每次查询 | 调用方用户或服务账号 | `quant_user_01` |
| `api_name` | 接口名 | API 网关 | 每次查询 | SDK 或 REST 接口名称 | `get_price` |
| `request_hash` | 请求摘要 | API 网关 | 每次查询 | 参数 hash，避免记录敏感明文 | `sha256:...` |
| `data_versions` | 数据版本 | 服务层 | 每次查询 | 本次使用的数据版本列表 | `[1001, 1002]` |
| `row_count` | 返回行数 | 服务层 | 每次查询 | 实际返回行数 | `250000` |
| `status` | 查询状态 | 服务层 | 每次查询 | success/failed/partial_success | `success` |

## 16. Epsilon 多源融合和 API 审计

### 16.1 `source_priority`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `dataset_id` | 数据集 ID | 系统配置 | 数据源配置变更时 | 对应 `dataset_catalog` | `daily_bar` |
| `source_id` | 数据源 ID | 系统配置 | 数据源配置变更时 | 对应 `source_system` | `csv_mirror` |
| `priority` | 优先级 | 系统配置 | 数据源配置变更时 | 数字越小优先级越高 | `0` |
| `is_fallback` | 是否可作备源 | 系统配置 | 数据源配置变更时 | 主源失败或缺失时是否可回源 | `true` |
| `effective_date` | 生效日期 | 系统配置 | 数据源配置变更时 | 优先级开始生效日期 | `2024-01-01` |

### 16.2 `data_conflict_daily`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `primary_source_id` | 主源 ID | 多源对账 | 每日/每批 | 当前采纳的数据源 | `csv` |
| `secondary_source_id` | 备源 ID | 多源对账 | 每日/每批 | 对照来源 | `csv_mirror` |
| `symbol` | 证券代码 | 多源对账 | 每日/每批 | 标准交易代码 | `600519.SH` |
| `field_name` | 冲突字段 | 多源对账 | 每日/每批 | 出现差异的数据字段 | `close` |
| `primary_value` | 主源值 | 多源对账 | 每日/每批 | 先以文本保留原始显示 | `1715.0` |
| `secondary_value` | 备源值 | 多源对账 | 每日/每批 | 先以文本保留原始显示 | `1716.715` |
| `absolute_diff` | 绝对差异 | 系统计算 | 每日/每批 | 数值字段的绝对差 | `1.715` |
| `relative_diff` | 相对差异 | 系统计算 | 每日/每批 | 绝对差 / 较大绝对值 | `0.000999` |
| `severity` | 严重级别 | 系统计算 | 每日/每批 | low/medium/high/critical | `high` |
| `status` | 处理状态 | 质控流程 | 人工或自动处理时 | open/accepted/resolved/ignored | `open` |

### 16.3 `multi_source_quality_daily`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `primary_count` | 主源行数 | 多源对账 | 每日 | 主源当日记录数 | `2` |
| `secondary_count` | 备源行数 | 多源对账 | 每日 | 备源当日记录数 | `2` |
| `matched_count` | 匹配行数 | 多源对账 | 每日 | symbol/trade_date 同时存在数量 | `2` |
| `conflict_count` | 字段冲突数 | 多源对账 | 每日 | 字段级冲突记录数 | `2` |
| `coverage_rate` | 备源覆盖率 | 系统计算 | 每日 | matched_count / primary_count | `1.00000000` |
| `conflict_rate` | 字段冲突率 | 系统计算 | 每日 | conflict_count / 可比较字段数 | `0.16666667` |
| `status` | 质量状态 | 系统计算 | 每日 | pass/warning/failed | `warning` |

### 16.4 `api_token`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `token_hash` | Token 哈希 | 鉴权系统 | 新建 token 时 | SHA-256，不保存明文 token | `sha256...` |
| `token_name` | Token 名称 | 鉴权系统 | 新建/变更时 | 便于识别调用方 | `research-dev` |
| `owner` | 所有人 | 鉴权系统 | 新建/变更时 | 用户、服务账号或项目 | `quant_team` |
| `scopes` | 权限范围 | 鉴权系统 | 新建/变更时 | 当前支持 read/admin 基础口径 | `{read}` |
| `quota_per_min` | 每分钟配额 | 鉴权系统 | 新建/变更时 | 单 token 分钟级请求数 | `120` |
| `tenant_id` | 租户 ID | 鉴权系统 | 新建/变更 token 时 | 可为空，非空时参与数据集 ACL 和用量归属 | `demo` |
| `project_id` | 项目 ID | 鉴权系统 | 新建/变更 token 时 | 可为空，非空时用于项目级权限和成本中心 | `quant-research` |
| `principal_id` | 调用主体 ID | 鉴权系统 | 新建/变更 token 时 | 用户或服务账号主体 | `research-bot` |
| `cost_center` | 成本中心 | 财务/运营配置 | 新建/变更 token 时 | API 用量归集口径 | `research` |
| `expires_at` | 过期时间 | 鉴权系统 | 新建/变更时 | 空表示不过期 | `2026-12-31 23:59:59` |

### 16.5 `api_request_audit`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `api_name` | API 名称 | REST 服务 | 每次请求 | path 对应接口名 | `price` |
| `request_summary` | 请求摘要 | REST 服务 | 每次请求 | JSON，记录 path/query，不写 token 明文 | `{"path": "/price"}` |
| `response_format` | 返回格式 | REST 服务 | 每次请求 | json/csv/arrow | `json` |
| `status` | 请求状态 | REST 服务 | 每次请求 | success/failed/partial_success | `success` |
| `row_count` | 返回行数 | REST 服务 | 每次请求 | `data` 数量或矩阵行数 | `2` |
| `duration_ms` | 耗时毫秒 | REST 服务 | 每次请求 | finished_at - started_at | `12` |
| `client_ip` | 客户端 IP | REST 服务 | 每次请求 | 审计和限流辅助 | `127.0.0.1` |
| `tenant_id/project_id/principal_id` | 租户上下文 | REST 服务 | 每次请求 | 从 DB token 派生，旧环境 token 可为空 | `demo/quant-research/research-bot` |
| `cost_units` | 成本单位 | REST 服务/用量 rollup | 每次请求 | 默认 `1 + row_count / 1000 * 0.1`，可按价格表调整 | `1.0002` |

## 17. Zeta 运维看板、SLA 和告警

### 17.1 `sla_policy`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `policy_code` | SLA 策略编码 | 运维配置 | 新增/变更策略时 | 全局唯一，建议包含数据集和目标 | `daily_bar_conflict_sla` |
| `dataset_id` | 数据集 ID | 运维配置 | 新增/变更策略时 | 可为空，空表示全局策略 | `daily_bar` |
| `job_id` | Pipeline 任务 ID | 运维配置 | 新增/变更策略时 | 可为空，空表示不绑定具体任务 | `daily_market_csv_all` |
| `source_id` | 数据源 ID | 运维配置 | 新增/变更策略时 | 可为空，空表示不绑定具体来源 | `csv` |
| `target_finish_time` | 目标完成时间 | 运维配置 | 新增/变更策略时 | 每个交易日应完成的本地时间 | `17:00:00` |
| `min_completeness` | 最低完整率 | 运维配置 | 新增/变更策略时 | 低于阈值产生告警 | `0.99900000` |
| `max_conflict_rate` | 最高冲突率 | 运维配置 | 新增/变更策略时 | 多源字段冲突率高于阈值告警 | `0.00100000` |
| `max_api_error_rate` | 最高 API 错误率 | 运维配置 | 新增/变更策略时 | 失败请求数 / 总请求数 | `0.01000000` |
| `max_duration_ms` | 最大运行耗时 | 运维配置 | 新增/变更策略时 | pipeline 运行耗时上限 | `600000` |
| `alert_severity` | 告警级别 | 运维配置 | 新增/变更策略时 | low/medium/high/critical | `high` |

### 17.2 `alert_event`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `alert_key` | 告警幂等键 | SLA 检查 | 每次检查 | 同一 policy/date/metric 保持稳定，避免重复告警 | `daily_bar_conflict_sla:conflict_rate...` |
| `policy_id` | SLA 策略 ID | SLA 检查 | 每次检查 | 对应触发策略，可为空 | `1` |
| `trade_date` | 告警交易日 | SLA 检查 | 每次检查 | 触发告警的数据日期 | `2024-01-04` |
| `alert_type` | 告警类型 | SLA 检查 | 每次检查 | missing_run/pipeline_status/conflict_rate 等 | `conflict_rate_above_sla` |
| `severity` | 告警级别 | SLA 检查 | 每次检查 | 继承 policy 或规则默认 | `high` |
| `status` | 处理状态 | 运维流程 | 人工或自动处理时 | open/acknowledged/resolved/ignored | `open` |
| `metric_name` | 指标名称 | SLA 检查 | 每次检查 | 触发告警的指标 | `conflict_rate` |
| `metric_value` | 指标值 | SLA 检查 | 每次检查 | 当前观测值 | `0.16666667` |
| `threshold_value` | 阈值 | SLA 检查 | 每次检查 | 策略阈值 | `0.00100000` |
| `message` | 告警消息 | SLA 检查 | 每次检查 | 可读说明 | `Multi-source conflict rate above SLA` |

### 17.3 `ops_dashboard_snapshot`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `snapshot_code` | 快照编码 | 看板脚本 | 每次写快照 | 全局唯一，包含窗口和筛选条件 | `ops-2024-01-04-...` |
| `window_start` | 窗口开始日期 | 看板脚本 | 每次写快照 | 汇总数据起始日期 | `2024-01-04` |
| `window_end` | 窗口结束日期 | 看板脚本 | 每次写快照 | 汇总数据结束日期 | `2024-01-04` |
| `job_code` | 任务编码 | 看板脚本 | 每次写快照 | 可为空，空表示全任务 | `daily_market_csv_all` |
| `dataset_code` | 数据集编码 | 看板脚本 | 每次写快照 | 可为空，空表示全数据集 | `daily_bar` |
| `pipeline_summary` | Pipeline 摘要 | 看板脚本 | 每次写快照 | status、missing、repair、watermark 汇总 | `{...}` |
| `quality_summary` | 质量摘要 | 看板脚本 | 每次写快照 | 质量检查、多源冲突、覆盖率汇总 | `{...}` |
| `sla_summary` | SLA 摘要 | 看板脚本 | 每次写快照 | 告警数量、类型和级别汇总 | `{...}` |
| `api_summary` | API 摘要 | 看板脚本 | 每次写快照 | 请求量、失败率、慢接口汇总 | `{...}` |

## 18. Eta 供应商接入、压测和评分

Eta 阶段用于把备源从固定样例推进到可接商业 vendor 的生产 adapter，并沉淀供应商可用性、质量和授权风险评价。

### 18.1 `vendor_integration_profile`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `source_id` | 数据源 ID | 供应商配置 | 新增/变更供应商时 | 对应 `qmeta.source_system`，同一供应商保持稳定 | `vendor_http` |
| `provider_name` | Provider 名称 | 采集配置 | 新增/变更供应商时 | 代码中可创建的 provider 名称 | `vendor_http` |
| `auth_mode` | 鉴权模式 | 供应商配置 | 新增/变更供应商时 | none/bearer/header/query/basic | `bearer` |
| `endpoint_base` | API 根地址 | 供应商配置 | 新增/变更供应商时 | 不记录 token 明文 | `https://vendor.example/api` |
| `enabled_datasets` | 可用数据集 | 供应商合同/配置 | 新增/变更供应商时 | 已授权或已接入的数据集清单 | `{daily_bar,adjustment_factor}` |
| `rate_limit_per_min` | 每分钟限频 | 供应商合同/配置 | 新增/变更供应商时 | adapter 按该值节流请求 | `120` |
| `retry_limit` | 重试次数 | 采集配置 | 新增/变更供应商时 | 单次请求失败后的最大重试次数 | `2` |
| `timeout_ms` | 请求超时 | 采集配置 | 新增/变更供应商时 | 单请求超时毫秒 | `30000` |
| `license_scope` | 授权范围 | 商务/法务 | 合同变更时 | 记录使用、展示、回测、再分发限制 | `commercial contract required` |
| `redistribution_allowed` | 是否允许再分发 | 商务/法务 | 合同变更时 | NULL 表示待确认 | `false` |
| `commercial_contract_ref` | 合同引用 | 商务/法务 | 合同变更时 | 只存内部引用，不存敏感合同正文 | `contract-2026-001` |
| `status` | 接入状态 | 数据平台 | 变更时 | testing/active/paused/retired | `testing` |

### 18.2 `provider_error_event`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `provider_name` | Provider 名称 | Adapter | 请求失败时 | 出错的 provider | `vendor_http` |
| `trade_date` | 数据日期 | Adapter/Benchmark | 请求失败时 | 失败对应交易日，可为空 | `2024-01-04` |
| `symbol` | 证券代码 | Adapter/Benchmark | 请求失败时 | 单票失败时记录，可为空 | `600519.SH` |
| `error_stage` | 出错阶段 | Adapter/Benchmark | 请求失败时 | auth/rate_limit/request/parse/normalize/load/compare/benchmark | `request` |
| `error_type` | 错误类型 | Adapter | 请求失败时 | auth/rate_limit/timeout/network/server/client/schema/empty/unknown | `rate_limit` |
| `retryable` | 是否可重试 | Adapter | 请求失败时 | 用于后续自动补偿策略 | `true` |
| `attempt` | 第几次尝试 | Adapter | 请求失败时 | 从 0 开始，含重试 | `1` |
| `error_message` | 错误摘要 | Adapter | 请求失败时 | 截断保存，不记录密钥 | `HTTP Error 429` |

### 18.3 `provider_benchmark_run`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `benchmark_code` | 压测编码 | Benchmark 脚本 | 每次压测 | 包含主源、备源和日期窗口的唯一编码 | `bench-csv-vendor_http-...` |
| `dataset_id` | 数据集 ID | Benchmark 脚本 | 每次压测 | 当前压测的数据集 | `daily_bar` |
| `primary_source_id` | 主源 ID | Benchmark 脚本 | 每次压测 | 对账主源 | `csv` |
| `secondary_source_id` | 备源 ID | Benchmark 脚本 | 每次压测 | 被评估供应商 | `vendor_http` |
| `symbol_count` | 证券数 | Benchmark 脚本 | 每次压测 | 去重后的请求证券数 | `2` |
| `date_count` | 日期数 | Benchmark 脚本 | 每次压测 | 压测窗口自然日数量 | `1` |
| `matched_count` | 匹配行数 | 多源对账 | 每次压测 | 主备都有记录的证券日数量 | `2` |
| `conflict_count` | 冲突字段数 | 多源对账 | 每次压测 | 字段级冲突数量 | `2` |
| `coverage_rate` | 覆盖率 | Benchmark 脚本 | 每次压测 | matched / primary rows | `1.00000000` |
| `conflict_rate` | 冲突率 | Benchmark 脚本 | 每次压测 | conflict fields / comparable fields | `0.16666667` |
| `failure_rate` | 失败率 | Benchmark 脚本 | 每次压测 | failed days / date_count | `0.00000000` |
| `p50_latency_ms` | P50 延迟 | Benchmark 脚本 | 每次压测 | 日级请求和对账耗时 | `0.65` |
| `p95_latency_ms` | P95 延迟 | Benchmark 脚本 | 每次压测 | 小样本时等于对应日耗时 | `0.65` |
| `rows_per_second` | 吞吐 | Benchmark 脚本 | 每次压测 | 主备总行数 / 总耗时秒 | `3000` |
| `status` | 压测状态 | Benchmark 脚本 | 每次压测 | success/warning/failed | `warning` |

### 18.4 `vendor_quality_score_daily`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `score_date` | 评分日期 | Benchmark 脚本 | 每次压测 | 默认使用压测结束日期 | `2024-01-04` |
| `coverage_score` | 覆盖得分 | 评分模型 | 每次压测 | coverage_rate x 100，权重 35% | `100` |
| `conflict_score` | 一致性得分 | 评分模型 | 每次压测 | (1 - conflict_rate) x 100，权重 25% | `83.3333` |
| `stability_score` | 稳定性得分 | 评分模型 | 每次压测 | (1 - failure_rate) x 100，权重 20% | `100` |
| `latency_score` | 延迟得分 | 评分模型 | 每次压测 | 相对目标延迟折算，权重 10% | `99.98` |
| `cost_score` | 成本得分 | 人工/配置 | 每次压测 | 成本越优得分越高，权重 5% | `80` |
| `license_risk_score` | 授权风险得分 | 人工/配置 | 每次压测 | 授权越清晰得分越高，权重 5% | `70` |
| `total_score` | 综合得分 | 评分模型 | 每次压测 | 加权总分，0-100 | `93.8320` |
| `rating` | 等级 | 评分模型 | 每次压测 | A/B/C/D | `A` |

## 19. Theta 真实供应商生产化

Theta 阶段用于把供应商从单日样例评分推进到全市场分片压测、SLA 告警和上线角色决策。

### 19.1 `vendor_field_mapping`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `source_id` | 数据源 ID | 供应商接入配置 | 新增/变更映射时 | 对应被映射供应商 | `vendor_http` |
| `dataset_id` | 数据集 ID | 供应商接入配置 | 新增/变更映射时 | 当前支持 `daily_bar` 优先 | `daily_bar` |
| `external_field` | 外部字段 | Vendor API 文档 | 接口变更时 | 供应商返回字段名 | `vol` |
| `internal_field` | 内部字段 | 平台口径 | 接口变更时 | 标准模型字段名 | `volume` |
| `transform_rule` | 转换规则 | 平台口径 | 接口变更时 | identity/date_yyyymmdd/volume_hand_to_share/pct_to_ratio 等 | `volume_hand_to_share` |
| `unit_from` | 外部单位 | Vendor API 文档 | 接口变更时 | 原始单位 | `hand` |
| `unit_to` | 内部单位 | 平台口径 | 接口变更时 | 标准单位 | `share` |
| `is_required` | 是否必需 | 平台口径 | 接口变更时 | 缺失时应进入 schema/normalize 错误 | `true` |
| `priority` | 映射优先级 | 平台口径 | 接口变更时 | 同一内部字段多个外部别名时按 priority 排序 | `10` |
| `status` | 映射状态 | 数据平台 | 变更时 | active/testing/paused/retired | `active` |

### 19.2 `provider_benchmark_suite_run`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `suite_code` | 分片压测编码 | Benchmark 脚本 | 每次 suite | 包含主源、备源、窗口和时间戳 | `suite-csv-vendor_http-...` |
| `target_trade_days` | 目标交易日数 | Benchmark 参数 | 每次 suite | 5/20/60 日压测窗口可用该字段标记 | `20` |
| `shard_size` | 分片大小 | Benchmark 参数 | 每次 suite | 每片证券数，控制单次请求和失败隔离 | `500` |
| `max_symbols` | 最大证券数 | Benchmark 参数 | 每次 suite | 灰度限量，全市场可为空 | `1000` |
| `symbol_count` | 实际证券数 | Benchmark 脚本 | 每次 suite | 去重并限量后的证券数量 | `5531` |
| `shard_count` | 分片数 | Benchmark 脚本 | 每次 suite | 证券分片数量 | `12` |
| `benchmark_count` | 子 benchmark 数 | Benchmark 脚本 | 每次 suite | 日期数 x 分片数 | `240` |
| `coverage_rate` | 聚合覆盖率 | Benchmark 脚本 | 每次 suite | matched rows / primary rows | `0.99980000` |
| `conflict_rate` | 聚合冲突率 | Benchmark 脚本 | 每次 suite | conflict fields / comparable fields | `0.00050000` |
| `failure_rate` | 聚合失败率 | Benchmark 脚本 | 每次 suite | failed shard runs / benchmark_count | `0.00400000` |
| `p95_latency_ms` | P95 延迟 | Benchmark 脚本 | 每次 suite | 子 benchmark P95 延迟的 suite P95 | `1800` |
| `rows_per_second` | 吞吐 | Benchmark 脚本 | 每次 suite | 主备总行数 / 总耗时秒 | `12000` |
| `status` | 压测状态 | Benchmark 脚本 | 每次 suite | success/warning/failed | `warning` |

### 19.3 `sla_policy` provider 阈值扩展

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `min_vendor_score` | 最低供应商评分 | 运维配置 | SLA 变更时 | 低于阈值触发 `vendor_score_below_sla` | `90` |
| `max_vendor_conflict_rate` | 最高供应商冲突率 | 运维配置 | SLA 变更时 | 高于阈值触发 `vendor_conflict_rate_above_sla` | `0.00500000` |
| `max_vendor_failure_rate` | 最高供应商失败率 | 运维配置 | SLA 变更时 | 高于阈值触发 `vendor_failure_rate_above_sla` | `0.01000000` |
| `max_vendor_latency_ms` | 最大供应商延迟 | 运维配置 | SLA 变更时 | 高于阈值触发 `vendor_latency_above_sla` | `5000` |
| `max_provider_error_count` | 最大 provider 错误数 | 运维配置 | SLA 变更时 | 高于阈值触发 `provider_error_count_above_sla` | `0` |

### 19.4 `vendor_decision_report`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `report_code` | 决策报告编码 | 决策脚本 | 每次生成 | source/dataset/date/time 组合 | `decision-vendor_http-daily_bar-...` |
| `score_date` | 评分日期 | 供应商评分 | 每次生成 | 使用最新 score_date | `2024-01-04` |
| `total_score` | 综合得分 | 供应商评分 | 每次生成 | 直接取最新 `vendor_quality_score_daily` | `93.8314` |
| `rating` | 评分等级 | 供应商评分 | 每次生成 | A/B/C/D | `A` |
| `recommendation` | 上线建议 | 决策脚本 | 每次生成 | approve_primary/approve_backup/watch/reject | `approve_backup` |
| `recommended_role` | 建议角色 | 决策脚本 | 每次生成 | primary/backup/research_only/none | `backup` |
| `rationale` | 决策理由 | 决策脚本 | 每次生成 | 可读说明 | `Vendor is usable as a backup source...` |
| `blocking_issues` | 阻塞项 | 决策脚本 | 每次生成 | 未达到 primary 阈值的具体指标 | `{conflict_rate...}` |
| `next_actions` | 下一步动作 | 决策脚本 | 每次生成 | 复测、合同、映射或替换建议 | `{rerun 20/60 day benchmark}` |

## 20. Iota 生产通知、租户权限和用量计量

Iota 阶段用于把量化数据平台推进到可按客户、项目、主体运营的闭环，并把告警、API 用量和供应商压测 schedule 落到可审计表。

### 20.1 `tenant` / `project` / `principal`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `tenant_code` | 租户编码 | 运营/客户管理 | 新租户或变更时 | 全局唯一，建议使用短编码 | `demo` |
| `project_code` | 项目编码 | 运营/客户管理 | 新项目或变更时 | 租户内唯一，用于策略/研究团队隔离 | `quant-research` |
| `principal_code` | 主体编码 | IAM/服务账号 | 新用户或服务账号时 | 租户内唯一，可表示用户、服务账号或系统任务 | `research-bot` |
| `principal_type` | 主体类型 | IAM | 新建主体时 | user/service_account/system | `service_account` |
| `status` | 状态 | 运营配置 | 变更时 | active/paused/disabled | `active` |

### 20.2 `dataset_access_policy`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `dataset_id` | 数据集 ID | 权限配置 | 授权变更时 | 对应 `dataset_catalog` | `daily_bar` |
| `tenant_id/project_id/principal_id` | 授权对象 | 权限配置 | 授权变更时 | 至少一个非空，优先级 principal > project > tenant | `quant-research` |
| `access_level` | 权限级别 | 权限配置 | 授权变更时 | read/write/admin | `read` |
| `field_allowlist` | 字段白名单 | 权限配置 | 授权变更时 | 空数组表示不限制字段 | `{close,volume}` |
| `field_denylist` | 字段黑名单 | 权限配置 | 授权变更时 | 命中时拒绝请求字段 | `{amount}` |
| `expires_at` | 过期时间 | 权限配置 | 授权变更时 | 空表示长期有效 | `NULL` |

### 20.3 `api_usage_daily`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `usage_date` | 用量日期 | API 审计 rollup | 日级/按需 | 以 `api_request_audit.started_at::date` 聚合 | `2026-07-24` |
| `api_name` | API 名称 | API 审计 rollup | 日级/按需 | path 对应接口名 | `price` |
| `request_count` | 请求数 | API 审计 rollup | 日级/按需 | 同租户/项目/主体/token/API 聚合 | `1280` |
| `failed_count` | 失败数 | API 审计 rollup | 日级/按需 | status=failed 数量 | `3` |
| `row_count` | 返回行数 | API 审计 rollup | 日级/按需 | 聚合返回 rows | `2000000` |
| `cost_units` | 成本单位 | API 审计 rollup | 日级/按需 | 用于账单或成本分摊，可后续接价格表 | `1480.5` |

### 20.4 `notification_channel` / `alert_notification_delivery`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `channel_code` | 通道编码 | 运维配置 | 新增/变更通道时 | 全局唯一 | `stdout-high` |
| `channel_type` | 通道类型 | 运维配置 | 新增/变更通道时 | stdout/webhook/email/feishu | `webhook` |
| `endpoint` | 投递地址 | 运维配置 | 新增/变更通道时 | webhook/飞书地址或邮件目标 | `https://ops.example/alert` |
| `min_severity` | 最低告警级别 | 运维配置 | 新增/变更通道时 | low/medium/high/critical | `high` |
| `delivery_key` | 投递幂等键 | 通知脚本 | 每次投递 | alert/channel/last_seen_at/mode 组合，dry-run 和真实投递隔离 | `2:1:...:send` |
| `attempt_count` | 尝试次数 | 通知脚本 | 每次投递 | 重复投递累加 | `2` |
| `status` | 投递状态 | 通知脚本 | 每次投递 | pending/sent/failed/skipped | `sent` |

### 20.5 `vendor_benchmark_schedule`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `schedule_code` | 调度编码 | 运营配置 | 新增/变更 schedule 时 | 全局唯一 | `daily_bar_vendor_fixture_schedule` |
| `dataset_id` | 数据集 ID | 运营配置 | 新增/变更 schedule 时 | 当前压测数据集 | `daily_bar` |
| `primary_source_id` | 主源 ID | 运营配置 | 新增/变更 schedule 时 | 对账主源 | `csv` |
| `secondary_source_id` | 备源 ID | 运营配置 | 新增/变更 schedule 时 | 被评估供应商 | `vendor_http` |
| `target_trade_days` | 目标交易日数 | 运营配置 | 新增/变更 schedule 时 | 5/20/60 日窗口可用 | `20` |
| `cadence` | 调度频率 | 运营配置 | 新增/变更 schedule 时 | manual/daily/weekly/monthly | `manual` |
| `last_suite_id` | 最近 suite | 压测调度 | 每次运行 | 对应 `provider_benchmark_suite_run` | `2` |
| `next_run_at` | 下次运行时间 | 压测调度 | 每次运行 | manual 为空，其他 cadence 自动推进 | `2026-07-25T16:00:00+08:00` |

## 21. Kappa 只读运营视图口径

Kappa 不新增底层事实表，而是把 Iota、Zeta 和 Theta 的运营数据整理成稳定只读 API。输出字段应避免泄露密钥、合同正文或 token 完整哈希。

### 21.1 `/admin/overview`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `active_tenant_count` | 活跃租户数 | `tenant` | 实时查询 | status=active | `1` |
| `active_project_count` | 活跃项目数 | `project` | 实时查询 | status=active | `1` |
| `active_token_count` | 活跃 token 数 | `api_token` | 实时查询 | is_active=true | `1` |
| `open_alert_count` | Open 告警数 | `alert_event` | 实时查询 | status=open | `3` |
| `sent_notification_count` | 已发送通知数 | `alert_notification_delivery` | 实时查询 | status=sent | `2` |
| `usage_7d_request_count` | 近 7 日请求数 | `api_usage_daily` | rollup 后查询 | 当前日期向前 7 日窗口，含无项目 fallback token 请求 | `117` |
| `usage_7d_cost_units` | 近 7 日成本单位 | `api_usage_daily` | rollup 后查询 | 同上，聚合 cost_units | `117.030200` |
| `active_worker_schedule_count` | 活跃 worker schedule 数 | `worker_schedule` | 实时查询 | status=active | `3` |
| `live_scheduler_count` | 运行中 scheduler 数 | `worker_heartbeat` | 实时查询 | status=running 且 2 分钟内有心跳 | `0` |
| `expired_worker_lock_count` | 过期锁数 | `worker_lock` | 实时查询 | expires_at <= now() | `0` |
| `latest_scheduler_tick_status` | 最新调度 tick 状态 | `worker_schedule_tick` | 实时查询 | 按 started_at 倒序取最新 | `success` |
| `latest_deployment_health_status` | 最新部署健康状态 | `deployment_health_snapshot` | 健康检查后 | 按 checked_at 倒序取最新 | `success` |
| `latest_deployment_release_status` | 最新发布状态 | `deployment_release` | 部署/健康检查后 | 按 created_at 倒序取最新 | `healthy` |
| `deployment_24h_failed_count` | 24 小时失败健康检查数 | `deployment_health_snapshot` | 健康检查后 | checked_at 近 24 小时且 status=failed | `0` |
| `active_product_count` | 活跃数据产品数 | `data_product` | 实时查询 | status=active | `1` |
| `active_subscription_count` | 活跃订阅数 | `product_subscription` | 实时查询 | status=active | `1` |
| `active_budget_policy_count` | 活跃预算策略数 | `budget_policy` | 实时查询 | status=active | `1` |
| `budget_open_alert_count` | Open 预算告警数 | `budget_alert` | 预算评估后 | status=open | `1` |
| `budget_blocked_count` | 本月 blocked 预算数 | `budget_usage_snapshot` | 预算评估后 | 当前月且 status=blocked | `0` |
| `budget_month_usage_amount` | 本月预算使用金额 | `budget_usage_snapshot` | 预算评估后 | 当前月 usage_amount 求和 | `0.16002800` |
| `budget_month_limit_amount` | 本月预算额度 | `budget_policy` | 配置变更时 | active monthly budget_amount 求和 | `0.15000000` |

### 21.2 `/admin/tokens`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `token_hash_tail` | Token 哈希尾号 | `api_token` | 实时查询 | 只返回 SHA-256 后 8 位，禁止返回完整哈希或明文 | `fd3e8ef6` |
| `scopes` | 权限范围 | `api_token` | token 变更时 | read/admin 等 scope | `{read,admin}` |
| `quota_per_min` | 分钟配额 | `api_token` | token 变更时 | 单 token 限频配置 | `120` |
| `tenant_code/project_code/principal_code` | 归属上下文 | Iota 权限表 | token 变更时 | 用于审计、ACL 和用量归集 | `demo/quant-research/research-bot` |
| `cost_center` | 成本中心 | `api_token` | token 变更时 | 计费用量归属 | `research` |

### 21.3 `/usage/daily`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `request_count` | 请求数 | `api_usage_daily` | rollup 后查询 | 按日期、项目、主体、token、API 聚合 | `31` |
| `failed_count` | 失败数 | `api_usage_daily` | rollup 后查询 | status=failed 的请求数 | `0` |
| `row_count` | 返回行数 | `api_usage_daily` | rollup 后查询 | 聚合 API 返回 rows | `76` |
| `duration_ms` | 总耗时 | `api_usage_daily` | rollup 后查询 | 聚合请求耗时 | `1504` |
| `cost_units` | 成本单位 | `api_usage_daily` | rollup 后查询 | 当前默认成本公式结果 | `31.007600` |

## 22. Lambda 后台自动化 Worker

Lambda 阶段用于记录后台自动化任务的执行状态，避免用量 rollup、告警投递和供应商压测调度停留在人工脚本层。

### 22.1 `worker_run`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `run_code` | Worker 运行编码 | Worker | 每次运行 | 全局唯一，含运行时间戳 | `lambda-worker-20260724085914939938` |
| `trigger_mode` | 触发方式 | Worker/调度器 | 每次运行 | manual/scheduled/once/smoke | `once` |
| `status` | 总状态 | Worker | 每次运行完成 | running/success/warning/failed/skipped | `success` |
| `task_filter` | 本次任务清单 | Worker 参数 | 每次运行 | 实际执行 task 名称数组 | `{usage_rollup}` |
| `dry_run` | 是否演练 | Worker 参数 | 每次运行 | true 表示只预览或不执行外部副作用 | `false` |
| `processed_count` | 总处理数 | Worker 汇总 | 每次运行完成 | 各 task processed_count 求和 | `19` |
| `success_count` | 成功数 | Worker 汇总 | 每次运行完成 | 各 task success_count 求和 | `19` |
| `warning_count` | Warning 数 | Worker 汇总 | 每次运行完成 | 如 vendor suite 为 warning | `1` |
| `failed_count` | 失败数 | Worker 汇总 | 每次运行完成 | task 失败或处理项失败数量 | `0` |

### 22.2 `worker_task_run`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `worker_run_id` | 所属 worker run | Worker | 每个 task | 对应 `worker_run` | `3` |
| `task_name` | 任务名 | Worker | 每个 task | usage_rollup/alert_dispatch/vendor_benchmark_schedule | `usage_rollup` |
| `status` | task 状态 | Worker | 每个 task 完成 | running/success/warning/failed/skipped | `success` |
| `duration_ms` | task 耗时 | Worker | 每个 task 完成 | finished_at - started_at | `96` |
| `details` | task 明细 | Worker | 每个 task 完成 | JSON，记录 preview rows、deliveries 或 schedule results | `{...}` |
| `error_message` | 错误摘要 | Worker | task 失败时 | 不记录密钥和完整响应正文 | `vendor benchmark schedule not found` |

## 23. Mu 后台调度器

Mu 阶段把 Lambda worker 从人工触发升级为可长期运行的调度器：调度配置由 `worker_schedule` 管，防重复由 `worker_lock` 管，进程存活由 `worker_heartbeat` 管，每次扫描执行由 `worker_schedule_tick` 记录。

### 23.1 `worker_schedule`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `schedule_code` | 调度编码 | Mu migration/运维配置 | 新增/变更调度时 | 全局唯一 | `mu_usage_rollup_5m` |
| `task_name` | 调度任务 | Mu 配置 | 新增/变更调度时 | usage_rollup/alert_dispatch/vendor_benchmark_schedule | `usage_rollup` |
| `frequency_seconds` | 调度间隔秒数 | Mu 配置 | 新增/变更调度时 | 成功或 warning 后按该间隔推进 next_run_at | `300` |
| `lock_timeout_seconds` | 锁超时秒数 | Mu 配置 | 新增/变更调度时 | scheduler 崩溃后允许其他实例接管 | `900` |
| `task_args` | task 参数 | Mu 配置 | 新增/变更调度时 | 透传给 Lambda worker 的安全参数 | `{"cost_per_request":1.0}` |
| `last_status` | 最近调度状态 | Mu scheduler | 每次 tick 完成 | 对应最近 worker 结果 | `success` |
| `next_run_at` | 下次到期时间 | Mu scheduler | 每次 tick 完成 | started_at + frequency_seconds | `2026-07-24T17:34:08+08:00` |
| `run_count` | 累计执行次数 | Mu scheduler | 每次 tick 完成 | 不含未抢到锁的 skipped_locked | `2` |

### 23.2 `worker_lock`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `lock_name` | 锁名称 | Mu scheduler | 抢锁时 | `worker_schedule:{schedule_code}` | `worker_schedule:mu_usage_rollup_5m` |
| `owner_id` | 锁持有者 | Mu scheduler | 抢锁/续约时 | scheduler_id | `mu-smoke` |
| `heartbeat_at` | 锁心跳时间 | Mu scheduler | 抢锁/续约时 | 判断活跃锁 | `2026-07-24T17:30:10+08:00` |
| `expires_at` | 锁过期时间 | Mu scheduler | 抢锁/续约时 | 过期后其他 scheduler 可接管 | `2026-07-24T17:45:10+08:00` |

### 23.3 `worker_heartbeat`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `scheduler_id` | 调度器实例 ID | Mu scheduler | 进程启动时 | host/pid/time 或显式传入 | `mu-smoke` |
| `status` | 调度器状态 | Mu scheduler | 扫描/停止时 | running/stopping/stopped/failed | `stopped` |
| `last_seen_at` | 最近心跳 | Mu scheduler | 每次扫描或 task 开始时 | Kappa 判断 live/stale | `2026-07-24T17:30:10+08:00` |
| `current_schedule_code` | 当前调度项 | Mu scheduler | task 开始/结束时 | 正在处理的 schedule | `mu_alert_dispatch_1m` |
| `tick_count` | 扫描次数 | Mu scheduler | 每次扫描 | 本 scheduler 进程内累计 | `1` |
| `run_count` | tick 结果数 | Mu scheduler | 每次扫描 | 本 scheduler 进程内累计 | `1` |

### 23.4 `worker_schedule_tick`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `tick_code` | tick 编码 | Mu scheduler | 每次尝试执行 schedule | 全局唯一 | `mu-tick-20260724093010158654` |
| `scheduler_id` | 调度器实例 | Mu scheduler | 每次 tick | 对应 heartbeat | `mu-dbc7888fe2cf-14-...` |
| `schedule_code` | 调度编码 | Mu scheduler | 每次 tick | 对应 `worker_schedule` | `mu_alert_dispatch_1m` |
| `status` | tick 状态 | Mu scheduler | tick 完成时 | success/warning/failed/skipped/skipped_locked | `success` |
| `worker_run_id` | 触发的 worker run | Lambda worker | tick 完成时 | 对应 `worker_run` | `6` |
| `lock_acquired` | 是否抢到锁 | Mu scheduler | tick 完成时 | false 表示被其他 scheduler 持有 | `true` |

## 24. Nu 部署发布和健康巡检

Nu 阶段记录本地标准部署的 release、健康快照、检查明细和事件，用于回答“系统现在是否能部署、能巡检、能回滚”。

### 24.1 `deployment_release`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `release_code` | 发布编码 | 部署脚本/健康检查 | 每次部署 | 全局唯一 | `nu-local-smoke-20260726` |
| `environment` | 环境 | 部署参数 | 每次部署 | local/staging/prod 等 | `local` |
| `version_label` | 版本标签 | 部署参数 | 每次部署 | git tag、镜像 tag 或本地 dev | `dev` |
| `git_ref` | Git 引用 | 部署参数 | 每次部署 | commit/branch | `local` |
| `status` | 发布状态 | 健康检查 | 部署/巡检后 | planned/deploying/healthy/degraded/failed/rolled_back | `healthy` |
| `health_snapshot_id` | 最近健康快照 | Nu health | 每次写入健康快照 | 对应 `deployment_health_snapshot` | `1` |

### 24.2 `deployment_health_snapshot`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `snapshot_code` | 健康快照编码 | Nu health | 每次巡检 | 全局唯一 | `nu-health-20260726094819059961` |
| `status` | 总健康状态 | Nu health | 每次巡检 | success/warning/failed | `success` |
| `check_count` | 检查项数量 | Nu health | 每次巡检 | 本次 check 总数 | `6` |
| `success_count` | 成功检查数 | Nu health | 每次巡检 | status=success | `6` |
| `warning_count` | warning/skip 检查数 | Nu health | 每次巡检 | status=warning 或 skipped | `0` |
| `failed_count` | 失败检查数 | Nu health | 每次巡检 | status=failed | `0` |

### 24.3 `deployment_health_check`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `check_name` | 检查名 | Nu health | 每次巡检 | postgres/migration/clickhouse/api/scheduler/kappa | `api_health` |
| `component` | 组件 | Nu health | 每次巡检 | postgres/clickhouse/api/scheduler/kappa/docker/migration/release | `api` |
| `status` | 检查状态 | Nu health | 每次巡检 | success/warning/failed/skipped | `success` |
| `duration_ms` | 检查耗时 | Nu health | 每次巡检 | 单项检查耗时 | `21` |
| `details` | 检查明细 | Nu health | 每次巡检 | JSON，记录连接、计数或 overview | `{"row_count":1}` |
| `error_message` | 错误摘要 | Nu health | 每次巡检失败 | 不记录密钥 | `connection refused` |

### 24.4 `deployment_event`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `event_code` | 事件编码 | 部署/健康脚本 | 每次事件 | 全局唯一 | `nu-event-...` |
| `event_type` | 事件类型 | 部署/健康脚本 | 每次事件 | deploy_start/deploy_finish/health_check/rollback_start/rollback_finish/manual_note | `health_check` |
| `status` | 事件状态 | 部署/健康脚本 | 每次事件 | success/warning/failed | `success` |
| `message` | 事件说明 | 部署/健康脚本 | 每次事件 | 简短可读摘要 | `Nu health check success` |

## 25. Xi 数据产品和预算治理

Xi 阶段记录可售数据产品、价格计划、项目订阅、预算策略、预算快照和预算告警，用于回答“哪些数据能卖、怎么计费、哪个项目快超预算”。

### 25.1 `data_product`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `product_code` | 产品编码 | 商业配置 | 新增/变更产品时 | 全局唯一 | `a_share_daily_core` |
| `product_name` | 产品名称 | 商业配置 | 新增/变更产品时 | 面向客户/销售可读 | `A Share Daily Quant Core` |
| `product_type` | 产品类型 | 商业配置 | 新增/变更产品时 | dataset_bundle/api_bundle/export/package | `dataset_bundle` |
| `billing_unit` | 默认计价单位 | 商业配置 | 新增/变更产品时 | request/row/cost_unit/export/month | `cost_unit` |
| `status` | 产品状态 | 商业配置 | 新增/变更产品时 | active/testing/paused/retired | `active` |

### 25.2 `data_product_dataset` / `data_product_api`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `product_id` | 产品 ID | 商业配置 | 产品绑定变更时 | 对应 `data_product` | `a_share_daily_core` |
| `dataset_id` | 数据集 ID | 商业配置 | 产品绑定变更时 | 对应 `dataset_catalog` | `daily_bar` |
| `api_name` | API 名称 | 商业配置 | 产品绑定变更时 | 与 REST 审计 `api_name` 对齐 | `price` |
| `is_billable` | 是否计费 | 商业配置 | 产品绑定变更时 | false 表示只授权不计费 | `true` |

### 25.3 `pricing_plan` / `pricing_rule`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `plan_code` | 价格计划编码 | 商业配置 | 新增/变更计划时 | 全局唯一 | `quant_starter_monthly` |
| `billing_cycle` | 计费周期 | 商业配置 | 新增/变更计划时 | daily/monthly/annual/prepaid/usage | `monthly` |
| `currency` | 币种 | 商业配置 | 新增/变更计划时 | ISO 或内部币种编码 | `CNY` |
| `base_fee` | 基础费用 | 商业配置 | 新增/变更计划时 | 周期固定费用 | `0` |
| `metric_name` | 计价指标 | 商业配置 | 新增/变更规则时 | request/row/cost_unit/export/monthly_fee | `cost_unit` |
| `unit_price` | 单价 | 商业配置 | 新增/变更规则时 | 当前规则单位价格 | `0.0100000000` |

### 25.4 `product_subscription`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `subscription_code` | 订阅编码 | 商业配置 | 新增/变更订阅时 | 全局唯一 | `demo_quant-research_a_share_daily_core` |
| `tenant_id/project_id` | 订阅对象 | Iota 租户项目 | 新增/变更订阅时 | 可按租户或项目订阅 | `demo/quant-research` |
| `plan_id/product_id` | 计划和产品 | 商业配置 | 新增/变更订阅时 | 对应 plan/product | `quant_starter_monthly/a_share_daily_core` |
| `hard_limit_enabled` | 是否启用硬限制 | 商业配置 | 新增/变更订阅时 | 与预算策略共同控制拦截 | `false` |

### 25.5 `budget_policy`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `budget_code` | 预算编码 | 商业/运营配置 | 新增/变更预算时 | 全局唯一 | `demo_quant-research_monthly_budget` |
| `tenant_id/project_id/principal_id` | 预算对象 | Iota 租户项目 | 新增/变更预算时 | 可按租户/项目/主体绑定 | `demo/quant-research` |
| `cost_center` | 成本中心 | API token/预算配置 | 新增/变更预算时 | 与 token cost_center 对齐 | `research` |
| `period` | 预算周期 | 商业配置 | 新增/变更预算时 | daily/monthly | `monthly` |
| `budget_amount` | 预算金额 | 商业配置 | 新增/变更预算时 | 当前币种金额 | `0.15000000` |
| `soft_threshold_pct` | 软阈值 | 商业配置 | 新增/变更预算时 | 达到后生成 warning | `0.7000` |
| `hard_threshold_pct` | 硬阈值 | 商业配置 | 新增/变更预算时 | 达到后 exceeded/blocked | `1.0000` |

### 25.6 `budget_usage_snapshot`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `snapshot_code` | 预算快照编码 | Xi 评估脚本 | 每次评估 | budget+period 稳定编码 | `xi-budget-demo_quant-research_monthly_budget-20260701-20260731` |
| `period_start/period_end` | 预算周期 | Xi 评估脚本 | 每次评估 | daily/monthly 展开后的自然日期 | `2026-07-01/2026-07-31` |
| `usage_amount` | 已用金额 | `api_usage_daily` + 价格规则 | 每次评估 | 当前产品 API 用量按规则折算 | `0.16002800` |
| `budget_amount` | 预算金额 | `budget_policy` | 每次评估 | 评估时预算额度快照 | `0.15000000` |
| `usage_pct` | 预算使用率 | Xi 评估脚本 | 每次评估 | usage_amount / budget_amount | `1.06685333` |
| `status` | 预算状态 | Xi 评估脚本 | 每次评估 | normal/warning/exceeded/blocked | `exceeded` |

### 25.7 `budget_alert`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `alert_key` | 告警幂等键 | Xi 评估脚本 | 每次评估 | budget+period+alert_type | `xi-budget:...:budget_exceeded` |
| `alert_type` | 告警类型 | Xi 评估脚本 | 每次评估 | budget_threshold_warning/budget_exceeded/budget_blocked/budget_usage_spike | `budget_exceeded` |
| `severity` | 严重级别 | Xi 评估脚本 | 每次评估 | low/medium/high/critical | `high` |
| `status` | 告警状态 | Xi 评估脚本 | 每次评估 | open/acknowledged/resolved/ignored | `open` |
| `usage_pct` | 触发时使用率 | Xi 评估脚本 | 每次评估 | 同预算快照 | `1.06685333` |
| `message` | 告警说明 | Xi 评估脚本 | 每次评估 | 可直接发通知 | `Budget ... is exceeded` |

## 26. Omicron 月度账单和收入回款

Omicron 阶段把 Xi 的订阅和 Iota 的用量转换成可对账账单，用于回答“本月应收多少、已收多少、哪些账单逾期”。

### 26.1 `invoice`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `invoice_code` | 账单编码 | Omicron 生成脚本 | 每账期/订阅 | tenant+project+product+period 稳定编码 | `inv-demo-quant-research-a_share_daily_core-20260701-20260731` |
| `tenant_id/project_id` | 客户和项目 | Iota/Xi 订阅 | 生成账单时 | 对应订阅归属 | `demo/quant-research` |
| `subscription_id` | 订阅 ID | Xi 订阅 | 生成账单时 | 对应 `product_subscription` | `demo_quant-research_a_share_daily_core` |
| `period_start/period_end` | 账期 | Omicron 参数 | 每账期 | 自然月或指定日期窗口 | `2026-07-01/2026-07-31` |
| `invoice_date/due_date` | 开票日/到期日 | Omicron 参数 | 生成账单时 | 默认 invoice_date+15 天到期 | `2026-07-26/2026-08-10` |
| `total_amount` | 应收总额 | 明细汇总 | 生成账单时 | subtotal-discount+tax | `0.16002800` |
| `paid_amount` | 实收金额 | 回款更新 | 回款时 | 已确认收款金额 | `0.00000000` |
| `outstanding_amount` | 未收金额 | 账单状态更新 | 生成/回款时 | total-paid，作废账单为 0 | `0.16002800` |
| `status` | 账单状态 | 生成/回款更新 | 生成/回款/催收时 | draft/issued/partially_paid/paid/overdue/void | `issued` |

### 26.2 `invoice_line`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `line_code` | 明细编码 | Omicron 生成脚本 | 生成账单时 | invoice+api+metric+序号 | `line-inv-demo-...-price-cost_unit-001` |
| `api_name` | API 名称 | `api_usage_daily` | 生成账单时 | 与产品内 billable API 对齐 | `price` |
| `metric_name` | 计价指标 | `pricing_rule` | 生成账单时 | request/row/cost_unit/export/monthly_fee/base_fee/adjustment | `cost_unit` |
| `quantity` | 计费数量 | 用量-免费额度 | 生成账单时 | 已扣除 free_quantity 的数量 | `16.00280000` |
| `unit_price` | 单价 | `pricing_rule` | 生成账单时 | 当前规则单位价格 | `0.0100000000` |
| `amount` | 明细金额 | quantity*unit_price | 生成账单时 | 保留 8 位小数 | `0.16002800` |
| `request_count/row_count/cost_units` | 原始用量 | `api_usage_daily` | 生成账单时 | 用于审计和对账 | `117/0/16.00280000` |

### 26.3 `invoice_event`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `event_code` | 事件编码 | Omicron 脚本 | 每次生成/状态变更 | 全局唯一 | `omicron-generated-inv-demo-...` |
| `event_type` | 事件类型 | Omicron 脚本 | 每次生成/状态变更 | generated/issued/paid/overdue/void/manual_note | `generated` |
| `status` | 事件状态 | Omicron 脚本 | 每次事件 | success/warning/failed | `success` |
| `message` | 事件说明 | Omicron 脚本 | 每次事件 | 简短可读摘要 | `Generated invoice ...` |

## 27. Pi 供应商上线复核

Pi 阶段把 Theta 的分片 suite 压测汇总成上线复核结论，用于回答“真实供应商能不能作为主源、备源或只能研究观察”。

### 27.1 `vendor_readiness_review`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `review_code` | 复核编码 | Pi 复核脚本 | 每次复核 | source+dataset+review_date+windows 稳定编码 | `pi-readiness-vendor_http-daily_bar-20260726-5-20-60d` |
| `dataset_id/source_id` | 数据集和候选源 | Theta/Eta 元数据 | 每次复核 | 候选供应商与数据集 | `daily_bar/vendor_http` |
| `required_windows` | 必要压测窗口 | Pi 参数 | 每次复核 | 默认 5/20/60 交易日 | `{5,20,60}` |
| `suite_count` | 已匹配 suite 数 | `provider_benchmark_suite_run` | 每次复核 | 对应窗口的最新 suite 数 | `3` |
| `status` | 复核状态 | Pi 规则 | 每次复核 | ready/watch/rejected/incomplete | `watch` |
| `recommendation` | 上线建议 | Pi 规则 | 每次复核 | approve_primary/approve_backup/watch/reject | `approve_backup` |
| `recommended_role` | 推荐角色 | Pi 规则 | 每次复核 | primary/backup/research_only/none | `backup` |
| `observed_*` | 观测指标 | 窗口明细汇总 | 每次复核 | min coverage、max conflict/failure/latency 等 | `observed_max_conflict_rate=0.16666667` |
| `runtime_mode` | 运行模式 | vendor profile | 每次复核 | live/fixture/offline/unknown | `fixture` |
| `blocking_issues` | 阻塞原因 | Pi 规则 | 每次复核 | 不能升主源的明确原因 | `5d conflict_rate above threshold` |

### 27.2 `vendor_readiness_window`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `window_days` | 压测窗口 | Pi 参数 | 每次复核 | 5/20/60 等目标交易日数量 | `20` |
| `suite_id` | 压测 suite | Theta suite | 每次复核 | 对应 `provider_benchmark_suite_run` | `6` |
| `status` | 窗口判断 | Pi 阈值 | 每次复核 | pass/warning/failed/missing | `warning` |
| `coverage_rate` | 覆盖率 | suite 指标 | 每次复核 | matched/primary_rows | `1.00000000` |
| `conflict_rate` | 冲突率 | suite 指标 | 每次复核 | conflict/comparable_fields | `0.16666667` |
| `failure_rate` | 失败率 | suite 指标 | 每次复核 | failed shard / benchmark_count | `0.00000000` |
| `p95_latency_ms` | P95 延迟 | suite 指标 | 每次复核 | 分片请求延迟 P95 | `0.5526` |
| `rows_per_second` | 吞吐 | suite 指标 | 每次复核 | 主备源总行数/耗时 | `4912.9969` |

## 28. Rho 收入对账和客户健康

Rho 阶段把 Omicron 账单、Xi 价格规则和 Iota 用量日报重算成收入对账结果，并沉淀 AR aging 与客户健康快照。

### 28.1 `revenue_reconciliation_run`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `reconciliation_code` | 对账编码 | Rho 脚本 | 每次复核 | tenant+project+product+period+date 稳定编码 | `rho-recon-demo-quant-research-a_share_daily_core-20260701-20260731-20260726` |
| `tenant_id/project_id` | 客户和项目 | Xi/Iota 元数据 | 每次复核 | 对账所属客户项目 | `demo/quant-research` |
| `subscription_id/product_id/plan_id` | 订阅、产品、价格计划 | Xi 订阅 | 每次复核 | 计费合同口径 | `a_share_daily_core/quant_starter_monthly` |
| `invoice_id` | 已开票账单 | Omicron 账单 | 每次复核 | 可为空，空表示缺失账单 | `1` |
| `period_start/period_end` | 对账账期 | Rho 参数 | 每次复核 | 账单周期 | `2026-07-01..2026-07-31` |
| `status` | 对账状态 | Rho 规则 | 每次复核 | matched/mismatch/missing_invoice/warning | `matched` |
| `recomputed_total_amount` | 重算金额 | Omicron 行生成口径 | 每次复核 | 按当前用量和价格规则重算 | `0.16002800` |
| `invoice_total_amount` | 开票金额 | Omicron invoice | 每次复核 | 已开票总额 | `0.16002800` |
| `amount_delta` | 金额差异 | Rho 规则 | 每次复核 | invoice_total - recomputed_total | `0.00000000` |
| `mismatch_line_count` | 差异明细数 | 行级对账 | 每次复核 | 行级 mismatch 数 | `0` |

### 28.2 `revenue_reconciliation_line`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `line_key` | 对账行键 | Rho 规则 | 每次复核 | product+rule+api+metric+unit_price | `p:1|r:1|api:price|m:cost_unit|u:0.0100000000` |
| `api_name/metric_name` | API 和计费指标 | Omicron/Xi | 每次复核 | API 级计费项 | `price/cost_unit` |
| `status` | 行级状态 | Rho 规则 | 每次复核 | matched/mismatch/missing_invoice_line/extra_invoice_line | `matched` |
| `recomputed_amount` | 重算行金额 | Rho 重算 | 每次复核 | 当前规则计算金额 | `0.04000800` |
| `invoice_amount` | 开票行金额 | Omicron line | 每次复核 | 已开票行金额 | `0.04000800` |
| `amount_delta` | 行金额差异 | Rho 规则 | 每次复核 | invoice_amount - recomputed_amount | `0.00000000` |

### 28.3 `ar_aging_snapshot`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `aging_code` | 应收账龄编码 | Rho 脚本 | 每次快照 | tenant+project+product+plan+currency+as_of | `rho-ar-demo-quant-research-a_share_daily_core-...` |
| `as_of_date` | 快照日期 | Rho 参数 | 每次快照 | 账龄观察日 | `2026-07-26` |
| `status` | 账龄状态 | Rho 规则 | 每次快照 | current/watch/overdue/critical | `current` |
| `outstanding_amount` | 未收金额 | Omicron invoice | 每次快照 | 非 void 账单未收合计 | `0.00000000` |
| `current_amount` | 未到期金额 | Omicron due_date | 每次快照 | 未逾期未收金额 | `0.00000000` |
| `bucket_1_30_amount` | 逾期 1-30 天 | Omicron due_date | 每次快照 | 逾期 1 到 30 天未收 | `0.00000000` |
| `bucket_31_60_amount` | 逾期 31-60 天 | Omicron due_date | 每次快照 | 逾期 31 到 60 天未收 | `0.00000000` |
| `bucket_61_90_amount` | 逾期 61-90 天 | Omicron due_date | 每次快照 | 逾期 61 到 90 天未收 | `0.00000000` |
| `bucket_90_plus_amount` | 逾期 90 天以上 | Omicron due_date | 每次快照 | 逾期超过 90 天未收 | `0.00000000` |

### 28.4 `customer_health_snapshot`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `health_code` | 客户健康编码 | Rho 脚本 | 每次快照 | tenant+project+subscription+as_of | `rho-health-demo-quant-research-demo_quant-...` |
| `status` | 客户健康状态 | Rho 规则 | 每次快照 | active/at_risk/dormant/churned | `active` |
| `retention_signal` | 留存信号 | Rho 规则 | 每次快照 | healthy/payment_risk/usage_declining/inactive/no_usage | `healthy` |
| `health_score` | 健康分 | Rho 规则 | 每次快照 | 0-100，综合活跃和付款风险 | `100` |
| `last_usage_date` | 最近使用日 | Iota 用量日报 | 每次快照 | 产品内 billable API 最近调用日期 | `2026-07-26` |
| `request_count_30d` | 30 日请求数 | Iota 用量日报 | 每次快照 | 产品内 billable API 请求数 | `16` |
| `outstanding_amount` | 未收金额 | Omicron invoice | 每次快照 | 客户当前未收金额 | `0.00000000` |
| `overdue_invoice_count` | 逾期账单数 | Omicron invoice | 每次快照 | 当前逾期未收账单数 | `0` |

## 29. Sigma 运行可观测和容量预警

Sigma 阶段把 API 审计、worker、部署健康、供应商 readiness、账单/客户健康和容量阈值聚合成可长期追踪的运行事实。

### 29.1 `runtime_log`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `log_code` | 日志编码 | Sigma/业务组件 | 每次事件 | 全局唯一，支持幂等更新 | `sigma-log-local-sigma-runtime-collection-20260726120000000000` |
| `environment` | 环境 | 采集参数 | 每次事件 | local/staging/prod 等 | `local` |
| `component` | 组件 | 采集参数 | 每次事件 | api/worker/postgres/sigma 等 | `sigma` |
| `service_name` | 服务名 | 采集参数 | 每次事件 | 运行服务或任务名 | `qdata-runtime` |
| `severity` | 严重级别 | 采集参数 | 每次事件 | debug/info/warning/error/critical | `info` |
| `event_type` | 事件类型 | 采集参数 | 每次事件 | runtime_collection/runtime_event 等 | `runtime_collection` |
| `message` | 日志摘要 | 采集参数 | 每次事件 | 可读运维信息 | `Sigma runtime collection completed` |

### 29.2 `runtime_metric_snapshot`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `metric_code` | 指标编码 | Sigma 采集 | 每次采集 | environment+component+metric+时间稳定编码 | `sigma-metric-local-api-api-request-count-7d-...` |
| `metric_name` | 指标名 | Sigma 采集 | 每次采集 | API 请求、失败率、慢请求、worker 失败等 | `api_request_count_7d` |
| `metric_value` | 指标值 | 源事实表聚合 | 每次采集 | 保留 12 位小数，兼容 count/ratio/ms/CNY | `271.000000000000` |
| `unit` | 单位 | Sigma 采集 | 每次采集 | requests/ratio/ms/runs/alerts/CNY/tables | `requests` |
| `status` | 阈值状态 | Sigma 规则 | 每次采集 | normal/warning/critical | `warning` |
| `warning_threshold` | warning 阈值 | Sigma 配置 | 每次采集 | 达到后生成 warning 指标 | `200` |
| `critical_threshold` | critical 阈值 | Sigma 配置 | 每次采集 | 达到后生成 critical 指标 | `1000` |

### 29.3 `runtime_daily_report`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `report_code` | 日报编码 | Sigma 生成 | 每日/每次重算 | environment+report_date 稳定编码 | `sigma-runtime-local-20260726` |
| `report_date` | 报告日期 | Sigma 参数 | 每日 | 运行观测所属自然日 | `2026-07-26` |
| `status` | 日报状态 | Sigma 规则 | 每次重算 | success/warning/critical | `warning` |
| `api_request_count` | 当日 API 请求数 | `api_request_audit` | 每次重算 | started_at 当日请求数 | `213` |
| `api_failed_count` | 当日 API 失败数 | `api_request_audit` | 每次重算 | status=failed 数量 | `0` |
| `api_error_rate` | 当日失败率 | API 失败/请求 | 每次重算 | failed/request | `0.00000000` |
| `worker_failed_count` | worker 失败数 | `worker_run` | 每次重算 | 当日 status=failed run 数量 | `0` |
| `deployment_health_status` | 最新部署健康 | Nu 健康快照 | 每次重算 | 报告日前最新状态 | `success` |
| `open_capacity_alert_count` | open 容量告警数 | `capacity_alert` | 每次重算 | 当日报告环境 open 告警数 | `1` |

### 29.4 `capacity_alert`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `alert_key` | 告警幂等键 | Sigma 规则 | 指标超阈值时 | environment+component+metric 稳定键 | `sigma-capacity-local-api-api-request-count-7d` |
| `alert_id` | 通用告警 ID | `alert_event` | 告警写入时 | 对应通用告警中心 | `9` |
| `component/metric_name` | 组件与指标 | 指标快照 | 指标超阈值时 | 告警归属和指标名 | `api/api_request_count_7d` |
| `severity` | 告警级别 | Sigma 规则 | 指标超阈值时 | warning 映射 medium，critical 映射 critical | `medium` |
| `status` | 告警状态 | Sigma/人工处理 | 超阈值或恢复时 | open/acknowledged/resolved/ignored | `open` |
| `metric_value` | 触发值 | 指标快照 | 指标超阈值时 | 当前指标值 | `271.000000000000` |
| `threshold_value` | 阈值 | 指标快照 | 指标超阈值时 | 触发 warning/critical 的阈值 | `200.000000000000` |
| `message` | 告警摘要 | Sigma 规则 | 指标超阈值时 | 可投递给通知通道 | `local/api/... reached warning threshold` |

## 30. Tau 真实回款、自动匹配和收入 Ledger

Tau 阶段把 Omicron 发票从“手工标记 paid”推进到真实回款流水驱动：先导入支付/银行流水，再按发票号、币种和金额匹配，最后沉淀收入 ledger。

### 30.1 `payment_import_batch`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `batch_code` | 回款批次编码 | 导入参数 | 每批流水 | 全局唯一，支持幂等导入 | `tau-demo-payments-20260727` |
| `source_type` | 流水来源类型 | 导入参数 | 每批流水 | bank_csv/alipay_csv/wechat_csv/manual_csv/api/demo | `demo` |
| `account_code` | 收款账户编码 | 导入参数 | 每批流水 | 银行或支付账户内部编码 | `demo-bank-cny` |
| `statement_start/statement_end` | 对账单日期范围 | 导入参数 | 每批流水 | 原始账单覆盖日期 | `2026-07-27..2026-07-27` |
| `currency` | 批次币种 | 导入参数 | 每批流水 | 原始流水主币种 | `CNY` |
| `status` | 批次状态 | Tau 汇总 | 每次导入/匹配 | imported/matched/partially_matched/failed/void | `matched` |
| `transaction_count` | 流水笔数 | Tau 汇总 | 每次导入/匹配 | 批次内 transaction 数 | `1` |
| `matched_count/unmatched_count` | 匹配/未匹配笔数 | Tau 汇总 | 每次匹配 | 按 payment_transaction status 汇总 | `1/0` |
| `total_amount/matched_amount/unmatched_amount` | 总额/已匹配/未匹配金额 | Tau 汇总 | 每次匹配 | 原币金额，保留 8 位小数 | `100.00000000` |

### 30.2 `payment_transaction`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `transaction_code` | 付款流水编码 | 外部交易号或 Tau 生成 | 每笔流水 | 全局唯一，重复导入幂等 | `tau-pay-tau-demo-payment-20260727` |
| `external_transaction_id` | 外部交易号 | 银行/支付机构 | 每笔流水 | 同一 batch 内唯一 | `tau-demo-payment-20260727` |
| `payment_channel` | 支付渠道 | 原始流水 | 每笔流水 | bank/alipay/wechat/manual/api | `bank` |
| `transaction_time/value_date` | 交易时间/入账日 | 原始流水 | 每笔流水 | value_date 用于财务归属 | `2026-07-27` |
| `direction` | 收支方向 | 原始流水 | 每笔流水 | inbound/outbound | `inbound` |
| `amount/base_amount` | 原币/本位币金额 | 原始流水+汇率 | 每笔流水 | 多币种时按 fx_rate_to_base 折算 | `100.00000000` |
| `status` | 流水状态 | Tau 匹配 | 每次匹配 | imported/matched/partially_matched/overpaid/unmatched/ignored/reversed | `matched` |
| `reference_text` | 备注 | 原始流水 | 每笔流水 | 可包含 `inv-*` 发票号 | `Payment for inv-demo-...` |
| `invoice_id` | 匹配发票 | Tau 匹配 | 每次匹配 | 匹配成功后回填 | `2` |

### 30.3 `payment_invoice_match`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `match_code` | 匹配编码 | Tau 生成 | 每次匹配 | transaction+invoice 稳定编码 | `tau-match-tau-pay-...` |
| `transaction_id/invoice_id` | 流水和发票 | Tau 匹配 | 每次匹配 | 唯一约束避免重复匹配 | `1/2` |
| `match_type` | 匹配类型 | Tau 规则 | 每次匹配 | auto_exact/auto_partial/auto_overpay/manual/rule_suggested | `auto_exact` |
| `status` | 匹配状态 | Tau 规则 | 每次匹配 | matched/partial/overpaid/unmatched/reversed | `matched` |
| `matched_amount` | 匹配金额 | Tau 规则 | 每次匹配 | 用于更新 invoice paid_amount | `100.00000000` |
| `unmatched_amount` | 未匹配余额 | Tau 规则 | 每次匹配 | overpaid 时保留多付金额 | `0.00000000` |
| `match_score` | 匹配置信度 | Tau 规则 | 每次匹配 | 0-1 | `1.000000` |

### 30.4 `revenue_ledger_entry`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `ledger_code` | Ledger 分录编码 | Tau 生成 | 每笔分录 | 全局唯一，重复执行幂等更新 | `tau-ledger-payment_received-...` |
| `entry_date` | 分录日期 | payment value_date | 每笔分录 | 财务归属日期 | `2026-07-27` |
| `entry_type` | 分录类型 | Tau 规则 | 每笔分录 | invoice_issued/payment_received/payment_matched/payment_unmatched/refund/adjustment | `payment_received` |
| `debit_amount/credit_amount/balance_amount` | 借/贷/余额 | Tau 规则 | 每笔分录 | 原币金额，回款 received 记 credit，匹配记 debit | `100.00000000` |
| `base_debit_amount/base_credit_amount/base_balance_amount` | 本位币金额 | Tau 汇率 | 每笔分录 | base_currency 折算金额 | `100.00000000` |
| `transaction_id/match_id/invoice_id` | 关联事实 | Tau 匹配 | 每笔分录 | 支持从 ledger 追溯到流水、匹配和发票 | `1/1/2` |

### 30.5 `fx_rate_daily`

| 字段名 | 中文含义 | 来源 | 更新频率 | 口径 | 样例 |
|---|---|---|---|---|---|
| `rate_code` | 汇率编码 | Tau/供应商 | 每日 | date+from+to+provider 稳定编码 | `fx-20260727-USD-CNY-manual` |
| `rate_date` | 汇率日期 | 汇率源 | 每日 | 折算使用日期 | `2026-07-27` |
| `from_currency/to_currency` | 原币/目标币 | 汇率源 | 每日 | 默认目标币 CNY | `USD/CNY` |
| `rate` | 汇率 | 汇率源 | 每日 | 保留 12 位小数，必须大于 0 | `7.180000000000` |
| `provider` | 汇率来源 | 导入参数 | 每日 | manual/vendor/bank 等 | `manual` |

## 31. 数据来源优先级

MVP 需要为每个数据集建立主源和备源。

| 数据集 | 主源 | 备源 | 更新频率 | 授权待确认 |
|---|---|---|---|---|
| 股票主数据 | 待确认 | 待确认 | 日级/事件 | 是 |
| 交易日历 | 交易所/数据商 | 手工校验 | 年度/临时 | 是 |
| 日线行情 | 待确认 | 待确认 | 日级 | 是 |
| 分钟线行情 | 待确认 | 待确认 | 分钟/日级 | 是 |
| 复权因子 | 待确认 | 系统计算 | 事件驱动 | 是 |
| 财务三表 | 待确认 | 公告解析 | 季度/事件 | 是 |
| 业绩预告 | 公告/数据商 | 公告解析 | 事件驱动 | 是 |
| 指数成分 | 指数公司/数据商 | 待确认 | 调仓/日级 | 是 |
| 行业分类 | 申万/中信授权源 | 待确认 | 调整时 | 是 |

## 32. 待确认项汇总

- 数据授权和可再分发边界。
- 首批数据供应商。
- 分钟线历史长度和更新延迟。
- 交易量单位统一为股还是手。
- 换手率分母口径。
- 财务披露时间精确到日期还是时间戳。
- 财报重述的版本识别规则。
- 指数权重采用调仓权重还是日频收盘权重。
- 行业分类公告日和生效日来源。
- 因子是否保存标准化和去极值后的衍生值。
