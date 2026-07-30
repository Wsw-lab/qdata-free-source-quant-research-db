# Mock 与 SQL 后端联调报告

## 1. 本次目标

本次将 Python SDK 从纯 mock 后端推进到可连接真实 PostgreSQL + ClickHouse 的 SQL 后端。

已保留 mock 作为默认后端，避免没有数据库环境时无法开发和测试。

## 2. 已完成内容

- `Client` 支持 `backend="mock"`、`backend="sql"`、`backend="auto"`。
- 支持通过环境变量配置：
  - `QDATA_BACKEND`
  - `QDATA_POSTGRES_DSN`
  - `QDATA_CLICKHOUSE_DSN`
- 新增 Docker Compose 本地数据库环境。
- 新增 PostgreSQL 和 ClickHouse seed 数据。
- 新增 PostgreSQL 连接封装 `PostgresClient`。
- 新增 ClickHouse 连接封装 `ClickHouseClient`。
- 新增真实查询层 `SqlBackend`。
- 新增 SQL backend 单元测试，使用假数据库客户端验证参数流和返回结构。
- 新增 `.env.example`。
- 新增 `examples/sql_backend_smoke.py`。

## 3. 已覆盖接口

SQL 后端已实现：

- `get_security_master`
- `get_trading_calendar`
- `get_price`
- `get_adjustment_factor`
- `get_trading_constraints`
- `get_fundamental_asof`
- `get_index_members_asof`
- `get_industry_asof`
- `get_universe`
- `get_factor`
- `get_dataset_health`

## 3.1 CSV 导入 Alpha

新增真实文件导入闭环：

- `scripts/check_data_quality.py`：检查本地 CSV。
- `scripts/ingest_daily_bar.py`：导入证券主数据、交易日历和日线行情。
- `qdata/ingest/`：CSV 解析、标准化、质量检查和 pipeline。
- `qdata/loaders/`：PostgreSQL + ClickHouse 写入器。
- `raw/samples/`：最小可复现样例数据。

导入覆盖：

- `qmeta.security_master`
- `qmeta.security_identifier_history`
- `qmeta.security_name_history`
- `qmeta.security_status_history`
- `qmeta.trading_calendar`
- `qmeta.adjustment_factor`
- `qmeta.limit_price_daily`
- `qts.daily_bar`
- `qmeta.data_quality_check_result`

## 3.2 日频市场数据同步 Beta

新增 provider 同步层：

- `qdata/sources/registry.py`：provider 注册与创建。
- `qdata/sources/providers/csv_provider.py`：本地 CSV provider。
- `qdata/sources/providers/akshare_provider.py`：AkShare A 股日线 provider。
- `qdata/sources/export.py`：将 provider bundle 输出为标准 CSV 快照。
- `qdata/sources/sync.py`：provider 拉取、raw/vendor 落盘、质量检查和 SQL 入库编排。
- `scripts/sync_daily_market.py`：日频市场数据同步入口。
- `scripts/smoke_daily_market.py`：同步后 SDK 查回 smoke。

实现要点：

- AkShare 依赖限定为 Python 3.10+，当前本机使用 `.venv312` 验收。
- AkShare 支持显式股票池同步，也支持 `--all-market` 解析全市场股票池。
- AkShare 历史 K 线接口不稳定时，会 fallback 到 `stock_zh_a_daily`，多取 20 个自然日来推导目标日 `pre_close` 和涨跌停价，再统一转换到内部 `DailyBarRecord`。
- SQL loader 的主数据 upsert 已改为缺失值不覆盖已有上市日期、退市日期和正式简称。
- 交易约束查询已改为状态历史单行 as-of 口径，避免多来源状态历史导致重复结果。

## 3.3 生产级采集调度 Alpha

新增调度和审计层：

- `db/migrations/0003_postgresql_pipeline_scheduler.sql`：新增调度元数据表。
- `scripts/apply_postgres_migrations.sh`：对已有 PostgreSQL volume 补跑增量 migration。
- `scripts/run_daily_pipeline.py`：日频 pipeline 总入口。
- `qdata/pipeline/models.py`：任务配置、任务记录和运行结果模型。
- `qdata/pipeline/store.py`：PostgreSQL 调度元数据 store。
- `qdata/pipeline/runner.py`：按日期窗口执行 provider sync、失败重试、skip 和 watermark 更新。

新增表：

- `qmeta.pipeline_job`：任务定义。
- `qmeta.pipeline_run`：运行记录，包含 trade_date、attempt、run_type、status、row_count、quality_passed、raw_paths 和错误信息。
- `qmeta.pipeline_watermark`：任务水位线，包含最后成功交易日、最后尝试交易日和连续失败次数。

实现要点：

- 同一 job/date 已有 `success` 时，默认记录 `skipped`，加 `--force` 才重跑。
- 每次失败 attempt 都会记录到 `pipeline_run`，并推进 last_attempt 与 consecutive_failures。
- 只有真正 `success` 才推进 last_success watermark。
- pipeline 复用 `sync_daily_market`，因此 CSV 和 AkShare 自动共享标准化、raw/vendor 快照、质量检查和 SQL 入库。
- `start_local_stack.sh` 会自动补跑 PostgreSQL 增量 migration，避免已有数据卷漏表。
- 数据质量检查新增正价格、VWAP 区间、成交额/成交量/VWAP 一致性和换手率极值检查。

## 3.4 A 股全市场日频生产 Beta

新增全市场生产能力：

- `qdata/sources/universe.py`：provider 股票池解析和交易日判断门面。
- `CsvProvider.list_symbols/is_trade_date`：本地样例全市场和交易日判断。
- `AkShareProvider.list_symbols/is_trade_date`：AkShare 全市场股票池和交易日判断。
- `sync_daily_market`：支持 `batch_size`、`expected_symbols`、`min_completeness` 和分批聚合。
- `scripts/smoke_full_market_daily.py`：生产 smoke，查询 pipeline_run、ClickHouse 行数、SDK 样例价格和数据健康。
- `db/migrations/0004_postgresql_full_market_pipeline.sql`：记录 all-market、批次数、预期行数、缺失股票和完整率。

实现要点：

- 全市场模式通过 `--all-market` 打开，provider 自动解析股票池。
- AkShare 优先使用 `stock_info_a_code_name` 获取全市场代码简称，东方财富 spot 只作为备用，降低网络抖动影响。
- `--batch-size` 用于分批拉取，所有 batch 会合并成一个标准 `DailyMarketBundle` 后统一入库，避免质量报告被多批覆盖。
- `--max-symbols` 支持小样本 smoke 和灰度限量。
- `--min-completeness` 低于阈值时 pipeline 标记 `partial_success`，不会推进 success watermark。
- 非交易日默认 `skipped`，可用 `--no-skip-closed-days` 覆盖。
- `list_date IS NULL` 的 active 证券在 as-of 查询中视为可见，避免代码简称类数据源缺失上市日期时查不回行情。
- 数据质量检查会写入 `job_code/run_id` 上下文，smoke 按当前 job/source 读取 health，避免同一交易日不同任务互相覆盖验收结果。

## 3.5 A 股全市场日频生产 Gamma

新增生产闭环能力：

- `db/migrations/0005_postgresql_production_gamma.sql`：新增交易所级完整率字段和 `qmeta.pipeline_repair_queue`。
- `qdata/pipeline/production.py`：生产窗口解析、watermark 续跑、日报摘要格式化。
- `scripts/run_daily_production.py` / `scripts/run_daily_production.sh`：增量、回补和重跑入口。
- `scripts/run_repair_queue.py`：按 open repair queue 重跑问题日期。
- `scripts/report_daily_production.py`：只读生产日报。
- `scripts/benchmark_daily_query.py`：SDK + SQL backend 查询压测。

实现要点：

- 增量模式可从 `pipeline_watermark.last_success_trade_date` 的下一天继续，也支持 lookback 复查。
- `partial_success/failed` 自动写入修复队列，重跑 `success` 后自动 resolved。
- 完整率记录 SH/SZ/BJ 交易所拆分，并保留缺失证券解释。
- 上市日晚于目标日、退市早于目标日的证券不计入当日应有分母。
- 生产日报输出 status 统计、缺失总数、最低完整率和逐日 run 摘要。

## 3.6 A 股量化行情 Delta

新增量化行情可用性能力：

- `db/migrations/0006_postgresql_quant_market_delta.sql`：新增复权/约束/universe 索引和 `matrix_export_audit`。
- `MarketConstraintBundle` / `MinuteMarketBundle`：provider 标准输出复权、涨跌停、停牌和分钟线。
- `scripts/sync_market_constraints.py`：独立同步 `adjustment_factor`、`limit_price_daily`、`suspension_history`。
- `scripts/build_tradable_universe.py`：生成并持久化每日可交易股票池。
- `scripts/export_price_matrix.py`：导出 `trade_date x symbol` 价格矩阵 CSV/Parquet，并写入导出审计。
- `scripts/sync_minute_market.py`：分钟线 Alpha 入库到 `qts.minute_bar`。
- `Client.get_tradable_universe`：SDK 直接获取可交易股票池。

实现要点：

- CSV provider 可从日线样本派生复权、涨跌停、停牌和一分钟样例。
- AkShare provider 尝试通过 qfq/hfq 收盘价推导复权因子，失败时回落到日线因子。
- 交易约束查询新增 `is_new_listing`，可交易股票池默认排除 ST、停牌、新股、退市期和上市天数不足。
- 矩阵出口固定使用 SDK 查询结果转宽表，CSV 必达，Parquet 依赖 pandas/pyarrow 环境。

## 3.7 A 股量化服务 Epsilon

新增服务化和多源融合能力：

- `db/migrations/0007_postgresql_service_fusion_epsilon.sql`：新增 `source_priority`、`data_conflict_daily`、`api_token`、`api_request_audit`、`multi_source_quality_daily`。
- `qdata.fusion`：比较两个 `DailyMarketBundle` 的字段级差异，输出覆盖率、冲突率和 fallback 尝试记录。
- `csv_mirror` provider：作为确定性备源，用 `close_offset_bps` 构造可复现冲突。
- `scripts/compare_daily_sources.py`：多源对账，可 dry-run，也可写入 PostgreSQL 冲突和质量日报。
- `qdata.api`：标准库 REST 服务，覆盖 `/price`、`/constraints`、`/tradable-universe`、`/matrix`。
- `TokenAuth`：支持 Bearer token、`X-API-Token`、scope、分钟配额和数据库 token 校验基础。
- `scripts/smoke_api_server.py`：真实 HTTP smoke，覆盖 JSON 和 CSV 返回。

实现要点：

- 多源融合先保留主源值，备源差异进入 `data_conflict_daily`，下游可按 severity/status 处理。
- `multi_source_quality_daily` 记录每日主备 coverage 和 conflict rate，可直接作为后续质量看板数据源。
- API 请求无论成功或失败都 best-effort 写入 `api_request_audit`，不阻塞查询主链路。
- Arrow 返回为可选能力；当前系统 Python 未安装 `pyarrow` 时返回明确依赖提示。

## 3.8 A 股量化运维 Zeta

新增生产运维治理能力：

- `db/migrations/0008_postgresql_ops_zeta.sql`：新增 `sla_policy`、`alert_event`、`ops_dashboard_snapshot`。
- `qdata.ops.dashboard`：汇总 pipeline、repair、watermark、质量检查、多源冲突、API 审计和告警。
- `scripts/report_ops_dashboard.py`：输出运维总看板，可写入 snapshot。
- `scripts/check_sla_alerts.py`：创建/更新 SLA 策略，评估并写入告警。
- `scripts/report_api_audit.py`：输出 API 请求量、失败率和慢接口。

实现要点：

- 看板优先从事实表聚合，不重复存明细；snapshot 只存窗口摘要。
- SLA 策略按 job/dataset/source 可选绑定，支持完整率、冲突率、API 错误率、耗时和完成时间。
- 告警使用 `alert_key` 幂等 upsert，同一 policy/date/metric 不重复刷屏。
- API 审计报表直接复用 Epsilon 的 `api_request_audit`。

## 3.9 A 股供应商接入和压测 Eta

新增真实第二数据源接入和供应商评分能力：

- `db/migrations/0009_postgresql_vendor_eta.sql`：新增供应商 profile、provider 错误事件、benchmark run 和供应商质量评分表。
- `qdata.sources.providers.vendor_http_provider`：通用商业 HTTP JSON adapter，支持 Bearer/Header/Query/Basic auth、限频、重试、timeout 和错误归因。
- `qdata.eta`：多日 provider benchmark、供应商评分、benchmark 落库和融合质量日报写入。
- `scripts/register_vendor_profile.py`：注册或更新供应商接入 profile。
- `scripts/benchmark_vendor_sources.py`：对主备源按日期窗口做字段级比较，并写入 benchmark、评分和多源质量表。
- `scripts/report_vendor_scores.py`：输出 dataset 维度最新供应商评分榜。

实现要点：

- 商业 vendor 没有真实账号时，`vendor_http` 可用 fixture 模式验收同一 provider 名称、字段映射、对账、评分和落库链路。
- AkShare 可作为真实开源第二源做小样本 benchmark，用来检验网络 provider、延迟统计和字段口径差异。
- benchmark 写库时同步调用 Epsilon 的融合落库能力，`data_conflict_daily` 和 `multi_source_quality_daily` 能继续被 Zeta 看板复用。
- 评分模型按 coverage 35%、conflict 25%、stability 20%、latency 10%、cost 5%、license 5% 输出 A/B/C/D。
- provider 错误按 auth、rate_limit、timeout、network、server、client、schema、unknown 分类，为后续自动补偿和供应商 SLA 做准备。

## 3.10 A 股真实供应商生产化 Theta

新增供应商生产化、分片压测、Provider SLA 和上线决策能力：

- `db/migrations/0010_postgresql_vendor_theta.sql`：新增字段映射、分片 benchmark suite、上线决策报告，并扩展 SLA provider 阈值。
- `qdata.sources.field_mapping`：统一处理外部字段名、日期格式、成交量手转股、金额单位和比例转换。
- `qdata.theta`：读取 `QDATA_VENDOR_*` 生产配置、管理 profile 状态、执行分片 benchmark、聚合 suite 评分并生成上线决策。
- `scripts/register_vendor_field_mapping.py`：注册默认日线字段映射。
- `scripts/benchmark_vendor_universe.py`：支持全市场股票池、分片、5/20/60 交易日窗口和 suite 聚合。
- `scripts/check_provider_sla_alerts.py`：把供应商评分、冲突率、失败率、延迟和错误数接入 `alert_event`。
- `scripts/report_vendor_decisions.py`：输出 primary/backup/research_only/reject 上线建议。

实现要点：

- `vendor_http` 生产 HTTP 模式可读取环境变量，但真实 token 不入库。
- 字段映射层保留 0 值，避免成交量、成交额、价格为 0 时被 fallback 逻辑误判为缺失。
- 分片 suite 会把子 benchmark 明细继续写入 Eta 表，并额外写入 suite 聚合结果，覆盖供应商日度聚合评分。
- Provider SLA 沿用 Zeta `sla_policy`/`alert_event`，不另建告警体系。
- 决策逻辑把高分但冲突率不达 primary 阈值的 vendor 降为 backup，避免只看总分上线。

## 3.11 A 股生产运营闭环 Iota

新增租户权限、告警通知、API 用量计量和供应商压测调度能力：

- `db/migrations/0011_postgresql_ops_iota.sql`：新增 tenant/project/principal/project_member/dataset_access_policy、api_usage_daily、notification_channel、alert_notification_delivery 和 vendor_benchmark_schedule。
- `qdata.iota`：封装租户 ACL 初始化、dataset 授权校验、通知投递、用量 rollup、压测 schedule 创建和运行。
- `qdata.api.auth/server/audit`：数据库 token 可携带 tenant/project/principal，REST 请求写入租户上下文和成本单位，并在查询前做 dataset ACL。
- `scripts/bootstrap_iota_security.py`：初始化租户、项目、主体、DB token 和数据集权限。
- `scripts/register_notification_channel.py` / `scripts/send_alert_notifications.py`：注册通道并投递 open alert。
- `scripts/report_api_usage.py`：把 API 审计聚合成项目/主体/API 维度日报。
- `scripts/manage_vendor_benchmark_schedule.py`：固化 Theta suite 参数并可立即运行。

实现要点：

- 未绑定租户的环境变量 token 保持兼容；绑定数据库 token 后按 `daily_bar`、`limit_price_daily`、`tradable_universe` 等 dataset 做权限校验。
- 用量 rollup 使用 NULL-safe 匹配，重复执行不会因为旧 token 的空租户字段产生重复日报。
- 通知投递记录 `delivery_key`、尝试次数、响应摘要和错误信息，先支持 stdout/webhook/feishu/email 的统一通道模型。
- 供应商压测 schedule 复用 Theta `run_sharded_provider_benchmark` 和 `record_benchmark_suite_report`，避免另起一套评分逻辑。
- 默认字段映射扩展到 `adjustment_factor`、`limit_price_daily` 和 `security_master`。

## 3.12 A 股运营管理 API Kappa

新增只读运营管理 API、CLI 和内部运营台：

- `qdata.kappa`：封装 overview、tenant、project、principal、token、dataset ACL、通知投递、供应商 schedule 和用量日报查询。
- `qdata.api.server`：新增 `/admin/*`、`/usage/daily` 和 `/admin/console` 路由，Kappa 路径要求 `admin` scope。
- `qdata.api.auth`：环境 token 支持配置 scopes，数据库 token 继续读取 `api_token.scopes`。
- `scripts/report_kappa_admin.py`：命令行查询 Kappa 只读资源。
- `scripts/smoke_kappa_admin_api.py`：对运行中的 Kappa API 做真机 smoke。

实现要点：

- Kappa 不新增底层表，直接复用 Iota/Zeta/Theta 的生产运营事实表。
- token 列表只返回 `token_hash_tail` 后 8 位，不返回完整 hash 或明文 token。
- `/admin/console` 是服务端生成的只读 HTML 页面，与管理 API 走同一套 admin scope 鉴权。
- Kappa API 接入后，原有 `/price`、`/constraints`、`/tradable-universe` 和 `/matrix` 行为保持兼容。

## 3.13 A 股后台自动化 Worker Lambda

新增后台自动化 worker、运行记录和 Kappa 观测入口：

- `db/migrations/0012_postgresql_ops_lambda.sql`：新增 `worker_run` 和 `worker_task_run`。
- `qdata.lambda_worker`：封装 `usage_rollup`、`alert_dispatch`、`vendor_benchmark_schedule` 三类 task。
- `scripts/run_lambda_worker.py`：支持 `--once`、`--task`、`--dry-run`、`--schedule-code` 和 `--channel-code`。
- `qdata.kappa`：新增 `/admin/worker-runs` 查询，并在 `/admin/console` 展示 Worker Runs。

实现要点：

- worker 总状态和 task 状态都支持 running/success/warning/failed/skipped。
- dry-run 会记录 worker run，但 usage/alert/vendor task 只预览，不执行真实供应商压测。
- vendor schedule 复用 Iota/Theta 的 `run_vendor_benchmark_schedule`，不复制 benchmark 逻辑。
- fixture vendor suite 返回 warning 时，worker 总状态为 warning，failed_count 仍为 0，便于区分“任务失败”和“数据质量警示”。

## 3.14 A 股后台调度器 Mu

新增长期调度、数据库锁、心跳和 Docker profile 运行入口：

- `db/migrations/0013_postgresql_ops_mu.sql`：新增 `worker_schedule`、`worker_lock`、`worker_heartbeat` 和 `worker_schedule_tick`。
- `qdata.mu_scheduler`：封装 due schedule 扫描、锁获取、Lambda worker 触发、schedule 状态推进和 heartbeat 更新。
- `scripts/run_mu_scheduler.py`：支持 `--once`、`--schedule-code`、`--task`、`--force-due`、`--dry-run` 和 JSON 输出。
- `scripts/smoke_mu_scheduler.py`：强制 schedule 到期、跑一次 scheduler，并通过 Kappa 查询 schedule/tick/heartbeat。
- `docker-compose.yml`：新增 `scheduler` profile 下的 `mu-scheduler` service。
- `qdata.kappa`：新增 `/admin/worker-schedules`、`/admin/worker-locks`、`/admin/worker-heartbeats` 和 `/admin/worker-schedule-ticks`。

实现要点：

- 默认初始化 3 个 active schedule：`mu_usage_rollup_5m`、`mu_alert_dispatch_1m`、`mu_vendor_benchmark_daily`。
- 同一 schedule 通过 `worker_lock` 防重复执行，锁过期后其他 scheduler 可接管。
- 每次执行都写 `worker_schedule_tick`，即使未抢到锁、失败或跳过也能审计。
- 调度器本身只负责编排，具体业务继续复用 Lambda worker 和 Iota/Theta 逻辑。

## 3.15 A 股标准部署 Nu

新增标准部署、健康巡检、发布元数据和非破坏性回滚入口：

- `db/migrations/0014_postgresql_ops_nu.sql`：新增 `deployment_release`、`deployment_health_snapshot`、`deployment_health_check` 和 `deployment_event`。
- `qdata.nu_deploy`：封装 Postgres、migration、ClickHouse、API、scheduler 和 Kappa 六类健康检查。
- `scripts/check_nu_health.py`：支持只读巡检、JSON 输出、失败退出码和 `--write-db` 写入健康快照。
- `scripts/deploy_nu_local.sh`：启动数据库、应用 migration、可选启动 API/scheduler profiles，并等待 API `/health` ready 后写入 Nu 健康结果。
- `scripts/rollback_nu_local.sh`：默认只停止 API/scheduler；显式 `--drop-nu-metadata` 才删除 Nu 元数据表。
- `docker-compose.yml`：新增 `app` profile 下的 `qdata-api`，与 `scheduler` profile 形成本地标准拓扑。
- `qdata.kappa`：新增 `/admin/deployment-releases`、`/admin/deployment-health`、`/admin/deployment-health-checks` 和 `/admin/deployment-events`。

实现要点：

- Nu 把“能不能跑”变成可查询事实：release、snapshot、check、event 都落到 `qmeta`。
- 健康检查允许 API 未启动时标记 skipped；部署脚本启动 API 时会等待 `/health` 可访问，避免首次容器安装依赖时抢跑。
- release 状态按健康结果自动更新为 healthy/degraded/failed，Kappa overview 同步展示最新部署健康。
- 回滚入口保持非破坏性，默认不删除业务数据和 Nu 元数据。

## 3.16 A 股数据产品和预算治理 Xi

新增数据产品目录、价格计划、项目订阅、预算评估、预算告警和 hard limit 决策：

- `db/migrations/0015_postgresql_product_xi.sql`：新增 `data_product`、`data_product_dataset`、`data_product_api`、`pricing_plan`、`pricing_rule`、`product_subscription`、`budget_policy`、`budget_usage_snapshot` 和 `budget_alert`。
- `qdata.xi_billing`：封装产品/价格/订阅/预算配置、预算周期计算、用量金额计算、snapshot/alert 写入和 hard limit 决策。
- `scripts/bootstrap_xi_commercial.py`：初始化默认商业目录 `a_share_daily_core`、价格计划 `quant_starter_monthly`、项目订阅和 demo 月预算。
- `scripts/report_xi_billing.py`：只读查询 Xi 资源，也可执行预算评估并写入预算快照/告警。
- `qdata.api.server`：DB token 查询前接入预算 hard limit 检查，兼容 env token 和未配置预算的旧链路。
- `qdata.kappa`：新增 `/admin/data-products`、`/admin/pricing-plans`、`/admin/pricing-rules`、`/admin/product-subscriptions`、`/admin/budget-policies`、`/admin/budget-usage` 和 `/admin/budget-alerts`。

实现要点：

- 产品目录把 dataset 和 API 绑定到可售产品，预算评估可以只统计产品内 billable API。
- 价格规则先支持 cost_unit/request/row/export/monthly_fee，当前本地样例使用 `cost_unit * 0.01`。
- 预算快照从 `api_usage_daily` 计算，因此可以复用 Iota/Mu 的用量 rollup。
- 预算告警升级时会关闭同周期旧等级告警，避免 warning/exceeded/blocked 同时 open。
- hard limit 决策在不写 HTTP 审计的情况下已验证：开启 hard limit 后 `price` 请求会返回 blocked 决策，恢复后保持只告警不阻断。

## 3.17 A 股月度账单和收入回款 Omicron

新增月度账单、账单明细、账单事件、收入汇总和应收/实收状态：

- `db/migrations/0016_postgresql_billing_omicron.sql`：新增 `invoice`、`invoice_line` 和 `invoice_event`。
- `qdata.omicron_billing`：封装账期校验、账单状态、明细金额计算、账单生成、回款状态更新和账单报表格式。
- `scripts/generate_omicron_invoices.py`：从 Xi 订阅、价格规则和 Iota 用量日报生成账单。
- `scripts/report_omicron_revenue.py`：通过 Kappa 只读端点查看账单、明细、事件和收入汇总。
- `scripts/update_omicron_invoice_status.py`：更新 paid/overdue/void 等状态并写入账单事件。
- `qdata.kappa`：新增 `/admin/invoices`、`/admin/invoice-lines`、`/admin/invoice-events` 和 `/admin/revenue-summary`，overview/console 展示收入、实收、未收和逾期指标。

实现要点：

- 账单编码按 tenant/project/product/period 生成，重复生成同账期同订阅账单保持幂等。
- 账单明细按 billable API 匹配专属价格规则，找不到专属规则时使用通用规则；完全无规则时保留 fallback cost_unit 明细，方便对账而不是静默丢失用量。
- 回款更新会同步维护 `paid_amount`、`outstanding_amount`、`paid_at` 和账单事件。
- Kappa CLI 对 Omicron 资源使用专用字段顺序，优先展示 status、total、paid 和 outstanding。

## 3.18 A 股供应商上线复核 Pi

新增供应商 5/20/60 交易日窗口上线复核、窗口明细、推荐角色和 Kappa 观测入口：

- `db/migrations/0017_postgresql_vendor_pi.sql`：新增 `vendor_readiness_review` 和 `vendor_readiness_window`。
- `qdata.pi_readiness`：封装必要窗口读取、阈值判定、blocking issues 生成和复核结果幂等写入。
- `scripts/report_pi_vendor_readiness.py`：从 Theta suite 汇总 readiness，支持 dry-run、JSON 和 live/contract/profile 强约束。
- `qdata.kappa`：新增 `/admin/vendor-readiness` 和 `/admin/vendor-readiness-windows`，overview/console 展示 ready/watch/rejected 供应商状态。

实现要点：

- Pi 不重新定义压测事实，只读取 Theta 的 `provider_benchmark_suite_run` 最新目标窗口，避免同一指标多处口径漂移。
- 复核状态区分 `ready`、`watch`、`rejected` 和 `incomplete`；上线建议区分 `approve_primary`、`approve_backup`、`watch` 和 `reject`。
- 覆盖率和失败率是硬阈值，冲突率、延迟和吞吐会影响是否只能作为备源。
- fixture vendor 在本地验收中因冲突率高于主源阈值被建议为 `backup`，真实商业 token 接入后可用同一入口开启 live/contract 强约束。

## 3.19 A 股收入对账和客户健康 Rho

新增收入对账、账单重算差异、AR aging、客户健康和 Kappa 观测入口：

- `db/migrations/0018_postgresql_revenue_rho.sql`：新增 `revenue_reconciliation_run`、`revenue_reconciliation_line`、`ar_aging_snapshot` 和 `customer_health_snapshot`。
- `qdata.rho_revenue`：封装 Omicron 账单重算、行级差异、账龄分桶和客户健康规则。
- `scripts/report_rho_revenue.py`：支持 generate-all、generate-reconciliation、generate-ar-aging、generate-customer-health，也可通过 Kappa 只读查询。
- `qdata.kappa`：新增 `/admin/revenue-reconciliation`、`/admin/revenue-reconciliation-lines`、`/admin/ar-aging` 和 `/admin/customer-health`，overview/console 展示经营健康指标。

实现要点：

- Rho 复用 Omicron 的 `build_invoice_lines`，确保“账单生成”和“账单重算”使用同一套计价口径。
- 对账只追加复核结果，不覆盖 Omicron 原始 invoice/line/event，便于财务审计和差异追溯。
- 行级差异按 product、pricing rule、API、metric 和 unit price 生成稳定 line key，能识别 missing、extra 和 mismatch。
- 客户健康结合产品内 billable API 最近使用、30/90 日请求、付款完成度和逾期账单风险。

## 3.20 A 股运行可观测和容量预警 Sigma

新增运行日志、运行指标、运行日报、容量告警和 Kappa 观测入口：

- `db/migrations/0019_postgresql_runtime_sigma.sql`：新增 `runtime_log`、`runtime_metric_snapshot`、`runtime_daily_report` 和 `capacity_alert`，并扩展 `alert_event` 的运行告警类型。
- `qdata.sigma_runtime`：封装阈值判断、运行日志/指标写入、容量告警双写和日报聚合。
- `scripts/report_sigma_runtime.py`：支持 collect、log、metric、daily-report 和 capacity-alerts。
- `qdata.kappa`：新增 `/admin/runtime-logs`、`/admin/runtime-metrics`、`/admin/runtime-daily-reports` 和 `/admin/capacity-alerts`，overview/console 展示运行健康和容量状态。

实现要点：

- Sigma 不改写 API、worker、billing 或 revenue 事实，只做运行态聚合和告警落库。
- 容量告警写入专用 `capacity_alert`，同时同步到通用 `alert_event`，复用现有告警通知链路。
- 指标状态由 warning/critical 阈值统一计算，日报状态根据 API 失败率、worker 失败、部署健康和 open capacity alert 综合判定。
- 同一 environment/component/metric 的容量告警用稳定 `alert_key` 幂等更新，避免重复告警刷屏。

## 3.21 A 股真实回款、自动匹配和收入 Ledger Tau

新增真实回款导入、发票自动匹配、收入 ledger、多币种汇率和 Kappa 观测入口：

- `db/migrations/0020_postgresql_payments_tau.sql`：新增 `payment_import_batch`、`payment_transaction`、`payment_invoice_match`、`revenue_ledger_entry` 和 `fx_rate_daily`。
- `qdata.tau_payments`：封装流水导入、发票号提取、exact/partial/overpaid/unmatched 匹配、invoice 状态刷新和 ledger 分录写入。
- `scripts/report_tau_payments.py`：支持 bootstrap-demo、import-csv、match 以及 Tau Kappa 资源查询。
- `qdata.kappa`：新增 `/admin/payment-batches`、`/admin/payments`、`/admin/payment-matches`、`/admin/revenue-ledger` 和 `/admin/fx-rates`，overview/console 展示回款和匹配状态。

实现要点：

- Tau 不改写 Omicron 原始开票口径；真实回款以付款流水、匹配记录、invoice event 和 ledger 分录追加。
- 重复导入同一 transaction_code 或重复匹配已 paid 发票保持幂等，不会把 matched 流水反向改成 unmatched。
- Ledger 同时保存原币和 base_currency 金额，为真实多币种客户做准备。
- `report_tau_payments.py --resource bootstrap-demo` 可在本地生成独立 Tau demo invoice 并完成回款匹配验收。

## 3.22 A 股前端运营管理台 Upsilon

新增交互式 HTML 运营台、前端筛选、分组视图和独立 smoke：

- `qdata.kappa.render_kappa_console`：升级 `/admin/console` 为 `QData Upsilon Ops Console`，保留 `QData Kappa Ops Console` 兼容标识。
- 控制台页面：新增全局搜索、状态筛选、All/Runtime/Payments/Revenue/Vendor/Automation/Commercial/Governance/Strategy 分组切换。
- `scripts/smoke_upsilon_console.py`：对运行中的 API 服务检查 HTML content-type、Upsilon 控件、Payments/Tau、Runtime/Sigma、Strategy/Phi 和 Governance/Chi 区块。
- `tests/test_upsilon_console.py`：覆盖 Upsilon 控件、分组视图、状态 chip、过滤脚本和 HTML escape。

实现要点：

- Upsilon 不引入前端构建链，服务端直接渲染首屏快照，浏览器内只做本地筛选和显隐。
- 表格横向溢出限制在 `.table-wrap`，移动端页面本身保持不横向撑破。
- 动态值全部通过 HTML escape 输出，避免运营数据中的 `<...>` 破坏页面或形成注入。
- `/admin/console` 仍然走 Kappa admin scope，普通 read token 不可访问。

## 3.23 A 股统一策略引擎 Phi

新增策略元数据、策略运行、策略信号、策略决策和升级事件：

- `db/migrations/0021_postgresql_strategy_phi.sql`：新增 `strategy_policy`、`strategy_run`、`strategy_signal`、`strategy_decision` 和 `strategy_escalation_event`。
- `qdata.phi_strategy`：实现质量、供应商、运行、商业、回款五个策略域的统一评估和幂等落库。
- `scripts/report_phi_strategy.py`：支持 run-all、runs、signals、decisions 和 escalations。
- `qdata.kappa`：新增 `/admin/strategy-runs`、`/admin/strategy-signals`、`/admin/strategy-decisions` 和 `/admin/strategy-escalations`。
- Upsilon：新增 Strategy tab，展示策略运行、信号、决策和升级事件。

实现要点：

- Phi 不改写源事实表，只读取 pipeline/quality、Pi readiness、Sigma runtime、Xi/Rho commercial 和 Tau payment/revenue 事实。
- 每条 signal 保留 source_table、source_ref、metric 和 message，决策可回溯到来源事实。
- high/critical 或 block/escalate 决策生成升级事件，按 source/runtime/commercial/finance owner 区分处理人。
- 同一 run_code 重跑时先替换该 run 的 signals/decisions/escalations，避免重复膨胀。

## 3.24 A 股多租户治理 Chi

新增权限决策审计、项目治理快照、治理动作和 Kappa/Upsilon 观测入口：

- `db/migrations/0022_postgresql_governance_chi.sql`：新增 `access_decision_audit`、`project_governance_snapshot` 和 `governance_action`。
- `qdata.iota`：ACL 命中层级修正为 principal > project > tenant 严格匹配，并支持权限决策审计落库。
- `qdata.chi_governance`：实现权限边界评估、项目治理快照、风险评分和治理动作生成。
- `scripts/report_chi_governance.py`：支持 evaluate-access、collect-snapshots、access-audit、project-governance 和 governance-actions。
- `qdata.kappa`：新增 `/admin/access-decisions`、`/admin/project-governance` 和 `/admin/governance-actions`。
- Upsilon：Governance tab 展示权限决策、项目治理和治理动作。

实现要点：

- principal 级 ACL 只匹配同一 principal，不会因同 tenant/project 字段误下沉给其他主体。
- REST 数据接口在数据库 token 路径下记录 allow/deny、effective_scope、effective_access_level、denied_fields、api_name 和 request_id。
- 项目治理聚合 7 日请求/失败/拒绝访问、预算状态、未回款/逾期账单和开放治理动作。
- warning/critical 项目生成稳定 action_code，同一项目同日同 action_type 重跑保持幂等更新。
- 风险评分兼容预算用量比例和百分数两种输入口径。

## 3.25 A 股自动化执行层 Psi

新增决策自动化 run/action、执行护栏、Kappa/Upsilon 观测入口：

- `db/migrations/0023_postgresql_automation_psi.sql`：新增 `automation_run` 和 `automation_action`。
- `qdata.psi_automation`：实现 Phi/Chi 来源动作映射、dry-run、execute、审批护栏和幂等执行判断。
- `scripts/report_psi_automation.py`：支持 run、runs 和 actions。
- `qdata.kappa`：新增 `/admin/automation-runs`、`/admin/automation-actions` 和 overview 自动化计数。
- Upsilon：Automation tab 展示 Automation Runs 和 Automation Actions。

实现要点：

- Psi 从 Phi `strategy_decision` 和 Chi `governance_action` 读取可行动来源，不直接重新评估业务规则。
- dry-run 默认落审计但不改写源事实，记录 would_execute 和 requires_approval。
- execute 模式下中低风险动作可成功记录执行；高风险动作必须审批，否则停在 approval_required。
- 高风险 action_type 包括 repair_data_quality、degrade_vendor、pause_product、freeze_budget 和 rotate_token。
- 同一 source_type/source_code/action_type 形成稳定 idempotency_key，防止重复真实执行。

## 3.26 A 股自动化控制层 Omega

新增生产级自动化控制、审批、执行器、重试和回滚控制面：

- `db/migrations/0024_postgresql_automation_omega.sql`：新增 `automation_approval`、`automation_executor`、`automation_execution_attempt` 和 `automation_rollback`，并扩展 `automation_action` 控制字段。
- `qdata.omega_control`：实现审批请求/决策、executor 选择、受控执行、失败重试、rollback plan/result 和敏感字段脱敏。
- `scripts/report_omega_control.py`：支持 request-approval、decide-approval、execute、request-rollback、run-rollback 和四类查询。
- `qdata.kappa`：新增 `/admin/automation-approvals`、`/admin/automation-executors`、`/admin/automation-attempts`、`/admin/automation-rollbacks` 和 Omega overview 计数。
- Upsilon：Automation tab 展示 Automation Approvals、Automation Executors、Automation Attempts 和 Automation Rollbacks。

实现要点：

- Psi 继续负责生成动作；Omega 只处理 action 进入生产控制面后的审批、执行、重试和回滚。
- 高风险 action pending/rejected/expired 时不会执行；approved 后才进入 executor。
- 默认 executor 为 noop，不产生外部副作用；webhook/script 需显式配置并显式允许。
- 失败 attempt 按 max_retry_count 和 retry_backoff_seconds 写 next_retry_at，避免无限重试。
- Kappa 查询递归脱敏 token、secret、password、authorization 等敏感字段。

## 3.27 A 股白名单外部执行沙箱 Alpha-2

新增 webhook/script 沙箱真实执行、allowlist、secret ref 和 Upsilon/Kappa 可观测入口：

- `db/migrations/0025_postgresql_automation_alpha2.sql`：扩展 `automation_executor` 安全字段，新增 `automation_executor_allowlist` 和 `automation_secret_ref`。
- `qdata.omega_control`：实现 allowlist 校验、script 相对路径沙箱、webhook HMAC-SHA256 签名、request/response 脱敏和真实 attempt 记录。
- `scripts/alpha2_executor_sandbox.py`：提供仓库内无副作用脚本执行器。
- `scripts/report_omega_control.py`：新增 allowlists/secrets 查询。
- `qdata.kappa`：新增 `/admin/automation-allowlists`、`/admin/automation-secrets` 和 Alpha-2 overview 计数。
- Upsilon：Automation tab 展示 Automation Allowlists 和 Automation Secrets。

实现要点：

- webhook/script executor 必须显式 `--allow-external` 才会 dispatch。
- executor 必须绑定 active allowlist，target 不匹配时失败并写入 blocked_by。
- script target 必须是项目内相对路径、不得包含 `..`，且必须是 `.py` 文件。
- secret ref 只保存 env var 引用，不保存 HMAC 明文；response payload 只记录 signed=true/false。
- 沙箱执行成功仍标记 `external_side_effect=false`，用于区分“真实调度验证”和“生产副作用”。

## 3.28 A 股通知/审批联调闭环 Beta-2

新增外部通知/审批 channel、dispatch、重复抑制、dead-letter 和恢复 runbook：

- `db/migrations/0026_postgresql_automation_beta2.sql`：新增 `automation_external_channel`、`automation_external_dispatch` 和 `automation_recovery_runbook`。
- `qdata.beta2_external`：实现 dispatch、duplicate window suppressed、retry/dead-letter、manual recovery 和 runbook 查询。
- `scripts/report_beta2_external.py`：支持 dispatch、recover、channels、dispatches 和 runbooks。
- `qdata.kappa`：新增 `/admin/automation-channels`、`/admin/automation-dispatches`、`/admin/automation-runbooks` 和 Beta-2 overview 计数。
- Upsilon：Automation tab 展示 Automation Channels、Automation Dispatches 和 Automation Runbooks。

实现要点：

- Beta-2 只在显式 `--allow-external` 时调用外部通道。
- channel 继续绑定 Alpha-2 allowlist 和 secret_ref，不存放明文 token/secret。
- 同一 action/channel/dispatch_type 在 duplicate window 内已有成功 dispatch 时，新记录 status=`suppressed`，不重复调用外部系统。
- 失败 dispatch 根据 channel retry budget 进入 retry_scheduled 或 dead_letter。
- recover 只允许 failed/retry_scheduled/dead_letter，恢复后保留原 response_payload/error_message。

## 3.29 A 股多环境通知通道与密钥轮换 Gamma-2

新增 provider profile、联调验证、候选密钥验证和轮换回滚审计：

- `db/migrations/0027_postgresql_automation_gamma2.sql`：新增 `automation_channel_profile`、`automation_channel_validation` 和 `automation_secret_rotation`。
- `qdata.gamma2_external`：实现 profile validation、secret rotation、rotation rollback、profile/validation/rotation 查询和报告格式化。
- `scripts/report_gamma2_external.py`：支持 validate、rotate、rollback、profiles、validations 和 rotations。
- `scripts/smoke_gamma2_external.py`：自动启动本地签名 webhook，完成 current validation、next secret validation、apply、rollback 和 post-rollback validation。
- `qdata.beta2_external`：增加向后兼容的 secret_ref_override/idempotency_suffix，用于候选 secret 验证前置校验。
- `qdata.kappa`：新增 `/admin/automation-channel-profiles`、`/admin/automation-channel-validations`、`/admin/automation-secret-rotations` 和 Gamma-2 overview 计数。
- Upsilon：Automation tab 展示 Automation Channel Profiles、Automation Channel Validations 和 Automation Secret Rotations。

实现要点：

- Gamma-2 默认只写本地 dry-run provider profile，不保存真实密钥明文。
- secret value 只来自 `automation_secret_ref.metadata.env_var`，报告只展示 secret_ref、env_var 和短 fingerprint。
- `--apply-rotation` 必须先用 candidate secret_ref 完成签名 dispatch validation，失败不更新 channel/profile。
- rollback 只允许 applied rotation，并将 channel/profile secret_ref 回退到旧 secret_ref。
- seeded provider profile 覆盖 feishu、wecom、email 三类通道，为后续真实办公系统测试账号接入留出相同控制面。

## 3.30 A 股企业微信 live validation Delta-2

新增企业微信机器人 live validation、provider receipt 和 Kappa/Upsilon 展示：

- `db/migrations/0028_postgresql_automation_delta2.sql`：新增 `automation_live_provider_receipt`，并 seed 企业微信 live runbook、endpoint secret ref、external channel 和 profile。
- `qdata.delta2_wecom`：实现企业微信 markdown/text payload 构造、env-only webhook endpoint 读取、显式 allow 外发、HTTP/errcode 回执判定、validation/receipt 写入和 receipt 查询。
- `scripts/smoke_delta2_wecom.py`：支持默认 blocked smoke，以及 `--allow-external --require-live` 的真实企业微信发送验收。
- `scripts/report_delta2_wecom.py`：支持 live validation 和 receipt 查询。
- `qdata.kappa`：新增 `/admin/automation-live-receipts`、Delta-2 overview 指标和 console 表格数据。
- Upsilon：Automation tab 展示 Automation Live Receipts，并在概览区展示 Delta2 Live/WeCom/Receipt。

实现要点：

- 真实企业微信 webhook URL 只来自 `QDATA_DELTA2_WECOM_WEBHOOK_URL`，数据库、Kappa API、CLI 和 Upsilon 均不保存或输出 URL 明文。
- 未显式 `--allow-external` 时只写 status=`blocked`，error_message=`external_live_dispatch_disabled`，并记录 `external_side_effect=false`。
- `--require-live` 在缺少 webhook env 时直接失败，避免把 blocked smoke 当作真实企业微信投递成功。
- 企业微信 HTTP 2xx 且 JSON body `errcode=0` 才标记 success；HTTP/网络异常或非 0 errcode 会写 failed/blocked 证据。
- 当前本机 shell 未配置 `QDATA_DELTA2_WECOM_WEBHOOK_URL`，因此本轮只完成 blocked 控制面和审计链路，未向真实企业微信群发送消息。

## 3.31 A 股真实供应商 live token gate Epsilon-3

新增真实供应商 token 门禁、live benchmark 准入和 Kappa/Upsilon 展示：

- `db/migrations/0029_postgresql_vendor_epsilon3_live_gate.sql`：新增 `vendor_live_gate_run`，并 seed `vendor_http` source/profile 的 env-only token 配置。
- `qdata.epsilon3_vendor_gate`：实现 safe blocked gate、真实 env 检查、可选 5/20/60 live benchmark、Pi readiness 复核写入、gate 查询和脱敏证据。
- `scripts/smoke_epsilon3_vendor_live_gate.py`：支持默认 blocked smoke，以及 `--allow-live --require-live` 的真实供应商 token 验收保护。
- `scripts/run_epsilon3_vendor_live_gate.py`：支持 gate 执行和 gate run 查询；查询模式不会误套执行默认日期、requested_by 或 trigger_mode。
- `qdata.kappa`：新增 `/admin/vendor-live-gates`、Epsilon-3 overview 指标和 console 表格数据。
- Upsilon：Vendor tab 展示 Vendor Live Gates，并在概览区展示 Vendor Gates/Gate Blocked/Gate Live/Gate Status。

实现要点：

- 真实供应商 `BASE_URL` 和 `TOKEN` 只来自 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`，数据库、Kappa API、CLI 和 Upsilon 均不保存或输出 token 明文。
- 未显式 `--allow-live` 时只写 status=`blocked`，error_message=`external_vendor_live_disabled`，不调用外部供应商。
- `--require-live` 在缺少真实供应商 env 时直接失败，避免把 blocked smoke 当作真实 vendor 联调成功。
- 如果未显式设置 `QDATA_VENDOR_AUTH_MODE`，Epsilon-3 会继承 DB vendor profile 的 `auth_mode`；当前 seeded `vendor_http` profile 为 bearer，因此缺 token 会被识别为阻塞。
- 当前本机 shell 未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`，因此本轮只完成 blocked 控制面和审计链路，未向真实供应商 endpoint 发起请求。

## 3.32 A 股真实供应商接入运营化 Zeta-3

新增真实供应商 onboarding run/result、预检编排、数据集级 gate 证据和 Kappa/Upsilon 展示：

- `db/migrations/0030_postgresql_vendor_zeta3_onboarding.sql`：新增 `vendor_onboarding_run` 和 `vendor_onboarding_dataset_result`，记录 run 级和 dataset 级 onboarding 审计。
- `qdata.zeta3_vendor_onboarding`：实现 env/profile/contract/rate limit/dataset preflight、默认 4 数据集、5/20/60 required windows、canary/gate 状态聚合、推荐角色和查询格式化。
- `scripts/smoke_zeta3_vendor_onboarding.py`：支持默认 blocked smoke，以及 `--allow-live --require-live` 的真实供应商 env 保护。
- `scripts/run_zeta3_vendor_onboarding.py`：支持 onboarding 执行、run 查询和 dataset result 查询。
- `qdata.kappa`：新增 `/admin/vendor-onboarding-runs`、`/admin/vendor-onboarding-results`、Zeta-3 overview 指标和 console 表格数据。
- Upsilon：Vendor tab 展示 Vendor Onboarding Runs、Vendor Onboarding Results 和 Vendor Live Gates。

实现要点：

- 真实供应商 `BASE_URL` 和 `TOKEN` 仍只来自 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`，数据库、Kappa API、CLI 和 Upsilon 均不保存或输出 token 明文。
- 未显式 `--allow-live --run-benchmarks` 时只写 status=`blocked` 的 onboarding/gate 审计，不调用外部供应商。
- `--require-live` 在缺少真实供应商 env 时直接失败，避免把 blocked smoke 当作真实 vendor 联调成功。
- 当前默认覆盖 `daily_bar,security_master,adjustment_factor,limit_price_daily`，其中未启用的 `security_master` 会明确记录 `dataset_not_enabled:security_master`。
- 非 daily_bar 数据集在真实 provider endpoint 未补齐前不会执行 live benchmark，也不得给出 primary_candidate。

## 3.33 A 股真实供应商 Live 接入闭环 Eta-3

新增真实供应商 live closure run/probe、endpoint schema 探针、profile 写入护栏和 Kappa/Upsilon 展示：

- `db/migrations/0031_postgresql_vendor_eta3_live_closure.sql`：新增 `vendor_live_closure_run` 和 `vendor_live_endpoint_probe`，记录 closure 级和 dataset endpoint probe 级审计。
- `qdata.eta3_vendor_live_closure`：实现 env/profile/contract/redistribution/rate limit/dataset preflight、endpoint path 探针、schema 字段检查、Zeta-3 onboarding 联动和推荐角色聚合。
- `scripts/smoke_eta3_vendor_live_closure.py`：支持默认 blocked smoke，以及 `--allow-live --require-live` 的真实供应商 env 保护。
- `scripts/run_eta3_vendor_live_closure.py`：支持 closure 执行、run 查询、probe 查询、profile 元数据安全写入和 live endpoint probe。
- `qdata.kappa`：新增 `/admin/vendor-live-closures`、`/admin/vendor-live-probes`、Eta-3 overview 指标和 console 表格数据。
- Upsilon：Vendor tab 展示 Vendor Live Closures、Vendor Live Probes、Vendor Onboarding Runs/Results 和 Vendor Live Gates。

实现要点：

- 真实供应商 `BASE_URL` 和 `TOKEN` 仍只来自 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`，数据库、Kappa API、CLI 和 Upsilon 均不保存或输出 token 明文。
- 未显式 `--allow-live` 时只写 status=`blocked` 的 closure/probe/onboarding/gate 审计，不调用外部供应商。
- endpoint probe 默认覆盖 `daily_bar,security_master,adjustment_factor,limit_price_daily`，记录 expected/observed/missing fields 和 auth/schema 状态。
- profile 写入必须显式 `--allow-profile-write`；未授权时只记录 blocked/next action，不改写 profile。
- `--require-live` 在缺少真实供应商 env、合同、再分发授权、rate limit、完整 dataset 或 endpoint schema 通过证据时直接失败，避免把 blocked smoke 当作真实 vendor 联调成功。
- 当前未启用的 `security_master` 会明确记录 `dataset_not_enabled:security_master`，不得被忽略或误判 primary_candidate。

## 3.34 A 股真实供应商 Live Pilot 试运行 Theta-3

新增真实供应商 live pilot run/result、dataset 级风险/签核聚合和 Kappa/Upsilon 展示：

- `db/migrations/0032_postgresql_vendor_theta3_live_pilot.sql`：新增 `vendor_live_pilot_run` 和 `vendor_live_pilot_dataset_result`，记录 pilot 批次和 dataset 级试运行结果。
- `qdata.theta3_vendor_live_pilot`：复用 Eta-3 closure/probe/onboarding/gate 证据，生成 pilot_scope、signoff_status、risk_level、recommendation、blocking_issues 和 next_actions。
- `scripts/smoke_theta3_vendor_live_pilot.py`：支持默认 blocked smoke，以及 `--allow-live --require-live` 的真实供应商 env 保护。
- `scripts/run_theta3_vendor_live_pilot.py`：支持 pilot 执行、run 查询和 dataset result 查询。
- `qdata.kappa`：新增 `/admin/vendor-live-pilots`、`/admin/vendor-live-pilot-results`、Theta-3 overview 指标和 console 表格数据。
- Upsilon：Vendor tab 展示 Vendor Live Pilots、Vendor Live Pilot Results、Vendor Live Closures/Probes、Vendor Onboarding Runs/Results 和 Vendor Live Gates。

实现要点：

- 真实供应商 `BASE_URL` 和 `TOKEN` 仍只来自 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`，数据库、Kappa API、CLI 和 Upsilon 均不保存或输出 token 明文。
- 默认 smoke 只写 blocked pilot/closure/probe/onboarding/gate 审计，不调用外部供应商。
- blocked/failed pilot 的 `signoff_status` 必须是 `not_ready`；只有 backup/primary_candidate 证据齐备后才进入 `pending_review`。
- `risk_level` 从 dataset 结果聚合：failed 为 critical，blocked 为 high，warning 为 medium，全部成功才为 low。
- 缺少合同、再分发授权、rate limit、完整 dataset、endpoint schema、onboarding 或 benchmark 证据时，不得给出 primary_candidate。

## 3.35 免费源联盟 Free Source Fabric Iota-3

新增免费源联盟 run/result、免费源候选目录、授权风险判断和 Kappa/Upsilon 展示：

- `db/migrations/0033_postgresql_free_source_iota3_fabric.sql`：新增 `free_source_fabric_run` 和 `free_source_fabric_dataset_result`，并登记 `csv/csv_mirror/akshare/baostock/tushare_free/cninfo_public/sse_public/szse_public/nbs_public` 候选源。
- `qdata.iota3_free_source_fabric`：按数据集评估多个免费源的覆盖率、一致性、授权状态、baseline_source、recommendation、risk_level、blocking_issues 和 next_actions。
- `scripts/smoke_iota3_free_source_fabric.py`：默认使用 `csv/csv_mirror` 做无外部副作用 smoke。
- `scripts/run_iota3_free_source_fabric.py`：支持 catalog、run、runs 和 results，支持外部免费源 `--allow-external`、真实外部要求 `--require-external` 和商业授权护栏 `--require-commercial-clearance`。
- `qdata.kappa`：新增 `/admin/free-source-fabric-runs`、`/admin/free-source-fabric-results`、Iota-3 overview 指标和 console 表格数据。
- Upsilon：新增 Free Sources tab，展示 Free Source Fabric Runs 和 Free Source Fabric Results。

实现要点：

- 默认 smoke 不调用外部免费网站，只用本地 fixture 验证 run/result、覆盖率和冲突率链路。
- 免费源原始行不写入审计表，只保存计数、阈值、状态、冲突摘要和脱敏 evidence。
- AKShare 等外部免费源必须显式 `--allow-external`；`--require-external` 可防止把本地 fixture 误当作真实免费源可用性。
- research_only/review_required 免费源默认只能作为 research/backup 证据；`--require-commercial-clearance` 打开时必须 blocked，不能替代商业授权主源。

## 3.36 外部免费源真实 Canary Iota-4

新增 Iota-4 AKShare 真实外部 canary，复用 Iota-3 fabric 审计和 Kappa/Upsilon 查询面：

- `qdata.iota4_external_free_source_canary`：包装 Iota-3 fabric，定义 live-only 和 compare-local 两种模式，并把“外部源执行成功”和“商业授权未通过”拆成两个独立状态。
- `scripts/smoke_iota4_external_free_source_canary.py`：默认跑 AKShare daily_bar/security_master/trading_calendar，写入 fabric run/result，并输出 canary status、fabric status、coverage、recommendation 和 commercial_clearance。
- `tests/test_iota4_external_free_source_canary.py`：覆盖 warning/research_only 仍可作为技术 canary ok、外部未执行失败、blocked fabric 失败、默认模式和 formatter。

实现要点：

- `iota4_external_free_source_canary=ok` 只代表真实外部免费源链路、字段解析、覆盖率和审计落库通过。
- AKShare 当前仍按 `research_only` 处理，fabric status 允许为 warning，`commercial_clearance=blocked` 必须保留。
- compare-local 模式证明 AKShare 能进入 csv/csv_mirror/akshare 多源 fabric，但本地 fixture 不作为真实行情基准。
- Iota-4 不新增迁移，不改写原始行情、供应商 pilot、账单或权限。

## 3.37 多免费源 Adapter Pool Iota-5

新增 BaoStock、TuShare free 和官方公开源 scaffold，并把多免费源 pool 固化为可审计 smoke：

- `qdata.sources.providers.baostock_provider`：新增 BaoStock explicit-symbol provider，支持 daily_bar/security_master/trading_calendar，并用 socket default timeout 防止 `www.baostock.com:10030` 不可达时挂住。
- `qdata.sources.providers.tushare_provider`：新增 TuShare Pro HTTP provider，支持 token guard、daily 行情映射和 trade_cal 映射。
- `qdata.sources.providers.official_public_provider`：新增 CNINFO/SSE/SZSE/NBS scaffold-only provider，返回结构化 contract-required 原因。
- `qdata.iota5_free_source_adapter_pool`：包装 Iota-3 fabric，输出 ok/degraded/failed、external_executed、commercial_clearance 和 degraded_reasons。
- `scripts/smoke_iota5_free_source_adapter_pool.py`：默认跑 akshare/baostock/tushare_free/sse_public/szse_public/cninfo_public，支持 `--require-ok` 严格两源成功门槛。
- `tests/test_free_source_providers.py` 和 `tests/test_iota5_free_source_adapter_pool.py`：覆盖 provider mapping、token guard、scaffold reason 和 pool 状态聚合。

实现要点：

- Iota-5 不新增迁移，继续复用 Iota-3 `free_source_fabric_run` 和 `free_source_fabric_dataset_result`。
- 当前本机 AKShare 真实成功，BaoStock socket 超时，TuShare 未配置 token，官方源仍是 scaffold，所以 Iota-5 正确输出 degraded。
- degraded 状态仍落库并可由 Kappa/Upsilon 查询；只有 `--require-ok` 才把两路外部源成功作为硬失败门槛。
- 免费源继续保持 research_only/review_required，不输出商业 primary_candidate。

## 3.38 免费源可靠性评分 Kappa-5

新增免费源可靠性快照、自动降级和 Kappa/Upsilon 查询面：

- `db/migrations/0034_postgresql_free_source_kappa5_reliability.sql`：新增 `free_source_reliability_snapshot`，按 source+dataset 记录 reliability_score、success_rate、coverage_rate、conflict_rate_bps、连续失败、授权状态、商业清晰度、降级原因和恢复动作。
- `qdata.kappa5_free_source_reliability`：从 Iota-3 fabric result 展开 source 级观察，计算 ready/watch/degraded/rejected/no_data 和 recommended_role。
- `scripts/run_kappa5_free_source_reliability.py`：支持 score 和 snapshots 查询。
- `scripts/smoke_kappa5_free_source_reliability.py`：输出 snapshot_count、状态分布和分数范围。
- Kappa 新增 `/admin/free-source-reliability`，overview 新增 reliability 计数和最新状态，Upsilon Free Sources 分组新增 Free Source Reliability 表。

实现要点：

- 免费源即使技术成功，也只进入 validator/backup/research_only/degraded/reject，不进入商业 production primary。
- BaoStock timeout、TuShare token 缺失、official public scaffold、冲突率过高或商业授权未清晰都会生成结构化降级原因。
- Kappa-5 只追加 snapshot，不改写 Iota-3/Iota-5 fabric、行情、真实供应商、账单或权限事实。

## 3.39 免费源恢复编排 Lambda-5

新增免费源恢复 run/action、worker task 和 Kappa/Upsilon 查询面：

- `db/migrations/0035_postgresql_free_source_lambda5_recovery.sql`：新增 `free_source_recovery_run` 和 `free_source_recovery_action`，并扩展 worker task、worker schedule tick 和 `alert_event.alert_type` 枚举。
- `qdata.lambda5_free_source_recovery`：把 Kappa-5 snapshot 转成 retry_canary、manual_review、observe 和 alert 动作。
- `qdata.lambda_worker`：新增 `free_source_recovery` task；dry-run 只预览，不写恢复表。
- `scripts/run_lambda5_free_source_recovery.py`：支持 recover、runs、actions 三类资源。
- `scripts/smoke_lambda5_free_source_recovery.py`：输出 status、snapshot_count、action_count、retry、alerts 和 manual_review。
- Kappa 新增 `/admin/free-source-recovery-runs`、`/admin/free-source-recovery-actions`，overview 新增 recovery 计数和最新状态，Upsilon Free Sources 分组新增恢复 run/action 表。

实现要点：

- rejected 或商业授权 blocked 的免费源进入 manual_review/high-critical 路径，并幂等写入 `free_source_recovery_required` 告警。
- degraded 且可重试的免费源生成 retry_canary、retry_after_minutes 和 next_retry_at。
- watch 免费源只 observe，不触发生产 fallback。
- Lambda-5 只追加恢复审计和告警，不改写 Kappa-5 snapshot、Iota-3/Iota-5 fabric、行情、真实供应商、账单或权限事实。

## 3.40 免费源恢复执行闭环 Mu-5

新增免费源恢复 execution、worker task、审批通知和 Kappa/Upsilon 查询面：

- `db/migrations/0036_postgresql_free_source_mu5_recovery_execution.sql`：新增 `free_source_recovery_execution`，扩展恢复 action 状态和 worker task 枚举，并初始化 `mu_free_source_recovery_execute_30m`。
- `qdata.mu5_free_source_recovery_executor`：执行 Lambda-5 待处理 action，`retry_canary` 接 Iota-5 canary，`manual_review` 接 Psi/Omega 审批和 Delta-2 企业微信通知。
- `qdata.lambda_worker` / `qdata.mu_scheduler`：新增 `free_source_recovery_execute` task 和 `mu5_*` 调度参数。
- `scripts/run_mu5_free_source_recovery_executor.py`：支持 execute 和 executions 查询。
- `scripts/smoke_mu5_free_source_recovery_executor.py`：默认执行 1 条 manual_review，企业微信外发关闭，验证 approval 和 blocked receipt 审计。
- Kappa 新增 `/admin/free-source-recovery-executions`，overview 新增 execution/recovered/failed/latest execution status，Upsilon Free Sources 分组新增恢复 execution 表。

实现要点：

- `retry_canary` 只有 Iota-5 pool status 为 ok 才回写 recovered；degraded/failed 一律回写 failed。
- `manual_review` 生成标准 `automation_action` 和 `automation_approval`，未显式 `--allow-wecom-external` 时企业微信只写 blocked receipt，不外发。
- 24 小时内已完成的同类 action 会写 suppressed execution，避免调度器重复骚扰。
- Mu-5 只追加执行审计和恢复 action 状态回写，不改写 Kappa-5 snapshot、Iota-3/Iota-5 fabric 原始结论、行情、真实供应商、账单或权限事实。

## 3.41 免费源恢复健康与 SLA Nu-5

新增免费源恢复 health snapshot、worker task、调度健康和 Kappa/Upsilon 查询面：

- `db/migrations/0037_postgresql_free_source_nu5_recovery_health.sql`：新增 `free_source_recovery_health_snapshot`，扩展 worker task 枚举，并初始化 `nu_free_source_recovery_health_15m`。
- `qdata.nu5_free_source_recovery_health`：读取 Mu-5 action/execution、Omega approval 和 worker schedule/run，计算审批 SLA、backlog、失败率、调度陈旧度、latest worker/schedule/execution status。
- `qdata.lambda_worker` / `qdata.mu_scheduler`：新增 `free_source_recovery_health` task 和 `nu5_*` 调度参数；critical 映射为 worker failed，warning 映射为 worker warning。
- `scripts/run_nu5_free_source_recovery_health.py`：支持 check 和 snapshots 查询。
- `scripts/smoke_nu5_free_source_recovery_health.py`：验证 health snapshot 可写可查，warning/critical 视为发现风险而不是 smoke 失败。
- Kappa 新增 `/admin/free-source-recovery-health`，overview 新增 latest health status、24h health count、overdue approval 和 backlog，Upsilon Free Sources 分组新增恢复 health 表。

实现要点：

- 审批超 SLA、backlog 超阈值、失败率过高、Mu-5 schedule 陈旧、worker failed 会进入 critical。
- 未清空 backlog、待审批、近期失败/抑制/review_requested 会进入 warning。
- 每次快照都生成 `health_issues` 和 `runbook_actions`，把审批、backlog、失败、调度问题转成可执行处置。
- Nu-5 只追加 health snapshot，不改写恢复 action、审批、行情、真实供应商、账单、权限或生产事实。

## 3.42 免费源授权准入矩阵 Xi-5

新增免费源 admission profile、source+dataset admission snapshot、worker task、Mu schedule 和 Kappa/Upsilon 查询面：

- `db/migrations/0038_postgresql_free_source_xi5_admission.sql`：新增 `free_source_admission_profile` 和 `free_source_admission_snapshot`，扩展 worker task 枚举，并初始化 `xi_free_source_admission_review_6h`。
- `qdata.xi5_free_source_admission`：读取源级授权档案、Kappa-5 reliability snapshot 和 Iota-3/Iota-5 fabric evidence，输出 `approved/conditional/review_required/blocked/no_data` 与 `admission_role`。
- `qdata.lambda_worker` / `qdata.mu_scheduler`：新增 `free_source_admission_review` task 和 `xi5_*` 调度参数。
- `scripts/run_xi5_free_source_admission.py`：支持 review、snapshots 和 profiles 查询。
- `scripts/smoke_xi5_free_source_admission.py`：验证准入档案和准入快照可写可查。
- Kappa 新增 `/admin/free-source-admission-profiles` 和 `/admin/free-source-admission`，overview 新增 admission 分布与 primary_candidate 计数，Upsilon Free Sources 分组新增准入矩阵和准入档案表。

实现要点：

- `primary_candidate` 必须同时满足合同 active、商用许可 clear、再分发 yes、条款 approved、限频/日配额齐全、可靠性分数/覆盖率/冲突率达标。
- 免费、research_only、review_required、local_smoke 或未确认转授权的源，只能作为研发、校验或备份证据，不能替代商业授权主源。
- blocked/review_required/no_data 是准入治理结论，worker 计为 warning，不等同于系统异常。
- Xi-5 只追加准入档案和快照，不改写行情、真实供应商、账单、权限或生产事实。

## 4. Mock 与 SQL 后端差异

| 项目 | Mock 后端 | SQL 后端 |
|---|---|---|
| 数据来源 | 内存样例数据 | PostgreSQL + ClickHouse |
| 是否需要依赖 | 不需要 | 需要 `psycopg`、`clickhouse-connect` |
| 行情数据 | 内存数组 | `qts.daily_bar` / `qts.minute_bar` |
| 主数据 | 内存数组 | `qmeta.security_master` |
| PIT 财务 | 内存数组 | `qpit.financial_metric_pit` + `qpit.financial_statement_pit` |
| 因子数据 | 内存数组 | `qmeta.factor_definition` + `qts.factor_value_daily` |
| 数据质量 | 内存数组 | `qmeta.data_quality_check_result` |
| 真实延迟/权限 | API token 可模拟 | REST 层支持 token、配额和请求审计 |

## 5. 已验证内容

本地 SDK 测试使用 fake PostgreSQL/ClickHouse 客户端做接口级验证。

验证通过：

- mock 后端原有 5 个测试。
- SQL 后端 4 个测试。
- 数据导入、source 同步和 pipeline 调度测试。
- 单元测试总数 206 个。
- SDK 语法编译。
- quickstart 示例。
- Docker PostgreSQL + ClickHouse 真实链路 smoke。
- CSV provider 双票真实入库。
- AkShare provider 双票真实入库。
- CSV pipeline 成功运行、重复运行 skip。
- AkShare pipeline 成功运行。
- 调度表 job/run/watermark 真实落库。
- CSV 全市场样例运行为 `partial_success`，记录 expected=3、rows=2、missing=`300750.SZ`。
- CSV 非交易日 `2024-01-05` 自动 `skipped`。
- AkShare 全市场小样本运行为 `success`，`--max-symbols 2`、`batches=2`、完整率 1.0。
- 全市场生产 smoke 查回 `000001.SZ` 和 `000002.SZ` 价格。
- CSV/AkShare 同日 smoke 的 health 记录按 job/source 隔离。
- CSV partial_success 自动进入 repair queue，repair queue 重跑仍可保留 open 状态。
- 生产日报和查询压测脚本可在真实数据库上运行。
- 复权/约束独立同步、可交易股票池、价格矩阵导出和分钟线 Alpha 在本地 CSV 链路通过。
- Epsilon 单元测试覆盖多源冲突、fallback、REST token 鉴权和 CSV matrix。
- `0007` migration 已在 Docker PostgreSQL 真实应用。
- 多源融合真实写入 2 条 `data_conflict_daily` 和 1 条 `multi_source_quality_daily`。
- SQL REST API smoke 覆盖 `/health`、`/price`、`/constraints`、`/tradable-universe`、`/matrix`。
- `api_request_audit` 记录了 2630 条真实 REST 请求。
- Zeta 单元测试覆盖 pipeline/quality/API 汇总和 SLA 告警判定。
- `0008` migration 已在 Docker PostgreSQL 真实应用。
- 运维看板真实输出 pipeline=4、conflicts=2、open_repairs=1，并写入 1 条 snapshot。
- SLA 检查真实写入 1 条 `conflict_rate_above_sla` open alert。
- API 审计报表真实输出 requests=2630、failed=4 和慢接口列表；4 条失败均为无 Bearer token 的浏览器/curl 验证访问。
- Eta 单元测试覆盖 `vendor_http` fixture/HTTP/auth/retry 和 provider benchmark/评分。
- `0009` migration 已在 Docker PostgreSQL 真实应用。
- `vendor_http` profile 真实写入，`profile_id=1`，状态为 testing。
- `vendor_http` fixture benchmark 真实写库，coverage=1、conflict_rate=0.16666667、rating=A。
- AkShare 真实开源第二源 benchmark 使用 `.venv312` 跑通，coverage=1、conflict_rate=1、rating=C。
- `provider_benchmark_run` 当前真实库累计 4 条。
- `data_conflict_daily` 对 `2024-01-04` 记录了 csv-vendor_http 2 个冲突、csv-akshare 12 个冲突、csv-csv_mirror 2 个冲突。
- 供应商评分榜可输出 `vendor_http rating=A` 和 `akshare rating=C`。
- Theta 单元测试覆盖字段映射、0 值 fallback、分片 suite、provider SLA 和上线决策。
- `0010` migration 已在 Docker PostgreSQL 真实应用。
- `vendor_field_mapping` 真实写入 28 条默认日线映射。
- `vendor_http` profile 已真实切换为 active。
- 分片 benchmark suite 真实写库，`shards=2`、`benchmarks=2`、coverage=1、conflict_rate=0.16666667、rating=A。
- Provider SLA 真实写入 1 条 `vendor_conflict_rate_above_sla` open alert。
- 上线决策报告真实写入 2 条，`vendor_http=approve_backup`、`akshare=watch`。
- Iota 单元测试覆盖 ACL 兼容快路径、severity/access 级别、stdout/webhook 通知和用量报表格式。
- `0011` migration 已在 Docker PostgreSQL 真实应用。
- Iota 安全初始化真实写入 demo/quant-research/research-bot，DB token 绑定 3 个 dataset 权限。
- 通知通道 `stdout-high` 真实注册，2 条 open/high 告警投递为 sent。
- DB token REST smoke 通过 `/health`、`/price`、`/constraints`、`/tradable-universe`、`/matrix`。
- `api_usage_daily` 对 `quant-research` 汇总出 14 行、31 次请求、成本单位 31.007600，覆盖数据 API、Kappa 管理 API 和 worker-runs API。
- `vendor_benchmark_schedule` 真实写入 1 条，`last_suite_id=2`。
- `vendor_http` 字段映射真实覆盖 `daily_bar=28`、`adjustment_factor=10`、`limit_price_daily=12`、`security_master=11`。
- Kappa 单元测试覆盖 admin path 注册、分页参数校验、报表格式、Theta-3 vendor pilot 报表、HTML 转义、admin scope 鉴权和 console HTML。
- `report_kappa_admin.py --resource overview` 真实输出 active_tenant_count=1、open_alert_count=2、active_vendor_schedule_count=1、active_worker_schedule_count=3。
- `report_kappa_admin.py --resource usage-daily --trade-date 2026-07-24 --project-code quant-research` 真实输出 14 行项目用量。
- `report_kappa_admin.py --resource tokens` 真实输出 token_hash_tail 和 scopes，不输出完整 token_hash。
- Kappa Admin API smoke 通过 overview、tenants、projects、tokens、dataset_access、notification_deliveries、vendor_schedules、worker、deployment、Xi、Omicron、Pi、Rho、Tau、Phi、Chi、Psi、Omega、Upsilon、usage_daily 和 console。
- Kappa smoke 后原有 SQL REST smoke 仍通过 health/price/constraints/tradable/matrix。
- Lambda 单元测试覆盖 task 选择、去重、状态聚合、异常捕获和报表输出。
- `0012` migration 已在 Docker PostgreSQL 真实应用。
- Lambda dry-run worker 真实写入 1 条 skipped run，预览 usage 分组和 alert/channel 组合。
- Lambda 完整 worker 真实写入 1 条 warning run：usage_rollup success、alert_dispatch success、vendor schedule warning、failed_count=0。
- Lambda 最新 usage_rollup worker 真实写入 success run，并可被 Mu 以 scheduled trigger 复用。
- Kappa `/admin/worker-runs` 真实输出 6 条 worker run，最新 status=success。
- Kappa Admin API smoke 覆盖 `worker_runs=ok`，console HTML 展示 Worker Runs。
- Mu 单元测试覆盖 schedule/task 去重、日期参数归并、next_run_at 计算和报表输出。
- `0013` migration 已在 Docker PostgreSQL 真实应用。
- Mu 默认 schedule 真实初始化 3 条 active 配置。
- `smoke_mu_scheduler.py` 强制 `mu_usage_rollup_5m` 到期并真实写入 success tick，触发 scheduled worker_run_id=4。
- `run_mu_scheduler.py --schedule-code mu_usage_rollup_5m --once --force-due` 真实写入 success tick_id=2，并触发 worker_run_id=5。
- Docker profile `mu-scheduler` 容器内真实连接 Compose Postgres，执行 `mu_alert_dispatch_1m` 写入 tick_id=3 和 worker_run_id=6。
- Kappa `/admin/worker-schedules` 真实输出 3 条 schedule，`/admin/worker-schedule-ticks` 真实输出 3 条 tick，`/admin/worker-locks` 当前为 0 条未释放锁。
- `0014` migration 已在 Docker PostgreSQL 真实应用。
- Nu 健康检查真实写入 `snapshot_id=1`、`release_id=1`，6 项检查全部 success。
- Kappa Admin API smoke 覆盖 deployment release、health、check 和 event 端点。
- Kappa overview 最新输出 `latest_deployment_health_status=success`、`latest_deployment_release_status=healthy`、`deployment_24h_failed_count=0`。
- `docker compose --profile app --profile scheduler config --services` 可解析出 postgres/clickhouse/qdata-api/mu-scheduler。
- Docker app/scheduler profile 已配置可覆盖的 `PIP_INDEX_URL`，默认走清华 PyPI 镜像，解决当前网络下容器直连 PyPI 官方源 SSL EOF 导致 `qdata-api` 启动失败的问题。
- `0015` migration 已在 Docker PostgreSQL 真实应用。
- Xi 默认商业目录真实写入：`a_share_daily_core` 覆盖 4 个 dataset 和 4 个 API。
- Xi 价格计划真实写入：`quant_starter_monthly`，规则 `cost_unit * 0.01`。
- Xi 预算快照真实写入：`usage_amount=0.16002800`、`budget_amount=0.15000000`、`usage_pct=1.06685333`、`status=exceeded`。
- Xi 预算告警真实写入：当前 `budget_exceeded` 为 open，旧 warning/blocked 为 resolved。
- Xi hard limit 决策真实验证：hard limit 打开时 `check_budget_allowed(... api_name='price')` 返回 allowed=False、status=blocked。
- Kappa Admin API smoke 覆盖 Xi 产品、价格、订阅、预算和预算告警端点。
- 最新 Mu usage rollup 对 `2026-07-26` 写入 success worker_run_id=9，overview 7 日请求量更新为 117。
- `0016` migration 已在 Docker PostgreSQL 真实应用；重跑迁移时同步修复了 `0010` 告警类型约束对 Xi 预算告警的幂等兼容。
- Omicron 真实生成 2026-07 账单 1 张、明细 4 条、事件 2 条。
- 账单 `inv-demo-quant-research-a_share_daily_core-20260701-20260731` 总额 `0.16002800 CNY`，与 Xi 预算用量金额一致。
- 回款状态真实更新为 `paid`，`paid_amount=0.16002800`、`outstanding_amount=0.00000000`。
- Kappa overview 最新输出 `invoice_month_count=2`、`invoice_month_total_amount=100.16002800`、`invoice_month_paid_amount=100.16002800`、`invoice_month_outstanding_amount=0E-8`。
- Kappa Admin API smoke 覆盖 Omicron 账单、明细、事件和收入汇总端点。
- `0017` migration 已在 Docker PostgreSQL 真实应用。
- Pi fixture 供应商 5/20/60 窗口 suite 均已真实写库，suite_id 分别为 5、6、4，三组均为 warning。
- Pi readiness 真实写入 `pi-readiness-vendor_http-daily_bar-20260726-5-20-60d`，status=`watch`、recommendation=`approve_backup`、recommended_role=`backup`、suite_count=3。
- Pi blocking issues 明确记录 5/20/60 三个窗口 `conflict_rate=0.16666667` 高于主源阈值 `0.005`。
- Kappa overview 最新输出 `vendor_readiness_ready_count=0`、`vendor_readiness_watch_count=1`、`vendor_readiness_rejected_count=0`、`latest_vendor_readiness_status=watch`。
- Kappa Admin API smoke 覆盖 Pi readiness 总结和窗口明细端点，`vendor_readiness=ok rows=1`、`vendor_readiness_windows=ok rows=3`。
- `0018` migration 已在 Docker PostgreSQL 真实应用。
- Rho 真实生成 2026-07 经营快照：对账 1 条、对账明细 4 条、AR aging 1 条、客户健康 1 条。
- Rho 对账 `rho-recon-demo-quant-research-a_share_daily_core-20260701-20260731-20260726` 结论为 matched，invoice_total=`0.16002800`、recomputed_total=`0.16002800`、amount_delta=`0E-8`。
- Rho 行级对账 4 条均为 matched，覆盖 `constraints`、`matrix`、`price` 和 `tradable-universe`。
- Rho AR aging 结论为 current，outstanding_amount=`0E-8`、overdue_invoice_count=`0`。
- Rho customer health 结论为 active/healthy，health_score=`100`、request_count_30d=`16`。
- Kappa overview 最新输出 `latest_reconciliation_status=matched`、`latest_ar_outstanding_amount=0E-8`、`customer_health_active_count=1`、`customer_health_risk_count=0`。
- Kappa Admin API smoke 覆盖 Rho 对账、对账明细、AR aging 和客户健康端点，`revenue_reconciliation=ok rows=1`、`revenue_reconciliation_lines=ok rows=4`、`ar_aging=ok rows=1`、`customer_health=ok rows=1`。
- `0019` migration 已在 Docker PostgreSQL 真实应用。
- Sigma 真实采集写入运行日志 1 条、运行指标 8 条、运行日报 1 条、容量告警 1 条。
- Sigma 容量告警 `sigma-capacity-local-api-api-request-count-7d` 当前 metric_value=`271`、threshold=`200`、severity=`medium`、status=`open`。
- Sigma 日报 `sigma-runtime-local-20260726` 当前 status=`warning`、api_request_count=`213`、api_failed_count=`0`、open_capacity_alert_count=`1`。
- Kappa overview 最新输出 `runtime_24h_error_log_count=0`、`runtime_metric_warning_count=1`、`runtime_metric_critical_count=0`、`open_capacity_alert_count=1`、`latest_runtime_report_status=warning`。
- Kappa Admin API smoke 覆盖 Sigma 运行日志、指标、日报和容量告警端点，`runtime_logs=ok rows=1`、`runtime_metrics=ok rows=8`、`runtime_daily_reports=ok rows=1`、`capacity_alerts=ok rows=1`。
- `0020` migration 已在 Docker PostgreSQL 真实应用；重跑迁移时同步修复了 `0010`/`0015` 告警类型约束对 Sigma runtime alert 的幂等兼容。
- Tau demo 真实生成 `inv-demo-quant-research-a_share_daily_core-tau-20260727`，导入批次 `tau-demo-payments-20260727`。
- Tau 自动匹配真实写入 1 条 `payment_invoice_match`，match_type=`auto_exact`、matched_amount=`100.00000000`、invoice_status=`paid`。
- Tau payment batch 当前 status=`matched`、transaction_count=`1`、matched_count=`1`、unmatched_count=`0`。
- Tau revenue ledger 真实输出 payment_received 和 payment_matched 两条分录。
- Kappa overview 最新输出 `payment_month_received_amount=100.00000000`、`payment_month_matched_amount=100.00000000`、`unmatched_payment_count=0`、`latest_payment_batch_status=matched`。
- Kappa Admin API smoke 覆盖 Tau 回款批次、付款流水、匹配、ledger 和 FX rate 端点，`payment_batches=ok rows=1`、`payments=ok rows=1`、`payment_matches=ok rows=1`、`revenue_ledger=ok rows=2`、`fx_rates=ok rows=0`。
- `0021` migration 已在 Docker PostgreSQL 真实应用，5 张 Phi 策略表和 5 条默认策略可用。
- Phi 真实策略运行 `phi-local-20260727` 写入 status=`warning`、highest=`high`、signals=7、decisions=5、escalations=2。
- Phi 决策当前包括：data_quality `hold_production/block`、vendor `keep_backup/watch`、runtime `monitor/review`、commercial `open_review/escalate`、payment `monitor/allow`。
- Kappa overview 最新输出 `latest_strategy_status=warning`、`latest_strategy_severity=high`、`strategy_24h_action_decision_count=3`、`open_strategy_escalation_count=2`。
- Kappa Admin API smoke 覆盖 Phi strategy runs/signals/decisions/escalations 端点，`strategy_runs=ok rows=1`、`strategy_signals=ok rows=7`、`strategy_decisions=ok rows=5`、`strategy_escalations=ok rows=2`。
- `0022` migration 已在 Docker PostgreSQL 真实应用，Chi 权限审计、项目治理快照和治理动作 3 张表可用。
- Iota ACL 已修正为 principal > project > tenant 严格匹配，主体级权限不会被其他主体通过同租户 fallback 误用。
- Chi 权限评估真实写入 allow/deny 审计：`daily_bar/price` 允许，`financial_statement/fundamentals` 拒绝。
- Chi 项目治理快照 `chi-gov-demo-quant-research-20260727` 当前 status=`critical`、risk_score=`49.0`、request_count_7d=`39`、denied_access_7d_count=`1`、budget_status=`exceeded`、budget_usage_pct=`1.06685333`。
- Chi 治理动作真实生成 `chi-action-demo-quant-research-20260727-review_budget`，action_type=`review_budget`、severity=`high`、status=`open`、owner=`platform-governance`。
- Kappa overview 最新输出 `access_denied_24h_count=1`、`project_governance_warning_count=0`、`project_governance_critical_count=1`、`open_governance_action_count=1`。
- Kappa Admin API smoke 覆盖 Chi access decisions/project governance/governance actions 端点。
- `0023` migration 已在 Docker PostgreSQL 真实应用，Psi 自动化 run/action 2 张表可用。
- Psi dry-run `psi-local-20260727-dry_run` 生成 5 个动作：repair_data_quality、degrade_vendor、freeze_budget、notify_owner 和 escalate_commercial，executed=0、skipped=5。
- Psi execute `psi-local-20260727-execute-phi-safe` 成功执行 2 个中风险动作，2 个高风险动作进入 approval_required。
- Psi execute `psi-local-20260727-execute-chi-guard` 将 Chi freeze_budget 高风险动作拦截为 approval_required。
- Kappa overview 最新输出 `automation_24h_run_count=4`、`automation_24h_action_count=11`、`automation_approval_required_count=2`、`automation_24h_failed_count=0`、`latest_automation_status=success`。
- Kappa Admin API smoke 覆盖 Psi automation runs/actions 端点。
- `0024` migration 已在 Docker PostgreSQL 真实应用，Omega approval/executor/attempt/rollback 4 张表和 action 控制字段可用。
- Omega 为 3 个高风险 Psi 动作生成 approval，其中 `degrade_vendor` 已 approved 并通过 `omega-noop-degrade-vendor` 成功记录执行。
- Omega retry smoke `omega-smoke-retry-action` 通过 force_fail noop executor 进入 `retry_scheduled`，error_message=`forced executor failure`。
- Omega rollback smoke 对已执行 degrade_vendor 动作完成 noop rollback，rollback status=`success`。
- Kappa overview 最新输出 `automation_pending_approval_count=2`、`automation_retry_scheduled_count=0`、`automation_rollback_required_count=0`、`latest_automation_attempt_status=success`。
- Kappa Admin API smoke 覆盖 Omega automation approvals/executors/attempts/rollbacks 端点。
- `0025` migration 已在 Docker PostgreSQL 真实应用，Alpha-2 allowlist/secret ref 和 executor 安全字段可用。
- Alpha-2 registry 当前 automation_executors=`14`、automation_allowlists=`2`、automation_secrets=`1`。
- Alpha-2 script sandbox 通过 `alpha2-script-notify-owner` 真实执行仓库脚本，returncode=`0`、sandbox_dispatch=`true`、external_side_effect=`false`。
- Alpha-2 webhook sandbox 通过 `alpha2-webhook-notify-owner` 真实 POST 到本地 webhook，status_code=`200`、signed=`true`、sandbox_dispatch=`true`。
- Kappa overview 最新输出 `automation_active_sandbox_executor_count=2`、`automation_active_allowlist_count=2`、`automation_active_secret_ref_count=1`。
- Kappa Admin API smoke 覆盖 Alpha-2 automation allowlists/secrets 端点，`automation_allowlists=ok rows=2`、`automation_secrets=ok rows=1`。
- `0026` migration 已在 Docker PostgreSQL 真实应用，Beta-2 channel/dispatch/runbook 元数据可用。
- Beta-2 registry 当前 automation_channels=`2`、automation_runbooks=`2`。
- Beta-2 approval webhook dispatch 真实 POST 成功，status=`acknowledged`、status_code=`200`、signed=`true`。
- Beta-2 重复触发写入 suppressed，blocked_by=`duplicate_window`，未重复调用外部 webhook。
- Beta-2 dead-letter smoke 写入 dead_letter 后按 `beta2-webhook-timeout` runbook 恢复为 recovered。
- `0027` migration 已在 Docker PostgreSQL 真实应用，Gamma-2 profile/validation/rotation 元数据可用。
- Gamma-2 registry 当前 automation_channel_profiles=`3`，覆盖 local feishu/wecom/email 三类 dry-run provider profile。
- Gamma-2 smoke 输出 `gamma2_smoke=ok profiles=3 ready_profiles=1 validations=6 rotations=2 current_validation=success rotation=applied rollback=rolled_back post_rollback_validation=success`。
- Gamma-2 secret rotation 通过 `gamma2-local-hmac-current -> gamma2-local-hmac-next` 候选签名验证，apply 后按同一 rotation 记录 rollback，affected_channel_count=`1`。
- `0028` migration 已在 Docker PostgreSQL 真实应用，Delta-2 live receipt 审计和企业微信 env-only endpoint 引用可用。
- Delta-2 registry 当前新增 `delta2-wecom-webhook-url` secret ref、`delta2-wecom-live-webhook` channel、`delta2-wecom-live-profile` profile 和 `delta2-wecom-live` runbook。
- Delta-2 safe smoke 输出 `delta2_wecom_smoke=ok mode=blocked status=blocked ... provider_errcode=None`，当前已写入 2 条 blocked receipt。
- Delta-2 require-live 保护在当前未配置 `QDATA_DELTA2_WECOM_WEBHOOK_URL` 时正确失败：`delta2_wecom_smoke=failed reason=missing_env env=QDATA_DELTA2_WECOM_WEBHOOK_URL`，本轮没有真实企业微信外发。
- Delta-2 receipt 查询真实输出 2 条 `delta2-wecom-live-profile` blocked receipt，error_message=`external_live_dispatch_disabled`，evidence 中 `external_side_effect=false`。
- `0029` migration 已在 Docker PostgreSQL 真实应用，Epsilon-3 `vendor_live_gate_run` 审计表、索引和 `vendor_http` env-only profile 可用。
- Epsilon-3 safe smoke 输出 `epsilon3_vendor_live_gate_smoke=ok mode=blocked status=blocked ... live_base_url_present=False live_token_present=False`，最新 blocked gate 已落库。
- Epsilon-3 require-live 保护在当前未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时正确失败：`epsilon3_vendor_live_gate_smoke=failed reason=missing_vendor_live_env`，本轮没有真实供应商外部请求。
- Epsilon-3 gate 查询可输出最新 blocked gate；Theta-3 编排后当前真实库 `admin.vendor-live-gates rows=26`，最新 gate 仍为 `live_base_url_present=False`、`live_token_present=False`、`error_message=external_vendor_live_disabled`。
- `0030` migration 已在 Docker PostgreSQL 真实应用，Zeta-3 `vendor_onboarding_run` 和 `vendor_onboarding_dataset_result` 审计表、索引和 rollback 脚本可用。
- Zeta-3 safe smoke 输出 `zeta3_vendor_onboarding_smoke=ok mode=blocked status=blocked run_code=zeta3-onboarding-vendor_http-blocked-5d289f7340 dataset_count=4 gate_count=4 live_base_url_present=False live_token_present=False`；Theta-3 编排后当前 6 条 onboarding run 和 24 条 dataset result 已落库。
- Zeta-3 require-live 保护在当前未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时正确失败：`zeta3_vendor_onboarding_smoke=failed reason=missing_vendor_live_env`，本轮没有真实供应商外部请求。
- Zeta-3 onboarding runs 查询真实输出 blocked run，recommendation=`research_only`，error_message 包含 `external_vendor_live_disabled`、缺少 env 和 `dataset_not_enabled:security_master`。
- Zeta-3 onboarding results 查询真实输出 24 条 blocked dataset result，覆盖 `daily_bar`、`security_master`、`adjustment_factor` 和 `limit_price_daily` 的多轮审计。
- `0031` migration 已在 Docker PostgreSQL 真实应用，Eta-3 `vendor_live_closure_run` 和 `vendor_live_endpoint_probe` 审计表、索引和 rollback 脚本可用。
- Eta-3 safe smoke 输出 `eta3_vendor_live_closure_smoke=ok mode=blocked status=blocked closure_code=eta3-live-closure-vendor_http-blocked-b7fcf54a19 probe_count=4 onboarding_status=blocked live_base_url_present=False live_token_present=False`；Theta-3 编排后当前 4 条 closure 和 16 条 endpoint probe 已落库。
- Eta-3 require-live 保护在当前未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时正确失败：`eta3_vendor_live_closure_smoke=failed reason=missing_vendor_live_env`，本轮没有真实供应商外部请求。
- Eta-3 closure 查询真实输出 4 条 blocked closure，recommendation=`research_only`，error_message 包含 `external_vendor_live_disabled`、缺少 env、合同/授权和 `dataset_not_enabled:security_master`。
- Eta-3 probe 查询真实输出 16 条 blocked endpoint probe，最新 `daily_bar` probe 记录 missing_fields=`['close', 'symbol', 'trade_date']`，`security_master` 记录 `dataset_not_enabled:security_master`。
- `0032` migration 已在 Docker PostgreSQL 真实应用，Theta-3 `vendor_live_pilot_run` 和 `vendor_live_pilot_dataset_result` 审计表、索引和 rollback 脚本可用。
- Theta-3 safe smoke 输出 `theta3_vendor_live_pilot_smoke=ok mode=blocked status=blocked pilot_code=theta3-live-pilot-vendor_http-blocked-b7f52ed98c closure_status=blocked dataset_count=4 signoff_status=not_ready risk_level=high live_base_url_present=False live_token_present=False`，当前 2 条 pilot 和 8 条 dataset result 已落库。
- Theta-3 require-live 保护在当前未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时正确失败：`theta3_vendor_live_pilot_smoke=failed reason=missing_vendor_live_env`，本轮没有真实供应商外部请求。
- Theta-3 pilot 查询真实输出 2 条 blocked pilot，signoff_status=`not_ready`，risk_level=`high`，recommendation=`research_only`。
- Theta-3 result 查询真实输出 8 条 blocked dataset result，覆盖 `daily_bar`、`security_master`、`adjustment_factor` 和 `limit_price_daily` 的 closure/probe/gate/schema 证据。
- `0033` migration 已在 Docker PostgreSQL 真实应用，Iota-3 `free_source_fabric_run` 和 `free_source_fabric_dataset_result` 审计表、索引、免费源候选登记和 rollback 脚本可用。
- Iota-3 catalog 输出 9 个候选源：`csv`、`csv_mirror`、`akshare`、`baostock`、`tushare_free`、`cninfo_public`、`sse_public`、`szse_public`、`nbs_public`。
- Iota-3 safe smoke 输出 `iota3_free_source_fabric_smoke=ok status=success fabric_code=iota3-free-source-fabric-success-b7d1afb4d6 dataset_count=5 source_count=2 usable_source_count=2 coverage_rate=1.000000 conflict_rate_bps=0.000000 allow_external=False require_external=False`，没有外部免费源请求。
- Iota-3 conflict smoke 用 `--csv-mirror-close-offset-bps 10` 生成 warning run，daily_bar result 的 `consistency_status=warning`、`conflict_rate_bps=10.000000`。
- Iota-3 require-external 护栏在未允许外部免费源成功执行时正确失败：`iota3_free_source_fabric_smoke=failed reason=external_free_source_required`。
- Iota-3/Iota-4/Iota-5 Kappa 查询当前输出 `free_source_24h_fabric_count=10`，最新 fabric status 为 failed，failed 来自 Iota-5 adapter pool 严格两源目标未满足。
- Iota-4 live-only AKShare canary 输出 `iota4_external_free_source_canary=ok mode=live-only fabric_status=warning ... external_executed=1 coverage_rate=1.000000 recommendation=research_only commercial_clearance=blocked`。
- Iota-4 compare-local AKShare canary 输出 `iota4_external_free_source_canary=ok mode=compare-local fabric_status=warning ... source_count=3 external_executed=1 coverage_rate=1.000000 recommendation=research_only commercial_clearance=blocked`。
- Iota-4 Kappa 查询当前输出 `admin.free-source-fabric-runs rows=3` 和 AKShare result `rows=9`，覆盖 daily_bar/security_master/trading_calendar。
- Iota-5 adapter pool smoke 输出 `iota5_free_source_adapter_pool=degraded ... external_executed=1 ... degraded_reasons=fabric_status_degraded:failed,external_successful_sources_below_target:1/2,official_public_scaffold_pending,tushare_token_missing,baostock_source_failed`。
- Iota-5 Kappa 查询当前输出 `admin.free-source-fabric-runs rows=3`，baostock/tushare_free result 查询各输出 9 条 dataset result。
- Kappa-5 migration 0034 已在本机 PostgreSQL 应用成功，`free_source_reliability_snapshot` 可写入和查询。
- Kappa-5 reliability smoke 输出 `kappa5_free_source_reliability_smoke=ok snapshot_count=28 ready=0 watch=11 degraded=2 rejected=15 no_data=0 min_score=0.0000 max_score=72.0000`。
- Lambda-5 migration 0035 已在本机 PostgreSQL 应用成功，`free_source_recovery_run`/`free_source_recovery_action` 可写入和查询。
- Lambda-5 recovery smoke 输出 `lambda5_free_source_recovery_smoke=ok status=warning recovery_code=lambda5-free-source-recovery-2026-07-28-4982cec0f2 snapshot_count=28 action_count=28 retry=0 alerts=17 manual_review=17`。
- Lambda worker dry-run 输出 `task name=free_source_recovery status=skipped processed=28 warning=28`，恢复 run 总数保持不变。
- Mu-5 migration 0036 已在本机 PostgreSQL 连续应用两次，manual-review smoke 输出 `mu5_free_source_recovery_smoke=ok status=warning candidates=1 executions=1 recovered=0 failed=0 suppressed=0 review_requested=1 blocked=0`，retry-canary smoke 输出 `status=success recovered=1 iota5_pool_status=ok`。
- Nu-5 migration 0037 已在本机 PostgreSQL 连续应用两次，`free_source_recovery_health_snapshot` 表存在，`nu_free_source_recovery_health_15m` schedule_count=`1`。
- Nu-5 health smoke 输出 `nu5_free_source_recovery_health_smoke=ok status=warning snapshot_code=nu5-recovery-health-2cebd0d243 backlog=34 approvals=2 overdue=0 failures=0 stale_schedule=0`。
- Nu-5 worker dry-run 输出 `task name=free_source_recovery_health status=skipped processed=1 success=0 warning=1 failed=0`，非 dry-run worker 输出 `status=warning processed=1 warning=1`。
- Nu-5 Mu schedule 强制触发输出 `tick schedule=nu_free_source_recovery_health_15m task=free_source_recovery_health status=warning lock_acquired=True worker_run_id=14`。
- Xi-5 migration 0038 已在本机 PostgreSQL 应用成功，默认写入 9 条 admission profile 和 `xi_free_source_admission_review_6h` schedule。
- Xi-5 smoke 输出 `xi5_free_source_admission_smoke=ok snapshots=38 approved=0 conditional=0 review_required=11 blocked=17 no_data=10 primary_candidate=0`。
- Xi-5 worker dry-run 输出 `task name=free_source_admission_review status=skipped processed=38 warning=38`，非 dry-run worker 输出 `status=warning processed=38 warning=38`。
- Xi-5 Mu schedule 强制触发输出 `tick schedule=xi_free_source_admission_review_6h task=free_source_admission_review status=warning lock_acquired=True worker_run_id=17`。
- Kappa Xi-5 查询当前输出 `admin.free-source-admission rows=5`，overview 显示 `free_source_24h_admission_count=114`、`free_source_24h_admission_review_required_count=33`、`free_source_primary_candidate_count=0`。
- Omicron-5 migration 0039 已在本机 PostgreSQL 连续应用两次，`vendor_contract_profile`、`vendor_contract_dataset_entitlement`、`vendor_procurement_readiness_snapshot` 表存在并可重复 seed。
- Omicron-5 procurement smoke 输出 `omicron5_vendor_contract_smoke=ok snapshots=7 ready=0 conditional=0 review_required=3 blocked=4 no_contract=0 primary_candidate=0`。
- Omicron-5 worker dry-run 输出 `task name=vendor_contract_readiness_review status=skipped processed=7 warning=7`，非 dry-run worker 输出 `status=warning processed=7 warning=7 failed=0`。
- Omicron-5 Mu schedule 强制触发输出 `tick schedule=omicron5_vendor_contract_readiness_6h task=vendor_contract_readiness_review status=warning lock_acquired=True worker_run_id=20`。
- Kappa Omicron-5 查询当前输出 `admin.vendor-procurement-readiness rows=2`，合同 profile 返回 1 条 `vendor_http` draft/review_required 模板，dataset entitlement 返回 7 条核心授权模板，`primary_candidate=0`。
- Pi-5 migration 0040 已纳入增量迁移、Docker init、总表 DDL 和 rollback，并已在本机 PostgreSQL 连续应用两次；新增 `vendor_primary_promotion_run`、`vendor_primary_promotion_dataset_result` 和 `pi5_vendor_primary_promotion_6h` schedule。
- Pi-5 promotion smoke 输出 `pi5_vendor_primary_promotion_smoke=ok status=blocked datasets=7 approved=0 pending=0 blocked=7 applied=0 routing_allowed=False routing_applied=False`。
- Pi-5 worker dry-run 输出 `task name=vendor_primary_promotion_review status=skipped processed=7 warning=7`，非 dry-run worker 输出 `status=warning processed=7 warning=7 failed=0`。
- Pi-5 Mu schedule 强制触发输出 `tick schedule=pi5_vendor_primary_promotion_6h task=vendor_primary_promotion_review status=warning lock_acquired=True worker_run_id=23`。
- Pi-5 Kappa 查询当前输出 `admin.vendor-primary-promotions rows=3` 和 `admin.vendor-primary-promotion-results rows=20`，latest run 均为 `status=blocked apply_mode=review_only dataset_count=7 blocked_dataset_count=7`。
- Pi-5 promotion guard 默认 review-only，要求 Omicron-5 `ready/primary_candidate`、Pi 5/20/60 `approve_primary`、Theta-3 canary/full-market 和签批证据齐全后才允许 `approved_for_primary`；当前模板授权环境保持 blocked，不改写 `source_priority`。
- Kappa overview 最新输出 `vendor_24h_live_gate_count=16`、`vendor_24h_onboarding_count=4`、`vendor_24h_live_closure_count=4`、`vendor_24h_live_pilot_count=2`、`vendor_24h_procurement_readiness_count=28`、`vendor_procurement_primary_candidate_count=0`、`vendor_24h_primary_promotion_count=3`、`vendor_24h_primary_promotion_blocked_count=21`、`latest_vendor_primary_promotion_status=blocked`、`vendor_primary_promotion_routing_allowed_count=0`、`free_source_24h_recovery_health_count=3`、`latest_free_source_recovery_health_status=warning`、`free_source_recovery_backlog_count=34`。
- Kappa Admin API smoke 覆盖 Beta-2/Gamma-2/Delta-2/Epsilon-3/Zeta-3/Eta-3/Theta-3/Iota-3/Iota-4/Iota-5/Kappa-5/Lambda-5/Mu-5/Nu-5/Xi-5/Omicron-5/Pi-5 endpoints，`vendor_primary_promotions=ok rows=3`、`vendor_primary_promotion_results=ok rows=20`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=337318 markers=33`，覆盖 Vendor Primary Promotions 和 Vendor Primary Promotion Results。
- Kappa Admin API smoke 中 console HTML 更新并渲染 Payments/Revenue/Runtime/Strategy/Governance/Automation/Alpha-2/Beta-2/Gamma-2/Delta-2、Vendor/Epsilon-3/Zeta-3/Eta-3/Theta-3/Omicron-5/Pi-5 和 Free Sources/Iota-3 表格。
- Docker app profile 真实启动 `qdata-api=healthy`，`18080/devtoken` 下 Upsilon console、Kappa Admin API 和原数据 API smoke 均通过；Kappa Admin API 输出 `free_source_recovery_health=ok rows=3`，核心数据 API 输出 health/price/constraints/tradable/matrix 全部 ok。
- `GET /` 当前返回 `302 Location: /admin/console?token=devtoken`，浏览器打开根路径不再停在 missing bearer token JSON。
- Playwright 已生成 Pi-5 桌面截图 `/tmp/pi5-upsilon-desktop.png`（1440 x 261676）和移动截图 `/tmp/pi5-upsilon-mobile.png`（390 x 701175），两个视口均能看到 Upsilon 控件；HTML marker 已确认 Vendor Primary Promotions 和 Vendor Primary Promotion Results 表格渲染。
- API audit 最新输出 `requests=6118`、`failed=5`、`error_rate=0.00081726`；失败主要为无 Bearer token 的浏览器/curl 验证访问。

验证命令：

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q qdata scripts tests examples
python3 examples/quickstart.py
./scripts/check_data_quality.py
./scripts/ingest_daily_bar.py --dry-run
```

真实数据库 smoke 命令：

```bash
./scripts/start_local_stack.sh
./scripts/run_sql_smoke.sh
./scripts/ingest_daily_bar.py
./scripts/sync_daily_market.py --provider csv --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ
.venv312/bin/python scripts/sync_daily_market.py --provider akshare --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ
.venv312/bin/python scripts/smoke_daily_market.py --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ
./scripts/run_daily_pipeline.py --provider csv --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ --force
./scripts/run_daily_pipeline.py --provider csv --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ
.venv312/bin/python scripts/run_daily_pipeline.py --provider akshare --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ --force
./scripts/run_daily_pipeline.py --provider csv --all-market --job-code daily_market_csv_all --trade-date 2024-01-04 --batch-size 1 --force
./scripts/run_daily_pipeline.py --provider csv --all-market --job-code daily_market_csv_all --trade-date 2024-01-05 --batch-size 1 --force
./scripts/smoke_full_market_daily.py --job-code daily_market_csv_all --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ
.venv312/bin/python scripts/run_daily_pipeline.py --provider akshare --all-market --job-code daily_market_akshare_all_smoke --trade-date 2024-01-04 --max-symbols 2 --batch-size 1 --min-completeness 0.5 --force
.venv312/bin/python scripts/smoke_full_market_daily.py --job-code daily_market_akshare_all_smoke --trade-date 2024-01-04 --symbols 000001.SZ,000002.SZ
./scripts/run_daily_production.sh --provider csv --job-code daily_market_csv_all --start-date 2024-01-04 --end-date 2024-01-04 --batch-size 1 --force
./scripts/report_daily_production.py --job-code daily_market_csv_all --start-date 2024-01-04 --end-date 2024-01-05
./scripts/run_repair_queue.py --job-code daily_market_csv_all --limit 1
./scripts/benchmark_daily_query.py --symbols 600519.SH,000001.SZ --start-date 2024-01-04 --end-date 2024-01-04 --repeat 3
./scripts/sync_market_constraints.py --provider csv --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ
./scripts/build_tradable_universe.py --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ
./scripts/export_price_matrix.py --symbols 600519.SH,000001.SZ --start-date 2024-01-04 --end-date 2024-01-04 --field close --output raw/exports/close_matrix.csv
./scripts/sync_minute_market.py --provider csv --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ
./scripts/compare_daily_sources.py --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ
./scripts/run_api_server.py --backend sql --port 18080 --tokens devtoken
./scripts/smoke_api_server.py --base-url http://127.0.0.1:18080 --token devtoken --start-date 2024-01-02 --end-date 2024-01-02 --asof-date 2024-01-02 --symbols 600519.SH,000001.SZ
./scripts/report_ops_dashboard.py --start-date 2024-01-04 --end-date 2024-01-04 --dataset-code daily_bar --write-snapshot
./scripts/check_sla_alerts.py --policy-code daily_bar_conflict_sla --policy-name "Daily bar conflict SLA" --ensure-policy --dataset-code daily_bar --max-conflict-rate 0.001 --trade-date 2024-01-04
./scripts/report_api_audit.py --start-date 2026-07-24 --end-date 2026-07-28
./scripts/register_vendor_profile.py --source-code vendor_http --source-name "Commercial HTTP Vendor Fixture" --provider-name vendor_http --auth-mode bearer --enabled-datasets daily_bar,adjustment_factor,limit_price_daily --rate-limit-per-min 120 --license-scope "commercial contract required; fixture smoke only" --redistribution-allowed unknown --status testing
./scripts/benchmark_vendor_sources.py --primary-provider csv --secondary-provider vendor_http --start-date 2024-01-04 --end-date 2024-01-04 --symbols 600519.SH,000001.SZ --write-db
.venv312/bin/python scripts/benchmark_vendor_sources.py --primary-provider csv --secondary-provider akshare --start-date 2024-01-04 --end-date 2024-01-04 --symbols 600519.SH,000001.SZ --write-db
./scripts/report_vendor_scores.py --dataset-code daily_bar
./scripts/register_vendor_field_mapping.py --source-code vendor_http --dataset-code daily_bar --print-mapping
./scripts/activate_vendor_profile.py --source-code vendor_http --provider-name vendor_http --status active
./scripts/benchmark_vendor_universe.py --primary-provider csv --secondary-provider vendor_http --start-date 2024-01-04 --end-date 2024-01-04 --symbols 600519.SH,000001.SZ --shard-size 1 --write-db
./scripts/check_provider_sla_alerts.py --source-code vendor_http --dataset-code daily_bar --trade-date 2024-01-04
./scripts/report_vendor_decisions.py --dataset-code daily_bar --write-db
.venv312/bin/python scripts/bootstrap_iota_security.py --token iotatoken --json
.venv312/bin/python scripts/register_notification_channel.py --channel-code stdout-high --channel-type stdout --min-severity high --json
.venv312/bin/python scripts/send_alert_notifications.py --channel-code stdout-high --json
.venv312/bin/python scripts/run_api_server.py --backend sql --port 18081
.venv312/bin/python scripts/smoke_api_server.py --base-url http://127.0.0.1:18081 --token iotatoken --start-date 2024-01-04 --end-date 2024-01-04 --asof-date 2024-01-04 --symbols 600519.SH,000001.SZ
.venv312/bin/python scripts/report_api_usage.py --trade-date 2026-07-24 --rollup --project-code quant-research
.venv312/bin/python scripts/manage_vendor_benchmark_schedule.py --schedule-code daily_bar_vendor_fixture_schedule --run-now --json
./scripts/register_vendor_field_mapping.py --source-code vendor_http --dataset-code adjustment_factor
./scripts/register_vendor_field_mapping.py --source-code vendor_http --dataset-code limit_price_daily
./scripts/register_vendor_field_mapping.py --source-code vendor_http --dataset-code security_master
.venv312/bin/python scripts/bootstrap_iota_security.py --token iotatoken --scopes read,admin --json
.venv312/bin/python scripts/report_kappa_admin.py --resource overview
.venv312/bin/python scripts/report_kappa_admin.py --resource usage-daily --trade-date 2026-07-24 --project-code quant-research
.venv312/bin/python scripts/report_kappa_admin.py --resource tokens --limit 5
.venv312/bin/python scripts/run_api_server.py --backend sql --port 18084
.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18084 --token iotatoken --trade-date 2026-07-24
.venv312/bin/python scripts/smoke_api_server.py --base-url http://127.0.0.1:18084 --token iotatoken --start-date 2024-01-04 --end-date 2024-01-04 --asof-date 2024-01-04 --symbols 600519.SH,000001.SZ
.venv312/bin/python scripts/run_lambda_worker.py --task usage_rollup --task alert_dispatch --trade-date 2026-07-24 --channel-code stdout-high --dry-run --json
.venv312/bin/python scripts/run_lambda_worker.py --once --trade-date 2026-07-24 --channel-code stdout-high --schedule-code daily_bar_vendor_fixture_schedule --json
.venv312/bin/python scripts/run_lambda_worker.py --task usage_rollup --once --trade-date 2026-07-24
.venv312/bin/python scripts/report_kappa_admin.py --resource worker-runs --limit 5
.venv312/bin/python scripts/smoke_mu_scheduler.py --schedule-code mu_usage_rollup_5m --scheduler-id mu-smoke --trade-date 2026-07-24
.venv312/bin/python scripts/run_mu_scheduler.py --schedule-code mu_usage_rollup_5m --once --force-due --trade-date 2026-07-24
docker compose --profile scheduler run --rm mu-scheduler sh -lc "python -m pip install --no-cache-dir --target /tmp/qdata-deps 'psycopg[binary]>=3.1' >/tmp/qdata-mu-pip.log && PYTHONPATH=/tmp/qdata-deps:/app python scripts/run_mu_scheduler.py --schedule-code mu_alert_dispatch_1m --once --force-due --json"
.venv312/bin/python scripts/report_kappa_admin.py --resource worker-schedules --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource worker-schedule-ticks --limit 5
.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18084 --token iotatoken --trade-date 2026-07-24
.venv312/bin/python scripts/smoke_api_server.py --base-url http://127.0.0.1:18084 --token iotatoken --start-date 2024-01-04 --end-date 2024-01-04 --asof-date 2024-01-04 --symbols 600519.SH,000001.SZ
.venv312/bin/python scripts/run_api_server.py --backend sql --port 18085 --tokens iotatoken --token-scopes read,admin
.venv312/bin/python scripts/check_nu_health.py --environment local --release-code nu-local-smoke-20260726 --api-base-url http://127.0.0.1:18085 --api-token iotatoken --write-db --json
.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18085 --token iotatoken --trade-date 2026-07-24
.venv312/bin/python scripts/report_kappa_admin.py --resource deployment-health --limit 5
docker compose --profile app --profile scheduler config --services
.venv312/bin/python scripts/bootstrap_xi_commercial.py --evaluate --write-alerts --as-of-date 2026-07-26
.venv312/bin/python scripts/report_xi_billing.py --resource evaluate-budgets --budget-code demo_quant-research_monthly_budget --as-of-date 2026-07-26 --write-db --write-alerts
.venv312/bin/python scripts/report_kappa_admin.py --resource data-products --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource budget-alerts --limit 10
.venv312/bin/python scripts/generate_omicron_invoices.py --period-start 2026-07-01 --period-end 2026-07-31 --tenant-code demo --project-code quant-research --json
.venv312/bin/python scripts/report_kappa_admin.py --resource invoices --invoice-code inv-demo-quant-research-a_share_daily_core-20260701-20260731 --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource invoice-lines --invoice-code inv-demo-quant-research-a_share_daily_core-20260701-20260731 --limit 10
.venv312/bin/python scripts/report_omicron_revenue.py --resource revenue-summary --tenant-code demo --project-code quant-research
.venv312/bin/python scripts/update_omicron_invoice_status.py --invoice-code inv-demo-quant-research-a_share_daily_core-20260701-20260731 --status paid --json
.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18086 --token iotatoken --trade-date 2026-07-26
.venv312/bin/python scripts/benchmark_vendor_universe.py --primary-provider csv --secondary-provider vendor_http --start-date 2024-01-04 --end-date 2024-01-04 --target-trade-days 5 --symbols 600519.SH,000001.SZ --shard-size 1 --write-db
.venv312/bin/python scripts/benchmark_vendor_universe.py --primary-provider csv --secondary-provider vendor_http --start-date 2024-01-04 --end-date 2024-01-04 --target-trade-days 20 --symbols 600519.SH,000001.SZ --shard-size 1 --write-db
.venv312/bin/python scripts/benchmark_vendor_universe.py --primary-provider csv --secondary-provider vendor_http --start-date 2024-01-04 --end-date 2024-01-04 --target-trade-days 60 --symbols 600519.SH,000001.SZ --shard-size 1 --write-db
.venv312/bin/python scripts/report_pi_vendor_readiness.py --dataset-code daily_bar --source-code vendor_http --primary-source-code csv --windows 5,20,60 --json
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-readiness --source-code vendor_http --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-readiness-windows --review-code pi-readiness-vendor_http-daily_bar-20260726-5-20-60d --limit 10
.venv312/bin/python scripts/run_api_server.py --backend sql --port 18087 --tokens iotatoken --token-scopes read,admin
.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18087 --token iotatoken --trade-date 2026-07-26
.venv312/bin/python scripts/smoke_api_server.py --base-url http://127.0.0.1:18087 --token iotatoken --start-date 2024-01-04 --end-date 2024-01-04 --asof-date 2024-01-04 --symbols 600519.SH,000001.SZ
.venv312/bin/python scripts/report_rho_revenue.py --resource generate-all --period-start 2026-07-01 --period-end 2026-07-31 --as-of-date 2026-07-26 --tenant-code demo --project-code quant-research --json
.venv312/bin/python scripts/report_kappa_admin.py --resource revenue-reconciliation --tenant-code demo --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource revenue-reconciliation-lines --reconciliation-code rho-recon-demo-quant-research-a_share_daily_core-20260701-20260731-20260726 --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource ar-aging --as-of-date 2026-07-26 --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource customer-health --as-of-date 2026-07-26 --limit 10
.venv312/bin/python scripts/run_api_server.py --backend sql --port 18088 --tokens iotatoken --token-scopes read,admin
.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18088 --token iotatoken --trade-date 2026-07-26
.venv312/bin/python scripts/smoke_api_server.py --base-url http://127.0.0.1:18088 --token iotatoken --start-date 2024-01-04 --end-date 2024-01-04 --asof-date 2024-01-04 --symbols 600519.SH,000001.SZ
.venv312/bin/python scripts/report_sigma_runtime.py --resource collect --environment local --report-date 2026-07-26
.venv312/bin/python scripts/report_kappa_admin.py --resource runtime-logs --environment local --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource runtime-metrics --environment local --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource runtime-daily-reports --environment local --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource capacity-alerts --environment local --limit 5
.venv312/bin/python scripts/report_tau_payments.py --resource bootstrap-demo --as-of-date 2026-07-27 --tenant-code demo --project-code quant-research --amount 100.00000000
.venv312/bin/python scripts/report_tau_payments.py --resource payment-batches --batch-code tau-demo-payments-20260727
.venv312/bin/python scripts/report_tau_payments.py --resource payments --batch-code tau-demo-payments-20260727
.venv312/bin/python scripts/report_tau_payments.py --resource payment-matches --batch-code tau-demo-payments-20260727
.venv312/bin/python scripts/report_tau_payments.py --resource revenue-ledger --transaction-code tau-pay-tau-demo-payment-20260727
.venv312/bin/python scripts/report_phi_strategy.py --resource run-all --as-of-date 2026-07-27 --environment local --trigger-mode smoke
.venv312/bin/python scripts/report_phi_strategy.py --resource decisions --run-code phi-local-20260727
.venv312/bin/python scripts/report_kappa_admin.py --resource strategy-decisions --run-code phi-local-20260727 --limit 10
.venv312/bin/python scripts/report_chi_governance.py --resource evaluate-access --tenant-code demo --project-code quant-research --principal-code research-bot --dataset-code daily_bar --api-name price --fields close,volume --request-id chi-smoke-allow --write-audit
.venv312/bin/python scripts/report_chi_governance.py --resource evaluate-access --tenant-code demo --project-code quant-research --principal-code research-bot --dataset-code financial_statement --api-name fundamentals --request-id chi-smoke-deny --write-audit
.venv312/bin/python scripts/report_chi_governance.py --resource collect-snapshots --snapshot-date 2026-07-27 --tenant-code demo --project-code quant-research --write-db --write-actions
.venv312/bin/python scripts/report_kappa_admin.py --resource access-decisions --project-code quant-research --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource project-governance --project-code quant-research --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource governance-actions --project-code quant-research --limit 10
.venv312/bin/python scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode dry_run
.venv312/bin/python scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode execute --no-chi --source-run-code phi-local-20260727 --run-code psi-local-20260727-execute-phi-safe
.venv312/bin/python scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode execute --no-phi --tenant-code demo --project-code quant-research --run-code psi-local-20260727-execute-chi-guard
.venv312/bin/python scripts/report_kappa_admin.py --resource automation-runs --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource automation-actions --limit 10
.venv312/bin/python scripts/smoke_delta2_wecom.py
.venv312/bin/python scripts/report_delta2_wecom.py --resource receipts --profile-code delta2-wecom-live-profile --provider-code wecom --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource automation-live-receipts --limit 5
.venv312/bin/python scripts/smoke_epsilon3_vendor_live_gate.py
.venv312/bin/python scripts/smoke_epsilon3_vendor_live_gate.py --allow-live --require-live
.venv312/bin/python scripts/run_epsilon3_vendor_live_gate.py --resource runs --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-gates --limit 100
.venv312/bin/python scripts/smoke_zeta3_vendor_onboarding.py
.venv312/bin/python scripts/smoke_zeta3_vendor_onboarding.py --allow-live --require-live
.venv312/bin/python scripts/run_zeta3_vendor_onboarding.py --resource runs --limit 5
.venv312/bin/python scripts/run_zeta3_vendor_onboarding.py --resource results --limit 100
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-onboarding-runs --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-onboarding-results --limit 100
.venv312/bin/python scripts/smoke_eta3_vendor_live_closure.py
.venv312/bin/python scripts/smoke_eta3_vendor_live_closure.py --allow-live --require-live
.venv312/bin/python scripts/run_eta3_vendor_live_closure.py --resource runs --limit 5
.venv312/bin/python scripts/run_eta3_vendor_live_closure.py --resource probes --limit 100
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-closures --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-probes --limit 100
.venv312/bin/python scripts/smoke_theta3_vendor_live_pilot.py
.venv312/bin/python scripts/smoke_theta3_vendor_live_pilot.py --allow-live --require-live
.venv312/bin/python scripts/run_theta3_vendor_live_pilot.py --resource runs --limit 5
.venv312/bin/python scripts/run_theta3_vendor_live_pilot.py --resource results --limit 20
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-pilots --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-pilot-results --limit 20
.venv312/bin/python scripts/smoke_omicron5_vendor_contract.py
.venv312/bin/python scripts/run_omicron5_vendor_contract.py --resource profiles --limit 5
.venv312/bin/python scripts/run_omicron5_vendor_contract.py --resource entitlements --limit 5
.venv312/bin/python scripts/run_omicron5_vendor_contract.py --resource readiness --limit 5
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_contract_readiness_review --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code omicron5_vendor_contract_readiness_6h --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-procurement-readiness --limit 5
.venv312/bin/python scripts/smoke_pi5_vendor_primary_promotion.py
.venv312/bin/python scripts/run_pi5_vendor_primary_promotion.py --resource runs --limit 5
.venv312/bin/python scripts/run_pi5_vendor_primary_promotion.py --resource results --limit 20
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_promotion_review --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_promotion_review --trade-date 2026-07-28
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code pi5_vendor_primary_promotion_6h --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-promotions --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-promotion-results --limit 20
.venv312/bin/python scripts/smoke_rho5_post_promotion_monitor.py
.venv312/bin/python scripts/run_rho5_post_promotion_monitor.py --resource runs --limit 5
.venv312/bin/python scripts/run_rho5_post_promotion_monitor.py --resource results --limit 20
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_post_promotion_monitor --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_post_promotion_monitor --trade-date 2026-07-28
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code rho5_post_promotion_monitor_1h --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-post-promotion-monitors --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-post-promotion-results --limit 20
.venv312/bin/python scripts/smoke_sigma5_vendor_primary_stability.py
.venv312/bin/python scripts/run_sigma5_vendor_primary_stability.py --resource snapshots --limit 5
.venv312/bin/python scripts/run_sigma5_vendor_primary_stability.py --resource datasets --limit 20
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_stability_monitor --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_stability_monitor --trade-date 2026-07-28
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code sigma5_vendor_primary_stability_1h --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-stability --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-stability-datasets --limit 20
.venv312/bin/python scripts/run_api_server.py --backend sql --port 18091 --tokens iotatoken --token-scopes read,admin
.venv312/bin/python scripts/smoke_upsilon_console.py --base-url http://127.0.0.1:18091 --token iotatoken
.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18091 --token iotatoken --trade-date 2026-07-28
.venv312/bin/python scripts/smoke_api_server.py --base-url http://127.0.0.1:18091 --token iotatoken --start-date 2024-01-04 --end-date 2024-01-04 --asof-date 2024-01-04 --symbols 600519.SH,000001.SZ
docker compose --profile app up -d --force-recreate qdata-api
.venv312/bin/python scripts/smoke_upsilon_console.py --base-url http://127.0.0.1:18080 --token devtoken
.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18080 --token devtoken --trade-date 2026-07-28
.venv312/bin/python scripts/smoke_api_server.py --base-url http://127.0.0.1:18080 --token devtoken --start-date 2024-01-04 --end-date 2024-01-04 --asof-date 2024-01-04 --symbols 600519.SH,000001.SZ
curl -i -s http://127.0.0.1:18080/ | head -20
npx --yes playwright screenshot --full-page --viewport-size=1440,1100 --wait-for-selector='[data-upsilon-controls]' http://127.0.0.1:18080/ /tmp/rho5-upsilon-desktop.png
npx --yes playwright screenshot --full-page --viewport-size=390,900 --wait-for-selector='[data-upsilon-controls]' http://127.0.0.1:18080/ /tmp/rho5-upsilon-mobile.png
```

## 5.42 主源切换后监控与回滚闭环 Rho-5

新增 Pi-5 applied promotion 之后的 monitor/runbook 层：

- Migration `0041_postgresql_vendor_rho5_post_promotion_monitor.sql`：新增 `vendor_post_promotion_monitor_run`、`vendor_post_promotion_dataset_monitor` 和 `rho5_post_promotion_monitor_1h` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.rho5_post_promotion_monitor`：读取最新 Pi-5 promotion/result 和当前 `source_priority`，输出 healthy/warning/rollback_recommended/rolled_back/blocked/no_applied_promotion；默认 review-only，只有显式 `apply_rollback` 才回滚路由。
- CLI/smoke：新增 `scripts/run_rho5_post_promotion_monitor.py` 和 `scripts/smoke_rho5_post_promotion_monitor.py`。
- Worker/Mu：新增 `vendor_post_promotion_monitor` task 和 Rho-5 task_args 透传。
- Kappa/Upsilon：新增 `/admin/vendor-post-promotion-monitors`、`/admin/vendor-post-promotion-results`，overview 新增 post-promotion 指标，Vendor tab 新增两张表。
- 测试：新增 Rho-5 纯函数测试，并扩展 Lambda worker、Mu scheduler、Kappa、Upsilon 和 smoke marker 覆盖。
- Rho-5 migration 0041 已在本机 PostgreSQL 连续应用两次；第二次跳过已存在对象且 schedule `INSERT 0 0`。
- Rho-5 smoke 输出 `rho5_post_promotion_monitor_smoke=ok status=no_applied_promotion datasets=7 healthy=0 warning=0 rollback_recommended=0 rolled_back=0 blocked=0 no_applied=7 rollback_allowed=False rollback_applied=False`。
- Rho-5 worker dry-run 输出 `task name=vendor_post_promotion_monitor status=skipped processed=7 warning=7`，非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`。
- Rho-5 Mu schedule 强制触发输出 `tick schedule=rho5_post_promotion_monitor_1h task=vendor_post_promotion_monitor status=warning lock_acquired=True worker_run_id=26`。
- Kappa overview 最新输出 `vendor_24h_post_promotion_monitor_count=3`、`vendor_24h_post_promotion_no_applied_count=21`、`latest_vendor_post_promotion_status=no_applied_promotion`、`vendor_post_promotion_rollback_allowed_count=0`。
- Kappa Admin API smoke 覆盖 Rho-5 endpoints，`vendor_post_promotion_monitors=ok rows=3`、`vendor_post_promotion_results=ok rows=20`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=364331 markers=35`，覆盖 Vendor Post Promotion Monitors 和 Vendor Post Promotion Results。
- Playwright 已生成 Rho-5 桌面截图 `/tmp/rho5-upsilon-desktop.png`（1440 x 281862）和移动截图 `/tmp/rho5-upsilon-mobile.png`（390 x 761155）。

## 5.43 主供应商长期生产稳定性 Sigma-5

新增 Rho-5 之后的长期生产水位层：

- Migration `0042_postgresql_vendor_sigma5_primary_stability.sql`：新增 `vendor_primary_stability_snapshot`、`vendor_primary_stability_dataset_snapshot` 和 `sigma5_vendor_primary_stability_1h` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.sigma5_vendor_primary_stability`：读取 Omicron-5 entitlement、Pi-5 promotion、Rho-5 post-promotion、当前 `source_priority`、API audit、worker/scheduler 和 capacity alert，输出 healthy/warning/critical/blocked/no_primary_promotion。
- CLI/smoke：新增 `scripts/run_sigma5_vendor_primary_stability.py` 和 `scripts/smoke_sigma5_vendor_primary_stability.py`。
- Worker/Mu：新增 `vendor_primary_stability_monitor` task 和 Sigma-5 task_args 透传；critical 映射为 worker failed，no_primary/blocked/warning 映射为 warning。
- Kappa/Upsilon：新增 `/admin/vendor-primary-stability`、`/admin/vendor-primary-stability-datasets`，overview 新增 primary stability、critical/no_primary、cost、scheduler lag 和 backlog 指标，Vendor tab 新增两张表。
- 测试：新增 Sigma-5 纯函数测试，并扩展 Lambda worker、Mu scheduler、Kappa、Upsilon 和 smoke marker 覆盖。
- Sigma-5 migration 0042 已在本机 PostgreSQL 连续应用两次；第二次跳过已存在对象且 schedule `INSERT 0 0`。
- Sigma-5 smoke 输出 `sigma5_primary_stability_smoke=ok status=no_primary_promotion role=watch datasets=7 primary=0 healthy=0 warning=0 critical=0 blocked=0 no_primary=7 api_success_rate=0.999307 scheduler_lag=0 backlog=1 score=0.0000`。
- Sigma-5 worker dry-run 输出 `task name=vendor_primary_stability_monitor status=skipped processed=7 warning=7`，非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`。
- Sigma-5 Mu schedule 强制触发输出 `tick schedule=sigma5_vendor_primary_stability_1h task=vendor_primary_stability_monitor status=warning lock_acquired=True worker_run_id=29`。
- Kappa 查询输出 `admin.vendor-primary-stability rows=1 status=no_primary_promotion primary_dataset_count=0 no_primary_dataset_count=7 api_success_rate=0.999307`，dataset 查询输出 `admin.vendor-primary-stability-datasets rows=3`。
- Kappa Admin API smoke 覆盖 Sigma-5 endpoints，`vendor_primary_stability=ok rows=3`、`vendor_primary_stability_datasets=ok rows=20`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=401847 markers=37`，覆盖 Vendor Primary Stability 和 Vendor Primary Stability Datasets。
- Docker app profile 真实启动 `qdata-api=healthy`，`18080/devtoken` 下 Upsilon console、Kappa Admin API 和原数据 API smoke 均通过。
- Playwright 已生成 Sigma-5 全页截图 `/tmp/sigma5-upsilon-desktop.png`（10M）和 `/tmp/sigma5-upsilon-mobile.png`（6.3M），以及首屏截图 `/tmp/sigma5-upsilon-desktop-viewport.png`、`/tmp/sigma5-upsilon-mobile-viewport.png`；桌面和移动视口均能看到 Upsilon 控件。
- 当前未 applied Pi-5 promotion 时，Sigma-5 输出 `status=no_primary_promotion primary_dataset_count=0 no_primary_dataset_count=7`，明确告诉页面和运维系统“主源尚未真正切换”，而不是空白。

## 5.44 主供应商组合成本优化 Tau-5

新增 Sigma-5 之后的成本、quota 和路由权重建议层：

- Migration `0043_postgresql_vendor_tau5_cost_optimization.sql`：新增 `vendor_cost_optimization_snapshot`、`vendor_route_weight_plan`、`vendor_budget_stress_dataset_snapshot` 和 `tau5_vendor_cost_optimizer_6h` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.tau5_vendor_cost_optimization`：读取 Sigma-5 primary stability、Omicron-5 contract/entitlement、当前 `source_priority` 和 API audit，输出 optimized/watch/over_budget/quota_risk/blocked/no_primary_promotion。
- CLI/smoke：新增 `scripts/run_tau5_vendor_cost_optimization.py` 和 `scripts/smoke_tau5_vendor_cost_optimization.py`。
- Worker/Mu：新增 `vendor_cost_optimizer` task 和 Tau-5 task_args 透传；`blocked/over_budget` 映射为 worker failed，`no_primary_promotion/quota_risk/watch` 映射为 warning。
- Kappa/Upsilon：新增 `/admin/vendor-cost-optimizations`、`/admin/vendor-route-weight-plans`、`/admin/vendor-budget-stress`，overview 新增 cost plan、latest cost status、primary/backup/free weight、budget usage 和 quota usage，Vendor tab 新增三张表。
- 测试：新增 Tau-5 纯函数测试，并扩展 Lambda worker、Mu scheduler、Kappa、Upsilon 和 smoke marker 覆盖。
- Tau-5 migration 0043 已在本机 PostgreSQL 连续应用两次；第一次 `INSERT 0 1` 创建 schedule，第二次跳过已存在对象且 schedule `INSERT 0 0`。
- Tau-5 smoke 输出 `tau5_vendor_cost_smoke=ok status=no_primary_promotion role=watch datasets=7 optimized=0 watch=0 over_budget=0 quota_risk=0 blocked=0 no_primary=7 primary_weight=0.0000 backup_weight=100.0000 free_weight=0.0000 budget_pct=0E-8 monthly_quota_pct=0E-8 score=0.0000 stress=21`。
- Tau-5 worker dry-run 输出 `task name=vendor_cost_optimizer status=skipped processed=7 warning=7`，非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`。
- Tau-5 Mu schedule 强制触发输出 `tick schedule=tau5_vendor_cost_optimizer_6h task=vendor_cost_optimizer status=warning lock_acquired=True worker_run_id=32`。
- Kappa 查询输出 `admin.vendor-cost-optimizations rows=1 status=no_primary_promotion dataset_count=7 no_primary_dataset_count=7`，route plan 查询输出 `admin.vendor-route-weight-plans rows=3`，budget stress 查询输出 `admin.vendor-budget-stress rows=3 recommended_action=wait_primary_promotion`。
- Kappa Admin API smoke 覆盖 Tau-5 endpoints，`vendor_cost_optimizations=ok rows=3`、`vendor_route_weight_plans=ok rows=20`、`vendor_budget_stress=ok rows=20`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=461265 markers=40`，覆盖 Vendor Cost Optimizations、Vendor Route Weight Plans 和 Vendor Budget Stress。
- Docker app profile 真实重建后 `qdata-api=healthy`，`18080/devtoken` 下 Upsilon console、Kappa Admin API 和原数据 API smoke 均通过。
- Playwright 已生成 Tau-5 首屏截图 `/tmp/tau5-upsilon-desktop-viewport.png`、`/tmp/tau5-upsilon-mobile-viewport.png`，桌面长截图 `/tmp/tau5-upsilon-desktop-long.png` 和移动全页截图 `/tmp/tau5-upsilon-mobile.png`；桌面和移动视口均能看到 Upsilon 控件与 Tau-5 cost overview 指标。
- 当前未 applied Pi-5 promotion 时，Tau-5 输出 `status=no_primary_promotion recommended_primary_weight_pct=0.0000 recommended_backup_weight_pct=100.0000`，明确禁止供应商主源权重被误放大。

## 5.45 路由权重执行护栏 Upsilon-5

新增 Tau-5 之后的审批、灰度、执行和回滚控制面：

- Migration `0044_postgresql_vendor_upsilon5_route_execution.sql`：新增 `vendor_route_weight_execution_run`、`vendor_route_weight_execution_dataset`、`vendor_route_weight_rollout_stage`、`source_route_weight_policy` 和 `upsilon5_vendor_route_weight_executor_1h` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.upsilon5_route_weight_execution`：读取最新 Tau-5 route weight plan，按 approval、execution_mode、rollout stage、budget/quota override 和 rollback_requested 输出 pending_approval/approved/staged/applied/rollback_recommended/rolled_back/blocked/no_primary_promotion/review_required。
- CLI/smoke：新增 `scripts/run_upsilon5_route_weight_execution.py` 和 `scripts/smoke_upsilon5_route_weight_execution.py`；list 模式只使用显式传入的过滤条件，避免默认 approval 过滤隐藏真实数据。
- Worker/Mu：新增 `vendor_route_weight_executor` task 和 Upsilon-5 task_args 透传；`blocked/rollback_recommended` 映射为 worker failed，`pending_approval/no_primary_promotion/staged` 映射为 warning。
- Kappa/Upsilon：新增 `/admin/vendor-route-executions`、`/admin/vendor-route-execution-datasets`、`/admin/vendor-route-rollout-stages`、`/admin/source-route-weight-policies`，overview 新增 route execution、pending/staged/applied/blocked、latest status/approval、applied weight、current stage 和 active policy 指标，Vendor tab 新增四张表。
- 测试：新增 Upsilon-5 纯函数测试，并扩展 Lambda worker、Mu scheduler、Kappa、Upsilon 和 smoke marker 覆盖。
- Upsilon-5 migration 0044 已在本机 PostgreSQL 连续应用两次；第一次 `INSERT 0 1` 创建 schedule，第二次跳过已存在对象且 schedule `INSERT 0 0`。
- Upsilon-5 smoke 输出 `upsilon5_route_execution_smoke=ok status=no_primary_promotion datasets=7 pending=0 approved=0 staged=0 applied=0 blocked=0 no_primary=7 target_primary=0.0000 applied_primary=0.0000 policies=0 stages=7`。
- Upsilon-5 worker dry-run 输出 `task name=vendor_route_weight_executor status=skipped processed=7 warning=7`，非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`。
- Upsilon-5 Mu schedule 强制触发输出 `tick schedule=upsilon5_vendor_route_weight_executor_1h task=vendor_route_weight_executor status=warning lock_acquired=True worker_run_id=35`。
- Kappa overview 最新输出 `vendor_24h_route_execution_count=3`、`vendor_24h_route_blocked_count=21`、`latest_vendor_route_execution_status=no_primary_promotion`、`latest_vendor_route_execution_approval_status=blocked`、`active_source_route_weight_policy_count=0`。
- Kappa 查询输出 `admin.vendor-route-executions rows=1 status=no_primary_promotion approval_status=blocked execution_mode=review_only dataset_count=7`，dataset/stage/policy endpoints 可查；Phi-5 后当前 policy 数字见 5.46。
- Kappa Admin API smoke 覆盖 Upsilon-5 endpoints，route execution、dataset、stage 和 policy endpoint 均 ok；Phi-5 后当前 route policy/decision 数字见 5.46。
- Upsilon console 真实服务 smoke 在 Upsilon-5 阶段通过，覆盖 Vendor Route Executions、Vendor Route Execution Datasets、Vendor Route Rollout Stages 和 Source Route Weight Policies；Phi-5 后当前控制台 marker 见 5.46。
- Docker app profile 真实重建后 `qdata-api=healthy`，`18080/devtoken` 下 Upsilon console、Kappa Admin API 和原数据 API smoke 均通过。
- Playwright 已生成 Upsilon-5 首屏截图 `/tmp/upsilon5-upsilon-desktop-viewport.png` 和 `/tmp/upsilon5-upsilon-mobile-viewport.png`；DOM 检查 `tables=82 tiles=148 route_executions=true route_policies=true`。
- 当前未 applied Pi-5 promotion 时，Upsilon-5 输出 `status=no_primary_promotion applied_primary_weight_pct=0.0000 policies=0`，明确禁止供应商主源权重被误应用。

## 5.46 路由策略生产运行时 Phi-5

新增 Upsilon-5 policy 控制面之后的真实查询/采集路由层：

- Migration `0045_postgresql_vendor_phi5_route_policy_runtime.sql`：seed route-capable source systems，并新增 `qmeta.source_route_decision_audit` 决策审计表；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.phi5_route_policy`：读取 active `source_route_weight_policy`，按 dataset、requested source、as_of_date 和 request key 用 deterministic bucket 选择 primary/backup/free/fallback 候选源。
- Sync/API：`sync_daily_market(... use_route_policy=True)` 和 `scripts/sync_daily_market.py --use-route-policy` 接入 route resolver；`/price`、`/matrix`、`/constraints` 在 `meta.route_policy` 返回决策并写入 API 决策审计。
- Fallback：采集路径在 selected provider 失败或无数据时尝试 fallback，并记录 `fallback_success`/`fallback_failed`、final source、row_count 和 duration。
- Kappa/Upsilon：新增 `/admin/source-route-decisions`，overview 新增 source route 24h 决策、fallback 和 latest final source 指标，Vendor tab 新增 Source Route Decisions 表。
- 测试：新增 Phi-5 纯函数、sync selected/fallback、API meta/audit、Kappa endpoint 和 Upsilon marker 覆盖。
- Phi-5 migration 0045 已在本机 PostgreSQL 连续应用两次；第一次创建审计表和索引，第二次跳过已存在对象。
- Phi-5 smoke 输出 `phi5_route_policy_smoke=ok policy_code=phi5-smoke-policy-20260729023952118375 selected=csv_mirror final=csv_mirror fallback=False audits=1`。
- API 元信息检查确认 `/price` 返回 `meta.route_policy`，当前默认路径为 `decision_context=api route_mode=default decision_status=success selected_source_code=csv final_source_code=csv`。
- Kappa 查询输出 `admin.source-route-decisions rows=5`，latest 包含 API default 决策和 sync policy_weighted 决策。
- Kappa Admin API smoke 覆盖 Phi-5 endpoint，`source_route_weight_policies=ok rows=2`、`source_route_decisions=ok rows=6`、`console=ok html_bytes=511564`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=511564 markers=45`，覆盖 Source Route Decisions。
- Docker app profile 真实重建后 `qdata-api=healthy`，PostgreSQL/ClickHouse 均 healthy，`18080/devtoken` 下 Upsilon console、Kappa Admin API 和原数据 API smoke 均通过。
- Playwright 已生成 Phi-5 首屏截图 `/tmp/phi5-upsilon-desktop-viewport.png` 和 `/tmp/phi5-upsilon-mobile-viewport.png`，桌面和移动视口均渲染非空 Upsilon 页面。
- 没有 active policy 或没有 PostgreSQL DSN 时，Phi-5 保持默认 requested source，不改变现有 API/ingest 行为。

## 5.47 路由策略反馈闭环 Chi-5

新增 Phi-5 之后的实时健康反馈、熔断和恢复探测层：

- Migration `0046_postgresql_vendor_chi5_route_feedback.sql`：新增 `source_route_health_snapshot`、`source_route_circuit_breaker`、`source_route_recovery_probe` 和 `chi5_source_route_feedback_15m` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.chi5_route_feedback`：读取 `source_route_decision_audit`，按 source+dataset 聚合 request/success/failure/fallback/empty/latency，输出 healthy/degraded/circuit_open 和 open/keep/close circuit 动作。
- Phi-5 resolver：接入 circuit breaker，跳过仍在 `open_until` 内的候选源；如果所有候选都被跳过，则 fail-open 并在 route meta 标记 `circuit_fail_open=true`。
- CLI/smoke：新增 `scripts/run_chi5_route_feedback.py` 和 `scripts/smoke_chi5_route_feedback.py`；list 模式只使用显式传入的过滤条件，避免默认 trigger/environment 隐藏数据。
- Worker/Mu：新增 `source_route_feedback_monitor` task 和 Chi-5 task_args 透传；critical/degraded/open probe 风险映射为 worker warning。
- Kappa/Upsilon：新增 `/admin/source-route-health`、`/admin/source-route-circuit-breakers`、`/admin/source-route-recovery-probes`，overview 新增 route health/unhealthy/latest/open circuit/recovery probe 指标，Vendor tab 新增三张表。
- 测试：新增 Chi-5 纯函数测试，并扩展 Phi-5 resolver、Lambda worker、Mu scheduler、Kappa、Upsilon 和 smoke marker 覆盖。
- Chi-5 migration 0046 已在 Docker PostgreSQL 连续应用两次；第一次创建表和 schedule，第二次跳过已存在对象且 schedule `INSERT 0 0`。
- Chi-5 smoke 输出 `chi5_route_feedback_smoke=ok first_status=critical second_status=healthy health=2 circuit=closed probe=recovered`，验证失败开闸、健康恢复和 recovered probe。
- Chi-5 worker dry-run 输出 `task name=source_route_feedback_monitor status=skipped processed=4 warning=4`，非 dry-run 输出 `status=warning processed=4 success=3 warning=2 failed=0`。
- Chi-5 Mu schedule 强制触发输出 `tick schedule=chi5_source_route_feedback_15m task=source_route_feedback_monitor status=warning lock_acquired=True worker_run_id=38`。
- Kappa 查询输出 `admin.source-route-health rows=5`、`admin.source-route-circuit-breakers rows=4`、`admin.source-route-recovery-probes rows=2`；overview 输出 `source_route_24h_health_count=13`、`source_route_open_circuit_count=1`、`source_route_24h_recovery_probe_count=2`。
- Kappa Admin API smoke 覆盖 Chi-5 endpoints，`source_route_health=ok rows=17`、`source_route_circuit_breakers=ok rows=4`、`source_route_recovery_probes=ok rows=3`、`console=ok html_bytes=534442`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=534442 markers=48`，覆盖 Source Route Health、Source Route Circuit Breakers 和 Source Route Recovery Probes。
- Docker app profile 真实重启后 `qdata-api=healthy`，PostgreSQL/ClickHouse 均 healthy，`18080/devtoken` 下 Upsilon console、Kappa Admin API 和原数据 API smoke 均通过。
- Playwright 已生成 Chi-5 首屏截图 `/tmp/chi5-upsilon-desktop-viewport.png` 和 `/tmp/chi5-upsilon-mobile-viewport.png`；桌面和移动视口均能看到 Upsilon 控件和非空指标。
- 当前模拟 baostock route 失败会把 `daily_bar/baostock` circuit 重新 open，页面和 Kappa 明确展示 `open_until`，而不是空白或误报成功。

### 5.48 Psi-5 路由故障自动处置闭环

新增 Chi-5 之后的自动化处置层：

- Migration `0047_postgresql_automation_psi5_route_incident.sql`：新增 `source_route_incident_action`，扩展 automation source_type 和 worker task 枚举，并初始化 `psi5_route_incident_automation_15m` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.psi_automation`：新增 `include_route` 路由信号源，把 `circuit_open` 映射为高风险 `degrade_vendor` 审批动作，把 `recovery_failed` 映射为 owner 通知，把 `recovered` 映射为恢复监控。
- Worker/Mu：新增 `route_incident_automation` task 和 Psi-5 task_args 透传；dry-run 预览、不写库，非 dry-run 写入 automation run/action 和 route incident action。
- CLI/smoke：新增 `scripts/run_psi5_route_incident_automation.py` 和 `scripts/smoke_psi5_route_incident_automation.py`；smoke 串起 Chi-5 open circuit、Psi-5 approval action、Chi-5 recovered probe 和 Psi-5 recovered action。
- Kappa/Upsilon：新增 `/admin/source-route-incident-actions`，overview 新增 route incident action 数、pending 数和 latest status，Vendor tab 新增 Source Route Incident Actions 表。
- 测试：扩展 Psi automation、Lambda worker、Mu scheduler、Kappa、Upsilon 和 smoke marker 覆盖。
- 0047 migration 已在 Docker PostgreSQL 连续应用两次；第一次创建表和 schedule，第二次跳过已存在对象且 schedule `INSERT 0 0`。
- Psi-5 smoke 输出 `psi5_route_incident_smoke=ok open_action=approval_required recovered_action=success source=psi5_smoke_a25466319c incidents=2`，验证 open circuit 审批动作和 recovered monitor 动作。
- Psi-5 Worker dry-run 输出 `task name=route_incident_automation status=skipped processed=8 warning=8`，非 dry-run 输出 `status=success processed=8 success=0 warning=8 failed=0`。
- Psi-5 Mu schedule 强制触发输出 `tick schedule=psi5_route_incident_automation_15m task=route_incident_automation status=success lock_acquired=True worker_run_id=41`。
- Kappa 查询输出 `admin.source-route-incident-actions rows=5`，Kappa Admin API smoke 输出 `source_route_incident_actions=ok rows=10`、`console=ok html_bytes=558721`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=558721 markers=49`，HTML 检查 `incident_table=True incident_rows=10`。
- Playwright 已生成 Psi-5 首屏截图 `/tmp/psi5-upsilon-desktop-viewport.png` 和 `/tmp/psi5-upsilon-mobile-viewport.png`；桌面和移动视口均能看到 Upsilon 控件和非空指标。

### 5.49 Omega-5 路由故障真实审批与通知闭环

新增 Psi-5 之后的真实控制闭环：

- Migration `0048_postgresql_automation_omega5_route_incident_control.sql`：新增 `source_route_incident_control`，扩展 worker task 枚举，并初始化 `omega5_route_incident_control_15m` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.omega5_route_incident_control`：读取 Psi-5 incident action，串联 Omega approval、Delta-2 企业微信 receipt、acknowledged dispatch audit、Omega execution attempt 和 rollback plan。
- Worker/Mu：新增 `route_incident_control` task 和 Omega-5 task_args 透传；dry-run 预览、不写库，非 dry-run 写入 control、approval、dispatch、receipt、attempt 和 rollback 证据。
- CLI/smoke：新增 `scripts/run_omega5_route_incident_control.py` 和 `scripts/smoke_omega5_route_incident_control.py`；默认不外发企业微信，显式 `--allow-wecom-external` 才使用真实 webhook。
- Kappa/Upsilon：新增 `/admin/source-route-incident-controls`，overview 新增 route incident control 数、pending 数和 latest stage，Vendor tab 新增 Source Route Incident Controls 表。
- 测试：新增 Omega-5 纯函数测试，并扩展 Lambda worker、Mu scheduler、Kappa、Upsilon 和 smoke marker 覆盖。
- 0048 migration 已在 Docker PostgreSQL 连续应用两次；第一次创建表和 schedule，第二次跳过已存在对象并幂等更新 schedule。
- 单元测试输出 `Ran 252 tests ... OK`。
- Omega-5 smoke 输出 `omega5_route_incident_smoke=ok pending_approval=pending approved=approved dispatch=acknowledged receipt=blocked attempt=success rollback=planned control=executed source=omega5_smoke_fdfbf1016a`。
- Omega-5 Worker dry-run/非 dry-run 当前因候选已处理输出 `task name=route_incident_control status=skipped processed=0`；Mu 强制触发输出 `tick schedule=omega5_route_incident_control_15m task=route_incident_control status=skipped lock_acquired=True worker_run_id=44`。
- Kappa 查询输出 `admin.source-route-incident-controls rows=5`；overview 输出 `source_route_24h_incident_control_count=11`、`source_route_pending_incident_control_count=0`、`latest_source_route_incident_control_stage=executed`。
- Kappa Admin API smoke 输出 `source_route_incident_controls=ok rows=11`、`console=ok html_bytes=587502`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=587502 markers=50`，覆盖 Source Route Incident Controls。
- Playwright 已生成 Omega-5 首屏截图 `/tmp/omega5-upsilon-desktop-viewport.png` 和 `/tmp/omega5-upsilon-mobile-viewport.png`；桌面和移动视口均能看到 Upsilon 控件和非空指标。

### 5.50 Alpha-6 路由故障控制健康运维层

新增 Omega-5 之后的长期健康闭环：

- Migration `0049_postgresql_automation_alpha6_route_incident_control_health.sql`：新增 `source_route_incident_control_health_snapshot`，扩展 worker task 枚举，并初始化 `alpha6_route_incident_control_health_15m` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.alpha6_route_incident_control_health`：读取 Omega-5 control、approval、dispatch、WeCom receipt、execution attempt、rollback 和 Mu schedule 证据，计算 approval SLA、pending backlog、blocked_receipt_rate、execution_failure_rate、missing rollback 和 stale schedule。
- Worker/Mu：新增 `route_incident_control_health` task 和 Alpha-6 task_args 透传；dry-run 预览、不写 snapshot，非 dry-run 写入健康快照，critical 映射为 worker failed，warning 映射为 worker warning。
- CLI/smoke：新增 `scripts/run_alpha6_route_incident_control_health.py` 和 `scripts/smoke_alpha6_route_incident_control_health.py`；smoke 先复用 Omega-5 闭环造控制证据，再写 Alpha-6 健康快照。
- Kappa/Upsilon：新增 `/admin/source-route-incident-control-health`，overview 新增最新控制健康状态、issue_count、overdue approval 和 blocked receipt，Vendor tab 新增 Source Route Incident Control Health 表。
- 测试：新增 Alpha-6 纯函数测试，并扩展 Lambda worker、Mu scheduler、Kappa、Upsilon 和 smoke marker 覆盖。
- 0049 migration 已在 Docker PostgreSQL 连续应用两次；第二次跳过已存在表/索引并幂等更新 schedule。
- 单元测试输出 `Ran 257 tests ... OK`。
- Alpha-6 smoke 输出 `alpha6_route_incident_control_health_smoke=ok status=warning snapshot_code=alpha6-route-control-health-ae3a392e4e controls=15 pending=0 blocked_receipts=4 failed_execution=0 stale=0 latest_stage=executed`。
- Alpha-6 Worker dry-run 输出 `task name=route_incident_control_health status=skipped processed=1 warning=1`；非 dry-run 输出 `status=warning processed=1 warning=1`；Mu 强制触发输出 `tick schedule=alpha6_route_incident_control_health_15m task=route_incident_control_health status=warning lock_acquired=True worker_run_id=48`。
- Kappa 查询输出 `admin.source-route-incident-control-health rows=3`；Kappa Admin API smoke 输出 `source_route_incident_control_health=ok rows=3`、`console=ok html_bytes=609089`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=609089 markers=51`，覆盖 Source Route Incident Control Health。
- 核心 API smoke 输出 `health=ok rows=1`、`price=ok rows=2`、`constraints=ok rows=2`、`tradable=ok rows=2`、`matrix_csv=ok lines=2`。
- Playwright 已生成 Alpha-6 首屏截图 `/tmp/alpha6-upsilon-desktop-viewport.png` 和 `/tmp/alpha6-upsilon-mobile-viewport.png`；桌面和移动视口均能看到 Upsilon 控件和非空指标。

### 5.51 Beta-6 路由故障控制操作队列

新增 Alpha-6 之后的可运营队列层：

- Migration `0050_postgresql_automation_beta6_route_incident_operations.sql`：新增 `source_route_incident_operation_batch` 和 `source_route_incident_operation_item`，扩展 worker task 枚举，并初始化 `beta6_route_incident_operations_30m` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.beta6_route_incident_ops`：读取 Omega-5 pending controls，生成批量 approve/reject/hold 队列、通知降噪分组、suppressed notification 证据和 full-market/smoke route incident 压测计划。
- Worker/Mu：新增 `route_incident_operations` task 和 Beta-6 task_args 透传；默认 hold/apply=false，只刷新队列和压测证据；显式 apply 时通过 Omega approval 控制面批量 approve/reject。
- CLI/smoke：新增 `scripts/run_beta6_route_incident_operations.py` 和 `scripts/smoke_beta6_route_incident_operations.py`；smoke 先造 pending route control，再批量 approve 并校验 batch/item 持久化。
- Kappa/Upsilon：新增 `/admin/source-route-incident-operation-batches` 和 `/admin/source-route-incident-operation-items`，overview 新增 latest operation status、queue、dedupe 和 stress 指标，Vendor tab 新增 Operation Batches/Items 表。
- 测试：新增 Beta-6 纯函数测试，并扩展 Lambda worker、Mu scheduler、Kappa、Upsilon 和 smoke marker 覆盖。
- 0050 migration 已在 Docker PostgreSQL 连续应用两次；第二次跳过已存在表/索引并幂等更新 schedule。
- 单元测试输出 `Ran 262 tests ... OK`。
- Beta-6 smoke 输出 `beta6_route_incident_operations_smoke=ok status=success batch_code=beta6-route-ops-4811dfb7e6 eligible=1 approved=1 suppressed=0 stress_scenarios=16 items=1 source=beta6_smoke_4bb79a186c`。
- CLI 查询输出 `admin.source-route-incident-operation-batches rows=3` 和 `admin.source-route-incident-operation-items rows=1`。
- Beta-6 Worker dry-run 输出 `task name=route_incident_operations status=skipped processed=0 warning=1`；非 dry-run 当前无待处理队列输出 `status=skipped processed=0`；Mu 强制触发输出 `tick schedule=beta6_route_incident_operations_30m task=route_incident_operations status=skipped lock_acquired=True worker_run_id=51`。
- Kappa Admin API smoke 输出 `source_route_incident_operation_batches=ok rows=3`、`source_route_incident_operation_items=ok rows=1`、`console=ok html_bytes=632573`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=632573 markers=53`，覆盖 Source Route Incident Operation Batches/Items。
- 核心 API smoke 输出 `health=ok rows=1`、`price=ok rows=2`、`constraints=ok rows=2`、`tradable=ok rows=2`、`matrix_csv=ok lines=2`。

### 5.52 Gamma-6 路由故障可写审批 API

新增 Beta-6 队列之上的可写签批层：

- Migration `0051_postgresql_automation_gamma6_route_incident_approval_api.sql`：新增 `source_route_incident_approval_command`、`source_route_incident_approval_command_item`、`source_route_incident_approval_signature`，支持 command/item/signature 三层审计、quorum、幂等键和签批人记录；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.gamma6_route_incident_approval_api`：新增 `submit_route_incident_approval_command`、三类 list 函数和 report formatter；approve/reject 在 quorum 满足后仍通过 Omega `decide_automation_approval`，hold 只记录签批证据，不改变审批状态。
- API：新增 `POST /admin/source-route-incident-approval-commands`，必须 admin scope 和 bearer token；支持 `control_code/approval_code/batch_code` 三选一、`required_approvals`、`idempotency_key`、`requested_by/principal_code`。
- Kappa/Upsilon：新增 approval commands/items/signatures 三个 GET endpoint；overview 新增 approval command status、pending quorum、24h applied 和 signature 指标；Vendor tab 展示三张表，并在 Operation Items 行内渲染 Approve/Reject/Hold 按钮。
- CLI/smoke：新增 `scripts/run_gamma6_route_incident_approval_api.py` 和 `scripts/smoke_gamma6_route_incident_approval_api.py`；smoke 通过真实 HTTP POST 验证第一签 `pending_quorum`、第二签 `applied` 和幂等重放。
- 0051 migration 已在 Docker PostgreSQL 连续应用两次；第二次跳过已存在表/索引。
- 单元测试输出 `Ran 269 tests ... OK`。
- Gamma-6 smoke 输出 `gamma6_route_approval_api_smoke=ok first=pending_quorum second=applied quorum=met signatures=2 approved=approved`，包含 command_code、control 和 source。
- CLI 查询输出 commands/items/signatures 均 `rows>=1`。
- Kappa Admin API smoke 输出 `source_route_incident_approval_commands=ok`、`source_route_incident_approval_command_items=ok`、`source_route_incident_approval_signatures=ok`、`console=ok`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=659294 markers=57`，覆盖 Source Route Incident Approval Commands/Items/Signatures 和行级按钮。
- 核心 API smoke 输出 `health=ok rows=1`、`price=ok rows=2`、`constraints=ok rows=2`、`tradable=ok rows=2`、`matrix_csv=ok lines=2`。

### 5.53 Delta-6 路由故障审批治理层

新增 Gamma-6 之前的生产级审批治理闸门：

- Migration `0052_postgresql_automation_delta6_route_incident_approval_governance.sql`：新增 `source_route_incident_approval_role_binding`、`source_route_incident_approval_policy`、`source_route_incident_approval_callback`、`source_route_incident_approval_escalation`，支持角色绑定、策略 quorum、企业微信签名回调、replay 防护、超时/撤销/拒绝升级和 15m worker schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.delta6_route_incident_approval_governance`：新增 HMAC-SHA256 验签、时间戳偏移、nonce replay、RBAC scope、职责分离、policy 匹配、callback payload 脱敏、timeout scan、cancel 和四类 list/report 函数。
- API：新增 `POST /webhooks/wecom/source-route-incident-approval-callbacks`，不要求 Bearer token，但必须通过 `X-QData-Timestamp`、`X-QData-Nonce`、`X-QData-Signature`；新增 `POST /admin/source-route-incident-approval-wecom-callbacks`，要求 admin scope 并复用同一套签名治理。
- Kappa/Upsilon：新增 approval role bindings、policies、callbacks、escalations 四个 GET endpoint；overview 新增 active role/policy、latest callback status、24h verified/replay/denied callback 和 open escalation 指标；Vendor tab 展示四张治理表。
- CLI/smoke：新增 `scripts/run_delta6_route_incident_approval_governance.py` 和 `scripts/smoke_delta6_route_incident_approval_governance.py`；smoke 覆盖自批拒绝、第一签 pending quorum、超时升级、nonce replay 拒绝和第二签 applied。
- 0052 migration 已在 Docker PostgreSQL 连续应用两次；第二次跳过已存在表/索引；`scripts/apply_postgres_migrations.sh` 已补当前库 migration prefix 探测，真实运行输出 `Detected applied PostgreSQL migration prefix: 0052` 并跳过旧迁移。
- 单元测试输出 `Ran 276 tests ... OK`。
- Delta-6 smoke 输出 `delta6_route_approval_governance_smoke=ok denied=denied first=pending_quorum second=applied replay=replay_rejected replay_count=1 escalations=3 approved=approved`，包含 callback_code、command_code、control 和 source。
- CLI 查询输出 `delta6 resource=callbacks rows=3`、`role_bindings rows=2`、`policies rows=1`、`escalations rows=5`。
- Kappa Admin API smoke 输出 `source_route_incident_approval_role_bindings=ok rows=2`、`source_route_incident_approval_policies=ok rows=1`、`source_route_incident_approval_callbacks=ok rows=3`、`source_route_incident_approval_escalations=ok rows=5`、`console=ok html_bytes=688976`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=688976 markers=61`，覆盖 Source Route Incident Approval Role Bindings/Policies/Callbacks/Escalations。
- 核心 API smoke 输出 `health=ok rows=1`、`price=ok rows=2`、`constraints=ok rows=2`、`tradable=ok rows=2`、`matrix_csv=ok lines=2`。

### 5.54 Epsilon-6 路由故障审批韧性层

新增 Delta-6 外层的高并发审批一致性、不可变审计和恢复治理：

- Migration `0053_postgresql_automation_epsilon6_route_incident_approval_resilience.sql`：新增 approval lock event、state transition、audit hash chain、SLA action、recovery drill 五张表，扩展 worker task 枚举，并初始化 `epsilon6_route_incident_approval_resilience_15m` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.epsilon6_route_incident_approval_resilience`：新增 deterministic advisory lock key、state machine terminal guard、resilient WeCom callback wrapper、audit hash append/verify、SLA planned action 自动化和 recovery drill。
- API：`/webhooks/wecom/source-route-incident-approval-callbacks` 与 `/admin/source-route-incident-approval-wecom-callbacks` 已改为先经过 Epsilon-6 lock/state/audit，再进入 Delta-6 HMAC/RBAC/quorum。
- Worker/Mu：新增 `route_incident_approval_resilience` task 和 Epsilon-6 task_args 透传；每轮可校验 hash chain、生成 SLA planned action、写 recovery drill，hash/drill 失败映射为 failed，SLA action 映射为 warning。
- CLI/smoke：新增 `scripts/run_epsilon6_route_incident_approval_resilience.py` 和 `scripts/smoke_epsilon6_route_incident_approval_resilience.py`；smoke 覆盖第一签 pending quorum、超时 SLA action、恢复演练、第二签 applied、终态 stale callback 阻断和 audit chain 校验。
- Kappa/Upsilon：新增 lock events、state transitions、audit chain、SLA actions、recovery drills 五个 GET endpoint；overview 新增 lock/busy/state/block/audit/SLA/drill 指标，Vendor tab 展示五张韧性表。
- 0053 migration 已在 Docker PostgreSQL 连续应用两次；`scripts/apply_postgres_migrations.sh` 真实输出 `Detected applied PostgreSQL migration prefix: 0053` 并跳过旧迁移。
- 单元测试输出 `Ran 281 tests ... OK`。
- Epsilon-6 smoke 输出 `epsilon6_route_approval_resilience_smoke=ok first=pending_quorum second=applied terminal_block=invalid_terminal_state audit_broken=0 sla_actions=1 lock_events=3 transitions=3 audit_hashes=5 drills=1 approved=approved`。
- CLI 查询输出 `verify-chain` 的 `broken_count=0`；lock-events/state-transitions/audit-chain/sla-actions/recovery-drills 均返回真实行。
- Epsilon-6 Worker dry-run 输出 `task name=route_incident_approval_resilience status=skipped processed=18 success=0 warning=18 failed=0`；非 dry-run 输出 `status=warning processed=18 success=3 warning=4 failed=0`；Mu 强制触发输出 `tick schedule=epsilon6_route_incident_approval_resilience_15m task=route_incident_approval_resilience status=warning lock_acquired=True worker_run_id=54`。
- Kappa Admin API smoke 使用 `devtoken,smoketoken` 轮换 token 后通过，输出 `source_route_incident_approval_lock_events=ok rows=6`、`source_route_incident_approval_state_transitions=ok rows=6`、`source_route_incident_approval_audit_chain=ok rows=20`、`source_route_incident_approval_sla_actions=ok rows=7`、`source_route_incident_approval_recovery_drills=ok rows=4`、`console=ok html_bytes=730051`。
- Upsilon console 真实服务 smoke 通过：`upsilon_console=ok html_bytes=730051 markers=66`，覆盖 Source Route Incident Approval Lock Events/State Transitions/Audit Chain/SLA Actions/Recovery Drills。
- 核心 API smoke 输出 `health=ok rows=1`、`price=ok rows=2`、`constraints=ok rows=2`、`tradable=ok rows=2`、`matrix_csv=ok lines=2`。

### 5.55 Zeta-6 路由故障审批发布闸门

新增 Epsilon-6 外层的发布门禁、密钥轮换和监管审计包：

- Migration `0054_postgresql_automation_zeta6_route_incident_approval_release.sql`：新增 release preflight、secret rotation、concurrency test、audit export 四张表，扩展 worker task 枚举，并初始化 `zeta6_route_incident_approval_release_30m` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.zeta6_route_incident_approval_release`：新增 current/next 双密钥验签、secret rotation evidence、release preflight、concurrency test result、audit export package、Kappa list helpers 和 CLI formatter。
- API：企业微信 signed/admin callback 在进入 Epsilon-6 前先尝试 current 和 `QDATA_ZETA6_WECOM_CALLBACK_SECRET_NEXT`，命中 next 时用 next secret 交给 Epsilon-6/Delta-6 复验；响应只包含 secret label 和摘要证据，不包含密钥原文。
- Worker/Mu：新增 `route_incident_approval_release` task 和 Zeta-6 task_args 透传；每轮可跑 preflight 和 audit export，preflight failed 或 audit broken hash 映射为 failed，warning 映射为 warning。
- CLI/smoke：新增 `scripts/run_zeta6_route_incident_approval_release.py` 和 `scripts/smoke_zeta6_route_incident_approval_release.py`；支持 preflight、secret-rotation-check、audit-export 和四类证据查询。
- Kappa/Upsilon：新增 release preflights、secret rotations、concurrency tests、audit exports 四个 GET endpoint；overview 新增 release/secret/concurrency/export 指标，Vendor tab 展示四张 Zeta-6 表。
- Docker PostgreSQL 已应用 0054，重复执行 migration 输出 `Detected applied PostgreSQL migration prefix: 0054` 并跳过旧迁移。
- 单元测试输出 `Ran 287 tests ... OK`；Zeta-6 专项测试输出 `Ran 5 tests ... OK`。
- Zeta-6 smoke 输出 `zeta6_route_approval_release_smoke=ok preflight=success rotation=success verified_secret=next concurrency=success export=success broken_hashes=0 package_hash=e3b7713ad306473145af28d3b0b5595ea915cd2b3b964e4bc0801d70b5688b09`。
- Zeta-6 CLI 查询返回真实证据：release-preflights、secret-rotations、concurrency-tests、audit-exports 均 `rows=1`，audit export `broken_hash_count=0`。
- Zeta-6 Worker dry-run 输出 `task name=route_incident_approval_release status=skipped processed=7 success=0 warning=7 failed=0`；非 dry-run 输出 `task name=route_incident_approval_release status=success processed=7 success=7 warning=0 failed=0`。
- Kappa Admin API smoke 输出四个 Zeta endpoint 均 ok：release preflights `rows=2`、secret rotations `rows=1`、concurrency tests `rows=1`、audit exports `rows=2`；Upsilon 输出 `upsilon_console=ok html_bytes=735818 markers=70`；核心 API smoke 输出 health/price/constraints/tradable/matrix 全部 ok。

### 5.56 Eta-6 真实供应商生产主源闭环

新增真实授权主供应商生产主源闭环判定：

- Migration `0055_postgresql_vendor_eta6_production_source_closure.sql`：新增 `vendor_production_source_run`、`vendor_production_source_dataset_check`、`vendor_production_source_decision` 三张审计表，扩展 worker task 枚举，并初始化 `eta6_vendor_production_source_closure_30m` schedule；rollback、Docker init、`db/update.sql`、`db/table.sql` 已同步。
- `qdata.eta6_vendor_production_source`：串联 Omicron-5 合同/entitlement、Theta-3 live pilot、Pi-5 promotion、Sigma-5 stability、Tau-5 cost、Upsilon-5 route execution、post-promotion monitor 和 route health guard，输出 production run、dataset check 和 gate decision。
- 安全边界：真实供应商 token 只从环境变量读取，落库和输出只保留 token digest/tail 与 redacted config；CLI、Kappa API、Upsilon HTML 和数据库不保存 token 原文、Authorization header 或原始供应商响应正文。
- Worker/Mu：新增 `vendor_production_source_closure` task 和 Eta-6 task_args 透传；dry-run 不写 Eta-6 表，非 dry-run 写 run/check/decision；当前 blocked 映射为 worker warning，避免把缺真实 vendor env 误报为成功。
- CLI/smoke：新增 `scripts/run_eta6_vendor_production_source.py` 和 `scripts/smoke_eta6_vendor_production_source.py`；支持 run、runs、dataset-checks、decisions 查询。
- Kappa/Upsilon：新增 production source runs、dataset checks、decisions 三个 GET endpoint；overview 新增 production source count/ready/blocked/status/role/score/live env 指标，Vendor tab 展示三张 Eta-6 表。
- Docker PostgreSQL 已应用 0055，重复执行 migration 输出 `Detected applied PostgreSQL migration prefix: 0055` 并跳过旧迁移。
- 单元测试输出 `Ran 291 tests ... OK`；Eta-6 专项测试输出 `Ran 3 tests ... OK`。
- Eta-6 smoke 输出 `eta6_vendor_production_source_smoke=ok status=blocked role=blocked datasets=7 production_ready=0 blocked=7 decisions=63 live_base_url_present=False live_token_present=True score=12.5000`。
- Eta-6 CLI 查询返回真实证据：runs、dataset-checks、decisions 均 `rows=1`，输出只包含状态、计数、阻断原因和脱敏字段，不暴露 token 原文。
- Eta-6 Worker dry-run 输出 `task name=vendor_production_source_closure status=skipped processed=7 success=0 warning=7 failed=0`；非 dry-run 输出 `task name=vendor_production_source_closure status=warning processed=7 success=0 warning=7 failed=0`。
- Mu 强制触发输出 `tick schedule=eta6_vendor_production_source_closure_30m task=vendor_production_source_closure status=warning lock_acquired=True worker_run_id=59 duration_ms=178`。
- Kappa Admin API smoke 输出三个 Eta-6 endpoint 均 ok：production runs `rows=3`、dataset checks `rows=20`、decisions `rows=20`；Upsilon 输出 `upsilon_console=ok html_bytes=807462 markers=73`；核心 API smoke 输出 health/price/constraints/tradable/matrix 全部 ok。

## 6. 待扩展复测

继续接入更多真实数据源后，需要重点复测：

- `security_master.current_symbol || '.' || exchange` 是否与实际代码规范一致。
- `financial_metric_pit.metric_scope` 与 `financial_statement_pit.period_type` 是否按 DDL 初始化。
- 复权价格是否符合内部复权口径，尤其是多来源复权因子冲突。
- 指数和行业 as-of 查询是否能处理多版本冲突。
- 查询大股票池时的性能和参数数量上限。
- AkShare 免费接口的许可边界、稳定性、字段口径差异和限频策略。
- 真实商业 vendor token、合同授权、再分发边界和生产 rate limit。
- vendor_http 在真实 endpoint 下 5/20/60 个交易日、全市场股票池的稳定性和吞吐。
- Pi 在真实商业 endpoint 下启用 `--require-live-endpoint`、`--require-active-profile` 和 `--require-contract` 后的主源上线结论。
- 大日期窗口和大股票池下 pipeline_run 写入、重试和 skip 策略是否需要按分片任务拆分。
- 飞书/邮件/webhook 在真实办公系统里的签名、重试和降噪策略。
- Chi 在真实多租户、多项目、大量 principal/token/ACL 和字段级拒绝场景下的权限边界、审计写入量和治理动作归属。
- Kappa 页面在真实多租户、多项目、大量 token 和大量告警投递记录下的分页与筛选体验。
- Mu scheduler 在 systemd、Kubernetes CronJob 或内部任务调度平台下的长期心跳、日志和失败重试策略。
- Nu 部署脚本在真实 Docker Desktop 冷启动、镜像重拉、端口冲突和网络抖动下的耗时边界。
- Xi/Omicron 在真实客户多产品、多价格层级、多币种、月末账单周期、部分回款和账单重算下的金额精度与对账口径。
- Rho 在真实多客户、多产品、多价格层级、多币种、部分回款和逾期账单下的 AR aging 与客户健康分层。
- Sigma 在长期运行、真实日志量、进程资源指标、表容量增长和多环境部署下的阈值调优与告警降噪。
- Tau 在真实银行/支付宝/微信/企业网银流水、部分回款、跨币种汇率、退款和人工复核下的财务口径。
- Upsilon 在真实大量租户、项目、token、告警、付款流水和 ledger 行数下的前端分页性能与人工复核操作体验。
- Phi 在真实全市场、多供应商、多租户、多产品、多环境下的策略阈值、优先级、升级归属和自动化动作误伤率。
- Delta-2 配置真实 `QDATA_DELTA2_WECOM_WEBHOOK_URL` 后的企业微信 `errcode=0` live 回执、群内可见性和告警降噪策略。
- Epsilon-3 配置真实 `QDATA_VENDOR_BASE_URL`、`QDATA_VENDOR_TOKEN`、合同状态和限频参数后的 5/20/60 live benchmark、全市场分片吞吐和 Pi 主源上线结论。
- Zeta-3 配置真实供应商 env、启用完整 dataset、补齐合同/再分发授权后，跑多数据集 canary、5/20/60 gate 和全市场 onboarding 编排。
- Theta-3 配置真实供应商 env、启用完整 dataset、补齐合同/再分发授权和 rate limit 后，跑 endpoint schema probe、Zeta-3 onboarding、Epsilon-3 gate 和 canary/full-market pilot。
- Nu-5 在真实企业微信 webhook、真实免费源 token 和长期调度下复测审批 SLA、backlog 降噪、调度陈旧识别和 runbook 处置效率。
- Xi-5 在真实合同、再分发授权、条款复核、限频配额和长期可靠性证据齐全后，复测是否只把合规源提升为 primary_candidate。
- Omicron-5 在真实主供应商合同、再分发/缓存授权、生产使用授权、dataset entitlement、schema/field mapping、SLA、quota 和 Pi/Epsilon-3/Zeta-3/Eta-3/Theta-3 live 证据齐全后，复测是否只把合规主源提升为 primary_candidate。
- Pi-5 在 Omicron-5 ready/primary_candidate、Pi 5/20/60 readiness、Theta-3 canary/full-market pilot 和签批证据齐全后，复测 `approved_for_primary`、显式 apply routing、`source_priority` 幂等更新和回滚监控。
- Rho-5 在真实 applied Pi-5 promotion 后，复测影子对账阈值、rollback_recommended、显式 apply rollback、`source_priority` 幂等回滚和 Upsilon 可观测。
- Sigma-5 在真实 applied Pi-5 promotion 后，复测 API success/error/timeout/latency、cost_units、scheduler lag、capacity alert、Rho rollback 风险和 worker failed/warning 映射。
- Tau-5 在真实 applied Pi-5 promotion、真实合同单价、月费、日/月 quota、预算和 API 用量后，复测 optimized/over_budget/quota_risk、1x/5x/10x 压测、权重建议和 worker failed/warning 映射。
- Upsilon-5 在真实 applied Pi-5 promotion 和 Tau-5 optimized plan 后，复测 manual approval、dry_run、apply、10/30/60/90 灰度阶段、active/superseded policy、rollback_requested 和 worker failed/warning 映射。
- Phi-5 在真实 active policy、全市场、多 provider、多数据集和 API 高并发下，复测 deterministic 权重分布、fallback 成功率、审计写入量、API latency 增量和默认兼容路径。
- Chi-5 在真实 active policy、长期 API/sync 流量、多 provider、多数据集和高并发下，复测熔断阈值、恢复探测窗口、fail-open 策略、worker warning 降噪和 API latency 增量。
- Psi-5 在真实 active policy、长期 API/sync 流量、多 provider、多数据集和高并发下，复测 incident action 去重、审批积压、企业微信通知、误报降噪和恢复动作重复执行风险。
- Omega-5 在真实企业微信 webhook、长期 route incident 积压、多审批人和高并发 worker 下，复测 approval SLA、通知降噪、执行 attempt 幂等、rollback plan 关联 attempt 和 Kappa/Upsilon 可观测性。
- Alpha-6 在真实长期 route incident 流量、多审批人、真实企业微信 webhook、worker failed/warning 和 schedule stale 场景下，复测健康状态、issue 降噪、runbook 动作和 Kappa/Upsilon 可观测性。
- Beta-6 在真实长期 route incident 积压、多审批人、批量 approve/reject/hold、通知摘要、全市场压测分片和 Upsilon 操作台下，复测幂等、误批风险和降噪效果。
- Gamma-6 在真实多审批人、高并发 POST、真实企业微信交互回调和更严格职责分离下，复测 quorum、幂等、撤销/超时升级、签名审计和误批风险。
- Delta-6 在真实企业微信回调、高并发 nonce、跨项目角色绑定、多风控审批人和长期 pending queue 下，复测验签、replay、RBAC/职责分离、超时升级、撤销审计和密钥轮换。
- Epsilon-6 在真实企业微信高并发回调、长 pending queue、跨环境部署、hash chain 大规模审计、SLA action 执行联动和灾备恢复下，复测 advisory lock、终态守卫、hash verification、planned action 降噪和 drill 成功率。
- Zeta-6 在 staging/production 双环境、真实企业微信 current/next 密钥、真实高并发回调、审计包下载和监管抽查下，复测 preflight gate、secret rotation、audit export package hash 和 Kappa/Upsilon 可观测性。
- Eta-6 在真实供应商 base URL/token、正式合同、完整 dataset entitlement、full-market pilot、applied promotion、稳定性、成本和 active route policy 证据齐全后，复测 production_ready/monitoring 判定、token 脱敏、Kappa/Upsilon 可观测和 rollback guard。

## 7. 修复建议

下一轮建议按这个顺序：

1. 配置真实 `QDATA_VENDOR_BASE_URL`、`QDATA_VENDOR_TOKEN`、`QDATA_VENDOR_AUTH_MODE=bearer`、真实合同引用、再分发/缓存授权、生产使用授权、限频、日配额和 SLA。
2. 将 Omicron-5 的 `vendor_contract_profile` 和 `vendor_contract_dataset_entitlement` 从模板状态更新为正式授权状态，确认 `vendor_procurement_readiness_snapshot.primary_candidate=1` 后再允许主源候选。
3. 跑 Eta-3 profile 写入命令：`scripts/run_eta3_vendor_live_closure.py --resource run --allow-profile-write --activate-profile --enable-profile-datasets --commercial-contract-ref <contract_ref> --redistribution-allowed true --rate-limit-per-min <rate_limit>`，启用完整 dataset，特别是当前 blocked 的 `security_master`。
4. 跑 Theta-3 full-market pilot、Pi-5 promotion、Sigma-5 stability、Tau-5 cost、Upsilon-5 route execution 后，再跑 `scripts/smoke_eta6_vendor_production_source.py` 复核是否从 blocked 推进到 production_ready 或 monitoring。
4. 跑 `scripts/smoke_theta3_vendor_live_pilot.py --allow-live --require-live`，确认 endpoint probe、Zeta-3 onboarding、Epsilon-3 gate 和 Theta-3 pilot 都不再 blocked。
5. Theta-3 canary pilot 通过后，把 `--pilot-scope full_market --full-market --max-symbols <n>` 扩大到全市场，用 5/20/60 suite 作为 Pi-5 主源切换证据，再显式跑 Pi-5 `--apply-routing`。
6. 配置真实 `QDATA_DELTA2_WECOM_WEBHOOK_URL`，跑 `scripts/smoke_delta2_wecom.py --allow-external --require-live`，把企业微信 `errcode=0` receipt 落库。
7. 强化租户隔离和字段级权限，在 PostgreSQL 层评估 RLS/field mask 的生产落地方式。
8. 扩展字段映射到更多财务和事件数据集，统一进入 Theta-3/Pi-5 验收。
