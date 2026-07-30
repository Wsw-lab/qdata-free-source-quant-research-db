# qdata

`qdata` 是 A 股量化数据底座的第一版 Python SDK 原型。

当前版本默认使用本地 mock 后端，不依赖真实数据库或 API 服务，目的是先跑通研究、因子、回测取数接口的形态。

## GitHub Pages 项目页

项目展示页放在 [docs/index.html](/Users/wushuaiwei/Documents/数据库/docs/index.html)。推到 GitHub 后，可以在仓库 `Settings -> Pages` 里选择 `Deploy from a branch`，分支选 `main`，目录选 `/docs`。

这个页面把项目包装成 **QData Free Source Quant Research Database**：强调 0 元免费源路线、量化数据工程、PIT 建模、多源互校、可靠性评分、Worker/API/控制台 smoke 和当前 291 个单元测试。

英文 README 放在 [README_EN.md](/Users/wushuaiwei/Documents/数据库/README_EN.md)，架构图放在 [docs/assets/qdata-architecture.svg](/Users/wushuaiwei/Documents/数据库/docs/assets/qdata-architecture.svg)，示例 notebook 放在 [notebooks/free_source_factor_backtest.ipynb](/Users/wushuaiwei/Documents/数据库/notebooks/free_source_factor_backtest.ipynb)，小型因子回测 demo 放在 [examples/factor_backtest_demo.py](/Users/wushuaiwei/Documents/数据库/examples/factor_backtest_demo.py)。

## 快速开始

```bash
python examples/quickstart.py
```

当前 macOS 环境如果只有 `python3`，可以运行：

```bash
python3 examples/quickstart.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

## 示例

```python
from qdata import Client

client = Client()

prices = client.get_price(
    symbols=["600519.SH", "000001.SZ"],
    start_date="2024-01-02",
    end_date="2024-01-03",
    adjust="forward",
    output_format="records",
)

print(prices)
```

## 真实数据库后端

SDK 已经支持 `backend="sql"`，用于连接 PostgreSQL + ClickHouse 查询层。

### 本地 Docker 环境

启动 PostgreSQL + ClickHouse，并自动执行建表和 seed：

```bash
./scripts/start_local_stack.sh
```

运行真实 SQL backend smoke：

```bash
./scripts/run_sql_smoke.sh
```

停止本地环境：

```bash
./scripts/stop_local_stack.sh
```

重置本地数据卷并重新初始化：

```bash
./scripts/reset_local_stack.sh
```

本地默认连接：

```text
PostgreSQL: postgresql://qdata:qdata@localhost:15432/qdata
ClickHouse: http://qdata:qdata@localhost:18123/default
```

### 手动配置

安装可选依赖：

```bash
python3 -m pip install -e ".[sql]"
```

环境变量方式：

```bash
export QDATA_BACKEND=sql
export QDATA_POSTGRES_DSN="postgresql://qdata:qdata@localhost:15432/qdata"
export QDATA_CLICKHOUSE_DSN="http://qdata:qdata@localhost:18123/default"
python3 examples/sql_backend_smoke.py
```

代码方式：

```python
from qdata import Client

client = Client(
    backend="sql",
    postgres_dsn="postgresql://qdata:qdata@localhost:15432/qdata",
    clickhouse_dsn="http://qdata:qdata@localhost:18123/default",
    default_format="records",
)
```

`backend="auto"` 会在发现 PostgreSQL DSN 时使用 SQL 后端，否则回落到 mock 后端。

## 已支持接口

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

## CSV 日频导入 Alpha

当前版本已经支持从本地 CSV 完成一条真实导入闭环：

```text
raw/samples/*.csv
  -> CSV 解析和标准化
  -> 数据质量检查
  -> raw/imports 原始文件追溯
  -> PostgreSQL 主数据/日历/复权/交易约束
  -> ClickHouse 日线行情
  -> Python SDK 查询验收
```

先做质量检查：

```bash
./scripts/check_data_quality.py
```

只解析不入库：

```bash
./scripts/ingest_daily_bar.py --dry-run
```

写入本地 Docker 数据库：

```bash
./scripts/start_local_stack.sh
./scripts/ingest_daily_bar.py
```

导入后查询刚写入的 2024-01-04 样例：

```bash
QDATA_BACKEND=sql \
QDATA_POSTGRES_DSN="postgresql://qdata:qdata@localhost:15432/qdata" \
QDATA_CLICKHOUSE_DSN="http://qdata:qdata@localhost:18123/default" \
python3 - <<'PY'
from qdata import Client
with Client(backend="sql", default_format="records") as client:
    print(client.get_price(
        symbols=["600519.SH", "000001.SZ"],
        start_date="2024-01-04",
        end_date="2024-01-04",
        adjust="forward",
    ))
PY
```

CSV 样例文件：

- `raw/samples/security_master.csv`
- `raw/samples/trading_calendar.csv`
- `raw/samples/daily_bar.csv`

## 日频市场数据同步 Beta

当前版本新增了 provider 抽象，日频行情可以从本地 CSV 或 AkShare 同步到统一入库链路：

```text
provider
  -> DailyMarketBundle
  -> raw/vendor/{provider}/daily_market/trade_date=YYYY-MM-DD/*.csv
  -> 质量检查
  -> PostgreSQL 主数据/日历/交易约束
  -> ClickHouse 日线行情
  -> SDK smoke 查询
```

CSV provider 复验：

```bash
./scripts/sync_daily_market.py \
  --provider csv \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ

./scripts/smoke_daily_market.py \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ
```

AkShare provider 需要 Python 3.10+。当前机器已创建 Python 3.12 虚拟环境：

```bash
.venv312/bin/python scripts/sync_daily_market.py \
  --provider akshare \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ

.venv312/bin/python scripts/smoke_daily_market.py \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ
```

AkShare 默认只拉指定股票的日线历史数据，不做全市场名称补全。历史 K 线接口不稳定时，会 fallback 到 AkShare daily 接口，并用目标日前一交易日 close 推导 `pre_close` 和涨跌停价；如需要补全名称可加：

```bash
--akshare-lookup-names
```

如果上游免费接口或本机网络代理异常，脚本会以 `QDataProviderError` 明确失败；CSV provider 和本地数据库 smoke 不依赖外部网络。

## 生产级采集调度 Alpha

当前版本已经把手动同步脚本升级为可审计的 pipeline：

```text
pipeline_job
  -> pipeline_run
  -> provider sync
  -> quality check
  -> PostgreSQL/ClickHouse
  -> pipeline_watermark
```

增量 migration：

```bash
./scripts/apply_postgres_migrations.sh
```

启动本地 Docker stack 时也会自动补跑 PostgreSQL 增量 migration：

```bash
./scripts/start_local_stack.sh
```

CSV pipeline：

```bash
./scripts/run_daily_pipeline.py \
  --provider csv \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ \
  --force
```

AkShare pipeline：

```bash
.venv312/bin/python scripts/run_daily_pipeline.py \
  --provider akshare \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ \
  --force
```

再次运行同一日期且不加 `--force` 时，pipeline 会记录 `skipped`，避免重复生产：

```bash
./scripts/run_daily_pipeline.py \
  --provider csv \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ
```

调度层新增表：

- `qmeta.pipeline_job`：任务定义，记录 provider、数据集、股票池、质量策略、重试次数。
- `qmeta.pipeline_run`：每次运行记录，记录日期、attempt、状态、行数、质量结果、raw 路径、错误信息。
- `qmeta.pipeline_watermark`：每个任务的最后成功交易日、最后尝试日期和连续失败次数。

当前质量检查已覆盖 OHLC、正价格、非负成交量/金额/换手率、涨跌停价、复权因子、VWAP 区间、成交额/成交量/VWAP 一致性和换手率极值。

## A 股全市场日频生产 Beta

当前版本支持按 provider 解析全市场股票池、按批次拉取、合并后一次质量检查和入库，并在 `pipeline_run` 中记录完整性：

```text
provider full-market symbols
  -> batch fetch
  -> merged DailyMarketBundle
  -> completeness check
  -> SQL ingest
  -> pipeline_run expected/missing/completeness
  -> production smoke
```

质量检查会写入 `job_code/run_id` 上下文，`smoke_full_market_daily.py` 会读取当前 job/source 的 health，避免同一交易日多个任务互相覆盖验收结果。

CSV 全市场样例会发现 `300750.SZ` 缺少 2024-01-04 日线，因此返回 `partial_success`：

```bash
./scripts/run_daily_pipeline.py \
  --provider csv \
  --all-market \
  --job-code daily_market_csv_all \
  --trade-date 2024-01-04 \
  --batch-size 1 \
  --force

./scripts/smoke_full_market_daily.py \
  --job-code daily_market_csv_all \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ
```

非交易日会自动 skipped：

```bash
./scripts/run_daily_pipeline.py \
  --provider csv \
  --all-market \
  --job-code daily_market_csv_all \
  --trade-date 2024-01-05 \
  --batch-size 1 \
  --force
```

AkShare 全市场小样本 smoke。这里 `--max-symbols 2` 只用于本地验收，生产可去掉并设置合理 `--batch-size` 和 `--sleep-seconds`：

```bash
.venv312/bin/python scripts/run_daily_pipeline.py \
  --provider akshare \
  --all-market \
  --job-code daily_market_akshare_all_smoke \
  --trade-date 2024-01-04 \
  --max-symbols 2 \
  --batch-size 1 \
  --min-completeness 0.5 \
  --force

.venv312/bin/python scripts/smoke_full_market_daily.py \
  --job-code daily_market_akshare_all_smoke \
  --trade-date 2024-01-04 \
  --symbols 000001.SZ,000002.SZ
```

全市场新增字段：

- `pipeline_job.all_market`：是否由 provider 自动解析全市场股票池。
- `pipeline_job.batch_size`：分批拉取大小，`0` 表示不分批。
- `pipeline_job.max_symbols`：本地 smoke 或灰度限量。
- `pipeline_job.min_completeness`：最低完整率阈值。
- `pipeline_run.expected_row_count`：预期证券数。
- `pipeline_run.missing_symbols`：缺失证券清单。
- `pipeline_run.completeness_rate`：实际覆盖率。
- `pipeline_run.batch_count`：实际批次数。
- `pipeline_run.all_market`：本次运行是否为全市场模式。

## A 股全市场日频生产 Gamma

Gamma 阶段把日频行情从“能跑通”推进到“可增量、可回补、可修复、可报告、可压测”：

- 从 watermark 续跑：`success` 才推进成功水位线，`partial_success/failed` 只推进尝试水位线。
- 回补和重跑：生产脚本支持 `incremental`、`backfill`、`rerun` 三种模式。
- 修复队列：`partial_success/failed` 自动进入 `qmeta.pipeline_repair_queue`，后续重跑成功后自动 resolved。
- 交易所级完整率：`pipeline_run` 记录 expected/actual/missing 的 SH/SZ/BJ 拆分。
- 缺失解释：上市日前、退市后不计入应有分母；无法解释的缺失进入修复闭环。
- 生产日报：跑完即输出 status、missing、completeness、repair 概况。
- 查询压测：用 SDK 读取 ClickHouse，统计 rows、耗时和 rows/s。

增量生产，从上次成功水位线继续：

```bash
./scripts/run_daily_production.sh \
  --provider csv \
  --job-code daily_market_csv_all \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --batch-size 1
```

历史回补：

```bash
./scripts/run_daily_production.sh \
  --mode backfill \
  --provider csv \
  --job-code daily_market_csv_all \
  --start-date 2024-01-04 \
  --end-date 2024-01-05 \
  --batch-size 1
```

修复队列重跑：

```bash
./scripts/run_repair_queue.py --job-code daily_market_csv_all --limit 10
```

只读生产日报：

```bash
./scripts/report_daily_production.py \
  --job-code daily_market_csv_all \
  --start-date 2024-01-04 \
  --end-date 2024-01-05
```

查询压测：

```bash
./scripts/benchmark_daily_query.py \
  --symbols 600519.SH,000001.SZ \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --repeat 3
```

Gamma 新增字段和表：

- `pipeline_run.expected_by_exchange`：按交易所拆分的预期证券数。
- `pipeline_run.actual_by_exchange`：按交易所拆分的实际覆盖证券数。
- `pipeline_run.missing_by_exchange`：按交易所拆分的缺失证券。
- `pipeline_run.missing_explanations`：缺失或排除原因。
- `pipeline_run.repair_status`：当前 run 是否进入修复闭环。
- `pipeline_repair_queue`：待修复日期、缺失标的、完整率和修复状态。

## A 股量化行情 Delta

Delta 阶段把日频行情做成量化可直接使用的行情口径：

- 独立复权因子同步：`adjustment_factor` 不再只能跟随日线入库。
- 独立交易约束同步：涨跌停、ST、新股、停复牌可单独补跑。
- 可交易股票池：`get_tradable_universe` 和 `build_tradable_universe.py` 生成每日 tradable universe。
- 矩阵出口：`export_price_matrix.py` 输出 `trade_date x symbol` 宽表 CSV/Parquet。
- 分钟线 Alpha：`sync_minute_market.py` 写入 `qts.minute_bar`，CSV 样例可派生分钟线。

同步复权、涨跌停和停牌：

```bash
./scripts/sync_market_constraints.py \
  --provider csv \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ
```

生成每日可交易股票池：

```bash
./scripts/build_tradable_universe.py \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ
```

导出价格矩阵：

```bash
./scripts/export_price_matrix.py \
  --symbols 600519.SH,000001.SZ \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --field close \
  --output raw/exports/close_matrix.csv
```

CSV 导出不需要额外依赖；Parquet 导出需要安装 `qdata[export]` 或提供 `pandas + pyarrow`。

同步分钟线 Alpha：

```bash
./scripts/sync_minute_market.py \
  --provider csv \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ
```

SDK 可直接获取可交易股票池：

```python
from qdata import Client

client = Client(backend="sql", default_format="records")
rows = client.get_tradable_universe(asof_date="2024-01-04", symbols=["600519.SH", "000001.SZ"])
```

## A 股量化服务 Epsilon

Epsilon 阶段把数据底座从“可入库、可查询”推进到“可多源校验、可服务化、可审计”：

- 多源融合：`qdata.fusion` 支持主备源字段级 diff、coverage/conflict rate、主源失败 fallback。
- 备源样例：`csv_mirror` 用同一 CSV 样本模拟第二来源，可用 `close_offset_bps` 制造可复现冲突。
- 冲突落库：`qmeta.data_conflict_daily` 记录 symbol/date/field 级冲突，`qmeta.multi_source_quality_daily` 记录每日质量汇总。
- REST API：`scripts/run_api_server.py` 提供 `/price`、`/constraints`、`/tradable-universe`、`/matrix`。
- 权限审计：支持 Bearer token / `X-API-Token`、分钟级配额、`qmeta.api_token` 和 `qmeta.api_request_audit`。
- 批量格式：REST 支持 JSON/CSV，Arrow 为可选路径，安装 `qdata[export]` 后启用。

多源比较 dry-run：

```bash
./scripts/compare_daily_sources.py \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ \
  --dry-run
```

写入冲突和多源质量日报：

```bash
./scripts/compare_daily_sources.py \
  --trade-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ
```

启动 REST API：

```bash
./scripts/run_api_server.py \
  --backend sql \
  --port 18080 \
  --tokens devtoken
```

REST smoke：

```bash
./scripts/smoke_api_server.py \
  --base-url http://127.0.0.1:18080 \
  --token devtoken \
  --start-date 2024-01-02 \
  --end-date 2024-01-02 \
  --asof-date 2024-01-02 \
  --symbols 600519.SH,000001.SZ
```

## A 股量化运维 Zeta

Zeta 阶段把平台推进到“每天跑完以后能自己说清楚状态”的生产雏形：

- 运维看板：汇总 pipeline run、repair queue、watermark、质量检查、多源冲突、API 审计和告警。
- SLA 策略：`qmeta.sla_policy` 定义完整率、冲突率、API 错误率、耗时和完成时间目标。
- 告警事件：`qmeta.alert_event` 按 policy/date/metric 幂等写入 open/ack/resolved/ignored 状态。
- 看板快照：`qmeta.ops_dashboard_snapshot` 固化每日窗口摘要，后续可直接做页面或日报。
- API 审计报表：按接口、状态、格式、耗时聚合 `qmeta.api_request_audit`。

生成运维看板并写快照：

```bash
./scripts/report_ops_dashboard.py \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --dataset-code daily_bar \
  --write-snapshot
```

创建并检查 SLA 告警：

```bash
./scripts/check_sla_alerts.py \
  --policy-code daily_bar_conflict_sla \
  --policy-name "Daily bar conflict SLA" \
  --ensure-policy \
  --dataset-code daily_bar \
  --max-conflict-rate 0.001 \
  --trade-date 2024-01-04
```

查看 API 审计：

```bash
./scripts/report_api_audit.py \
  --start-date 2026-07-24 \
  --end-date 2026-07-24
```

## 供应商接入和压测 Eta

Eta 阶段把“第二数据源”从固定 `csv_mirror` 推进到可接真实 vendor 的 adapter 和评分体系：

- 商业源 adapter：`vendor_http` 支持 HTTP JSON、Bearer/Header/Query/Basic auth、限频、重试和错误归因。
- Fixture smoke：无商业账号时可用同一 adapter 的 fixture 模式验收字段映射、对账和评分。
- 真实开源源：AkShare 可作为真实第二源小样本对账，用 `.venv312` 运行。
- Provider profile：`qmeta.vendor_integration_profile` 记录授权、端点、限频、重试、合同引用和再分发边界。
- Benchmark：`provider_benchmark_run` 记录覆盖率、冲突率、失败率、p50/p95、rows/s。
- 供应商评分：`vendor_quality_score_daily` 输出 coverage/conflict/stability/latency/cost/license 综合分。
- 错误归因：`provider_error_event` 记录 auth、rate_limit、timeout、network、schema 等失败原因。

注册商业源配置：

```bash
./scripts/register_vendor_profile.py \
  --source-code vendor_http \
  --source-name "Commercial HTTP Vendor" \
  --provider-name vendor_http \
  --auth-mode bearer \
  --enabled-datasets daily_bar,adjustment_factor,limit_price_daily \
  --rate-limit-per-min 120
```

用商业 adapter fixture 模式跑 benchmark 并写库：

```bash
./scripts/benchmark_vendor_sources.py \
  --primary-provider csv \
  --secondary-provider vendor_http \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ \
  --write-db
```

用 AkShare 真实开源源跑小样本 benchmark：

```bash
.venv312/bin/python scripts/benchmark_vendor_sources.py \
  --primary-provider csv \
  --secondary-provider akshare \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ \
  --write-db
```

查看供应商评分榜：

```bash
./scripts/report_vendor_scores.py --dataset-code daily_bar
```

## 真实供应商生产化 Theta

Theta 阶段把 Eta 的供应商接入推进到生产化决策链路：

- 生产配置：`vendor_http` 可从 `QDATA_VENDOR_*` 环境变量读取 endpoint、auth、限频、重试和响应行路径。
- 字段映射：`vendor_field_mapping` 记录外部字段、内部字段、单位转换和 transform 规则。
- Profile 状态：供应商 profile 可在 testing/active/paused/retired 间切换。
- 分片压测：`benchmark_vendor_universe.py` 支持全市场股票池、`shard_size`、`max_symbols` 和 5/20/60 交易日窗口。
- Provider SLA：`sla_policy` 增加 vendor score、冲突率、失败率、延迟和错误数阈值。
- 上线决策：`vendor_decision_report` 输出 primary/backup/research_only/reject 建议。

注册字段映射并激活 profile：

```bash
./scripts/register_vendor_field_mapping.py \
  --source-code vendor_http \
  --dataset-code daily_bar

./scripts/activate_vendor_profile.py \
  --source-code vendor_http \
  --provider-name vendor_http \
  --status active
```

运行分片压测并写库：

```bash
./scripts/benchmark_vendor_universe.py \
  --primary-provider csv \
  --secondary-provider vendor_http \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ \
  --shard-size 1 \
  --write-db
```

检查 provider SLA 并生成上线决策：

```bash
./scripts/check_provider_sla_alerts.py \
  --source-code vendor_http \
  --dataset-code daily_bar \
  --trade-date 2024-01-04

./scripts/report_vendor_decisions.py \
  --dataset-code daily_bar \
  --write-db
```

## 生产运营闭环 Iota

Iota 阶段把平台从“能判断供应商是否可上线”推进到“可按租户真实运营”：

- 租户权限：`tenant/project/principal/project_member/dataset_access_policy` 记录项目级和主体级数据集 ACL。
- 数据库 token：`api_token` 可绑定租户、项目、主体和成本中心，REST 查询自动做 dataset ACL 校验。
- 用量计量：`api_request_audit` 增加租户上下文和 `cost_units`，`api_usage_daily` 形成日粒度计费/成本分摊报表。
- 告警通知：`notification_channel` 和 `alert_notification_delivery` 支持 stdout/webhook/飞书/邮件通道的投递记录。
- 压测调度：`vendor_benchmark_schedule` 固化供应商 benchmark 参数，并能一键运行和回写最新 suite。
- 字段映射扩展：默认映射覆盖 `daily_bar`、`adjustment_factor`、`limit_price_daily` 和 `security_master`。

初始化租户、项目、主体、token 和数据集权限：

```bash
./scripts/bootstrap_iota_security.py \
  --tenant-code demo \
  --project-code quant-research \
  --principal-code research-bot \
  --token iotatoken \
  --datasets daily_bar,limit_price_daily,tradable_universe
```

注册通知通道并投递 open 告警：

```bash
./scripts/register_notification_channel.py \
  --channel-code stdout-high \
  --channel-type stdout \
  --min-severity high

./scripts/send_alert_notifications.py \
  --channel-code stdout-high
```

使用数据库 token 跑 REST smoke 并汇总用量：

```bash
./scripts/run_api_server.py --backend sql --port 18081

./scripts/smoke_api_server.py \
  --base-url http://127.0.0.1:18081 \
  --token iotatoken \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --asof-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ

./scripts/report_api_usage.py \
  --trade-date 2026-07-24 \
  --rollup \
  --project-code quant-research
```

登记并运行供应商压测调度：

```bash
./scripts/manage_vendor_benchmark_schedule.py \
  --schedule-code daily_bar_vendor_fixture_schedule \
  --run-now
```

## 运营管理 API Kappa

Kappa 阶段把 Iota 的底层运营表变成统一只读入口：

- 管理 API：`/admin/overview`、`/admin/tenants`、`/admin/projects`、`/admin/principals`、`/admin/tokens`、`/admin/dataset-access`、`/admin/notification-deliveries`、`/admin/vendor-schedules`、`/admin/worker-runs`、`/admin/worker-schedules`、`/admin/worker-locks`、`/admin/worker-heartbeats`、`/admin/worker-schedule-ticks`。
- 用量 API：`/usage/daily` 支持按日期、tenant、project、principal 和 API 名称过滤。
- 内部运营台：`/admin/console` 返回一个轻量只读 HTML 页面，展示用量、通知投递和供应商调度。
- 鉴权：Kappa 路径需要 `admin` scope；普通量化数据查询仍只需要 `read` scope。
- CLI：`report_kappa_admin.py` 可直接查看 Kappa 资源，`smoke_kappa_admin_api.py` 可对运行中的 API 服务做真机 smoke。

给本地 DB token 增加 admin scope：

```bash
./scripts/bootstrap_iota_security.py \
  --token iotatoken \
  --scopes read,admin
```

启动服务并跑 Kappa smoke：

```bash
./scripts/run_api_server.py --backend sql --port 18084

./scripts/smoke_kappa_admin_api.py \
  --base-url http://127.0.0.1:18084 \
  --token iotatoken \
  --trade-date 2026-07-24
```

只读 CLI 查询：

```bash
./scripts/report_kappa_admin.py --resource overview
./scripts/report_kappa_admin.py --resource usage-daily --trade-date 2026-07-24 --project-code quant-research
./scripts/report_kappa_admin.py --resource notification-deliveries --limit 20
./scripts/report_kappa_admin.py --resource worker-schedules --limit 10
```

## 后台自动化 Worker Lambda

Lambda 阶段把 Iota/Kappa 里的手动运营动作收进统一后台 worker：

- `usage_rollup`：把 `api_request_audit` 聚合到 `api_usage_daily`。
- `alert_dispatch`：扫描 open alert，按通知通道投递并写 `alert_notification_delivery`。
- `vendor_benchmark_schedule`：扫描到期或指定的 `vendor_benchmark_schedule`，运行 Theta suite 并回写最近 suite。
- 运行记录：`worker_run` 记录整次 worker 状态，`worker_task_run` 记录每个 task 的处理数、失败数、warning 数和错误。
- Kappa 可观测：`/admin/worker-runs` 和 `/admin/console` 可查看最近 worker 结果。

dry-run 预览用量和告警：

```bash
./scripts/run_lambda_worker.py \
  --task usage_rollup \
  --task alert_dispatch \
  --trade-date 2026-07-24 \
  --channel-code stdout-high \
  --dry-run
```

真实跑完整运营闭环：

```bash
./scripts/run_lambda_worker.py \
  --once \
  --trade-date 2026-07-24 \
  --channel-code stdout-high \
  --schedule-code daily_bar_vendor_fixture_schedule

./scripts/report_kappa_admin.py --resource worker-runs --limit 5
```

## 后台调度器 Mu

Mu 阶段把 Lambda worker 接进可长期运行的调度器：

- `worker_schedule`：保存 `usage_rollup`、`alert_dispatch`、`vendor_benchmark_schedule` 的调度配置。
- `worker_lock`：按 `schedule_code` 抢锁，防止多实例重复执行。
- `worker_heartbeat`：记录 scheduler 实例心跳和停止状态。
- `worker_schedule_tick`：记录每次调度扫描、锁状态和触发的 `worker_run_id`。
- Kappa 可观测：`/admin/worker-schedules`、`/admin/worker-locks`、`/admin/worker-heartbeats`、`/admin/worker-schedule-ticks` 和 `/admin/console`。

本地强制某个 schedule 到期并跑一次：

```bash
./scripts/run_mu_scheduler.py \
  --schedule-code mu_usage_rollup_5m \
  --once \
  --force-due \
  --trade-date 2026-07-24
```

完整 smoke：

```bash
./scripts/smoke_mu_scheduler.py \
  --schedule-code mu_usage_rollup_5m \
  --scheduler-id mu-smoke \
  --trade-date 2026-07-24
```

Docker profile 方式验证容器内调度：

```bash
docker compose --profile scheduler run --rm mu-scheduler sh -lc \
  "python -m pip install --no-cache-dir --target /tmp/qdata-deps 'psycopg[binary]>=3.1' >/tmp/qdata-mu-pip.log \
  && PYTHONPATH=/tmp/qdata-deps:/app python scripts/run_mu_scheduler.py --schedule-code mu_alert_dispatch_1m --once --force-due --json"
```

查看调度状态：

```bash
./scripts/report_kappa_admin.py --resource worker-schedules --limit 10
./scripts/report_kappa_admin.py --resource worker-schedule-ticks --limit 5
./scripts/report_kappa_admin.py --resource worker-heartbeats --limit 5
```

## 标准部署与健康巡检 Nu

Nu 阶段把本地系统整理成可部署、可巡检、可回滚的标准拓扑：

- Compose profiles：`app` 运行 `qdata-api`，`scheduler` 运行 `mu-scheduler`。
- 发布元数据：`deployment_release` 记录 release 状态。
- 健康快照：`deployment_health_snapshot` 记录总状态和成功/失败计数。
- 检查明细：`deployment_health_check` 记录 Postgres、migration、ClickHouse、API、scheduler、Kappa 每项检查。
- 部署事件：`deployment_event` 记录 health_check、rollback 等事件。
- Kappa 可观测：`/admin/deployment-releases`、`/admin/deployment-health`、`/admin/deployment-health-checks`、`/admin/deployment-events`。

本地部署：

```bash
./scripts/deploy_nu_local.sh
```

Docker app/scheduler profile 默认使用 `https://pypi.tuna.tsinghua.edu.cn/simple` 安装容器内 Python 依赖，避免当前网络下直连 PyPI 官方源出现 SSL EOF。需要切换镜像源时，可设置：

```bash
QDATA_PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple ./scripts/deploy_nu_local.sh
```

只跑健康检查并写库：

```bash
./scripts/check_nu_health.py \
  --environment local \
  --release-code nu-local-smoke-20260726 \
  --api-base-url http://127.0.0.1:18085 \
  --api-token iotatoken \
  --write-db
```

查看部署健康：

```bash
./scripts/report_kappa_admin.py --resource deployment-releases --limit 5
./scripts/report_kappa_admin.py --resource deployment-health --limit 5
./scripts/report_kappa_admin.py --resource deployment-health-checks --limit 10
```

非破坏性回滚：

```bash
./scripts/rollback_nu_local.sh
```

## 数据产品与预算告警 Xi

Xi 阶段把平台从内部数据库推进到可商业化的数据产品：

- 产品目录：`data_product`、`data_product_dataset`、`data_product_api` 描述可售产品包、数据集和 API。
- 价格体系：`pricing_plan`、`pricing_rule` 支持按 cost unit、请求数、行数、导出或月费计价。
- 项目订阅：`product_subscription` 把 tenant/project 绑定到产品和价格计划。
- 预算治理：`budget_policy`、`budget_usage_snapshot`、`budget_alert` 记录预算、周期用量和告警状态。
- API hard limit：DB token 带租户上下文时，超硬预算的请求会在查询前被拦截。
- Kappa 可观测：`/admin/data-products`、`/admin/pricing-plans`、`/admin/pricing-rules`、`/admin/product-subscriptions`、`/admin/budget-policies`、`/admin/budget-usage`、`/admin/budget-alerts`。

初始化默认商业目录并评估预算：

```bash
./scripts/bootstrap_xi_commercial.py \
  --evaluate \
  --write-alerts \
  --as-of-date 2026-07-26
```

查看 Xi 资源：

```bash
./scripts/report_xi_billing.py --resource products
./scripts/report_xi_billing.py --resource budget-usage
./scripts/report_xi_billing.py --resource budget-alerts
./scripts/report_kappa_admin.py --resource budget-alerts --limit 10
```

Beta-2 阶段验收快照：

- 产品：`a_share_daily_core`，覆盖 4 个 dataset 和 4 个 API。
- 价格计划：`quant_starter_monthly`，按 `cost_unit * 0.01` 计费。
- 预算：`demo_quant-research_monthly_budget`，月预算 `0.15 CNY`。
- 最新预算快照：usage=`0.16002800`，usage_pct=`1.06685333`，status=`exceeded`。
- 当前 open 预算告警：`budget_exceeded`，severity=`high`。

## 月度账单与收入回款 Omicron

Omicron 阶段把 Xi 的产品订阅和 Iota 的用量日报转成可对账账单：

- 账单主表：`invoice` 记录客户、项目、订阅、账期、应收、实收、未收和状态。
- 账单明细：`invoice_line` 按 billable API 和价格规则拆分 request/row/cost_unit/export/monthly_fee/base_fee。
- 账单事件：`invoice_event` 记录生成、开票、回款、逾期和作废动作。
- Kappa 可观测：`/admin/invoices`、`/admin/invoice-lines`、`/admin/invoice-events`、`/admin/revenue-summary`。

生成 2026 年 7 月账单：

```bash
./scripts/generate_omicron_invoices.py \
  --period-start 2026-07-01 \
  --period-end 2026-07-31 \
  --tenant-code demo \
  --project-code quant-research
```

查看账单和收入汇总：

```bash
./scripts/report_omicron_revenue.py --resource invoices
./scripts/report_omicron_revenue.py --resource invoice-lines
./scripts/report_omicron_revenue.py --resource revenue-summary
./scripts/report_kappa_admin.py --resource invoices --limit 10
```

更新回款状态：

```bash
./scripts/update_omicron_invoice_status.py \
  --invoice-code inv-demo-quant-research-a_share_daily_core-20260701-20260731 \
  --status paid
```

当前本地验收状态：

- 账单：`inv-demo-quant-research-a_share_daily_core-20260701-20260731`。
- 明细：4 条，分别来自 `constraints`、`matrix`、`price`、`tradable-universe`。
- 金额：total=`0.16002800`、paid=`0.16002800`、outstanding=`0.00000000`。
- Kappa overview：invoice_month_count=`1`、overdue_invoice_count=`0`。

## 供应商上线复核 Pi

Pi 阶段把 Theta 的分片压测结果变成 5/20/60 窗口上线复核：

- 复核总结：`vendor_readiness_review` 记录供应商、数据集、必要窗口、上线建议和推荐角色。
- 窗口明细：`vendor_readiness_window` 记录每个窗口对应 suite、覆盖率、冲突率、失败率、延迟和吞吐。
- 复核脚本：`report_pi_vendor_readiness.py` 读取最新 suite 并生成 readiness 结论。
- Kappa 可观测：`/admin/vendor-readiness`、`/admin/vendor-readiness-windows`。

跑 5/20/60 窗口压测后生成复核：

```bash
for days in 5 20 60; do
  ./scripts/benchmark_vendor_universe.py \
    --primary-provider csv \
    --secondary-provider vendor_http \
    --start-date 2024-01-04 \
    --end-date 2024-01-04 \
    --target-trade-days "$days" \
    --symbols 600519.SH,000001.SZ \
    --shard-size 1 \
    --write-db
done

./scripts/report_pi_vendor_readiness.py \
  --dataset-code daily_bar \
  --source-code vendor_http \
  --primary-source-code csv \
  --windows 5,20,60
```

查看 Pi 结果：

```bash
./scripts/report_kappa_admin.py --resource vendor-readiness --source-code vendor_http
./scripts/report_kappa_admin.py --resource vendor-readiness-windows --source-code vendor_http
```

当前本地验收状态：

- Pi review：`pi-readiness-vendor_http-daily_bar-20260726-5-20-60d`。
- suite：5/20/60 三个窗口均已写库。
- 结论：status=`watch`、recommendation=`approve_backup`、role=`backup`。
- 原因：fixture vendor 覆盖率为 1、失败率为 0，但冲突率 `0.16666667` 高于主源阈值 `0.005`。

## 收入对账和客户健康 Rho

Rho 阶段把 Omicron 账单、Xi 价格规则和 Iota 用量日报合并成经营复核：

- 收入对账：`revenue_reconciliation_run` 保存账单重算和已开票金额差异。
- 行级差异：`revenue_reconciliation_line` 保存 API/指标级金额、数量和差异状态。
- 应收账龄：`ar_aging_snapshot` 保存 current、1-30、31-60、61-90、90+ 分桶。
- 客户健康：`customer_health_snapshot` 保存 usage recency、付款风险、留存信号和 health score。
- Kappa 可观测：`/admin/revenue-reconciliation`、`/admin/revenue-reconciliation-lines`、`/admin/ar-aging`、`/admin/customer-health`。

生成 Rho 快照：

```bash
./scripts/report_rho_revenue.py \
  --resource generate-all \
  --period-start 2026-07-01 \
  --period-end 2026-07-31 \
  --as-of-date 2026-07-26 \
  --tenant-code demo \
  --project-code quant-research
```

查看 Rho 结果：

```bash
./scripts/report_kappa_admin.py --resource revenue-reconciliation --tenant-code demo
./scripts/report_kappa_admin.py --resource revenue-reconciliation-lines --reconciliation-code rho-recon-demo-quant-research-a_share_daily_core-20260701-20260731-20260726
./scripts/report_kappa_admin.py --resource ar-aging --as-of-date 2026-07-26
./scripts/report_kappa_admin.py --resource customer-health --as-of-date 2026-07-26
```

当前本地验收状态：

- 对账：`rho-recon-demo-quant-research-a_share_daily_core-20260701-20260731-20260726`。
- 结论：status=`matched`，invoice_total=`0.16002800`，recomputed_total=`0.16002800`，amount_delta=`0`。
- 明细：4 条，`constraints`、`matrix`、`price`、`tradable-universe` 均 matched。
- AR aging：status=`current`，outstanding=`0`，overdue_invoice_count=`0`。
- 客户健康：status=`active`，retention_signal=`healthy`，health_score=`100`。

## 运行可观测和容量预警 Sigma

Sigma 阶段把系统从“功能可用”推进到“长期运行可观察”：

- 运行日志：`runtime_log` 保存环境、组件、服务、严重级别、事件类型和 trace/request 信息。
- 运行指标：`runtime_metric_snapshot` 保存 API、worker、alerting、billing、revenue、Postgres 等组件的指标值、单位、阈值和状态。
- 运行日报：`runtime_daily_report` 汇总当日 API 请求/失败率、worker 失败、Nu 部署健康、Pi readiness、Rho 客户风险和容量告警。
- 容量告警：`capacity_alert` 记录开放/恢复状态，并同步写入通用 `alert_event`，方便复用现有通知链路。
- Kappa 可观测：`/admin/runtime-logs`、`/admin/runtime-metrics`、`/admin/runtime-daily-reports`、`/admin/capacity-alerts`。

采集本地运行观测数据：

```bash
./scripts/report_sigma_runtime.py \
  --resource collect \
  --environment local \
  --report-date 2026-07-26
```

查看 Sigma 结果：

```bash
./scripts/report_kappa_admin.py --resource runtime-logs --environment local
./scripts/report_kappa_admin.py --resource runtime-metrics --environment local
./scripts/report_kappa_admin.py --resource runtime-daily-reports --environment local
./scripts/report_kappa_admin.py --resource capacity-alerts --environment local
```

当前本地验收状态：

- 采集：运行日志 1 条、指标 8 条、容量告警 1 条、运行日报 1 条。
- 容量告警：`sigma-capacity-local-api-api-request-count-7d`，metric_value=`271`，threshold=`200`，severity=`medium`，status=`open`。
- 日报：`sigma-runtime-local-20260726`，status=`warning`，api_request_count=`213`，api_failed_count=`0`，open_capacity_alert_count=`1`。
- Kappa overview：runtime_24h_error_log_count=`0`、runtime_metric_warning_count=`1`、runtime_metric_critical_count=`0`、open_capacity_alert_count=`1`、latest_runtime_report_status=`warning`。

## 真实回款、自动匹配和收入 Ledger Tau

Tau 阶段把 Omicron/Rho 的收入闭环接上真实回款流水：

- 回款导入：`payment_import_batch` 和 `payment_transaction` 保存银行/支付/API/demo 流水。
- 自动匹配：从流水备注提取 `inv-*` 发票号，按币种和 outstanding 金额匹配 invoice。
- Ledger：`revenue_ledger_entry` 记录 payment_received、payment_matched、payment_unmatched、refund 和 adjustment 分录。
- 多币种准备：`fx_rate_daily` 保留日汇率，付款表同时保存原币金额和 base 金额。
- Kappa 可观测：`/admin/payment-batches`、`/admin/payments`、`/admin/payment-matches`、`/admin/revenue-ledger`、`/admin/fx-rates`。

跑 Tau demo：

```bash
./scripts/report_tau_payments.py \
  --resource bootstrap-demo \
  --as-of-date 2026-07-27 \
  --tenant-code demo \
  --project-code quant-research \
  --amount 100.00000000
```

查看 Tau 结果：

```bash
./scripts/report_tau_payments.py --resource payment-batches --batch-code tau-demo-payments-20260727
./scripts/report_tau_payments.py --resource payments --batch-code tau-demo-payments-20260727
./scripts/report_tau_payments.py --resource payment-matches --batch-code tau-demo-payments-20260727
./scripts/report_tau_payments.py --resource revenue-ledger --transaction-code tau-pay-tau-demo-payment-20260727
```

当前本地验收状态：

- Migration：`0020_postgresql_payments_tau.sql` 已在 Docker PostgreSQL 真实应用。
- Demo 回款：invoice=`inv-demo-quant-research-a_share_daily_core-tau-20260727`，batch=`tau-demo-payments-20260727`。
- 匹配：matches=`1`，match_type=`auto_exact`，matched_amount=`100.00000000`，invoice_status=`paid`。
- Ledger：同一 transaction 可看到 payment_received 和 payment_matched 两条分录。
- Kappa overview：payment_month_received_amount=`100.00000000`、payment_month_matched_amount=`100.00000000`、unmatched_payment_count=`0`、latest_payment_batch_status=`matched`。

## 前端运营管理台 Upsilon

Upsilon 阶段把 Kappa/Sigma/Tau/Phi/Chi/Psi/Omega 的只读运营能力做成一个可直接打开的管理台：

- 浏览器入口：`http://127.0.0.1:18080/` 会跳转到本地 `QData Upsilon Ops Console`。
- API 入口：`/admin/console` 仍支持标准 `Authorization: Bearer <token>` 鉴权。
- 筛选：全局搜索、状态筛选和 All/Runtime/Payments/Revenue/Vendor/Automation/Commercial/Governance/Strategy 分组切换。
- 支付复核：Payments 分组展示回款批次、付款流水、发票匹配、收入 ledger 和 FX rate。
- 运行风险：Runtime 分组展示部署健康、运行指标、运行日报和容量告警。
- 策略决策：Strategy 分组展示 Phi 策略运行、信号、决策和升级事件。
- 治理视图：Governance 分组展示 Chi 权限决策审计、项目治理快照和治理动作。
- 自动执行：Automation 分组展示 Lambda/Mu worker、Psi run/action 和 Omega approval/executor/attempt/rollback。
- 兼容：Kappa JSON/CSV API 和原有量化数据 API 行为保持不变。

启动服务并验证 Upsilon：

```bash
./scripts/run_api_server.py --backend sql --port 18091 --tokens iotatoken --token-scopes read,admin
./scripts/smoke_upsilon_console.py --base-url http://127.0.0.1:18091 --token iotatoken
./scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18091 --token iotatoken --trade-date 2026-07-27
```

当前本地验收状态：

- Upsilon smoke：`upsilon_console=ok html_bytes=71638 markers=22`。
- Kappa smoke：console 返回 HTML，Omega/Psi/Chi/Phi/Tau/Sigma/Rho/Xi/Omicron/Pi 端点均 ok。
- 数据 API smoke：health/price/constraints/tradable/matrix 全部 ok。
- Docker app profile：`qdata-api=healthy`，`18080/devtoken` 下 Upsilon/Kappa/数据 API smoke 均 ok。
- Playwright：桌面截图 `/tmp/phi-upsilon-console-desktop.png`，移动截图 `/tmp/phi-upsilon-console-mobile.png`。
- API audit：requests=`2301`，failed=`3`；3 条失败均为历史浏览器无 token 访问 `/` 或 `/favicon.ico`。

## 统一策略引擎 Phi

Phi 阶段把质量、供应商、运行、商业和回款事实串成可审计的统一策略决策：

- 策略表：`strategy_policy`、`strategy_run`、`strategy_signal`、`strategy_decision`、`strategy_escalation_event`。
- 策略域：data_quality、vendor、runtime、commercial、payment。
- CLI：`report_phi_strategy.py --resource run-all` 生成策略运行、信号、决策和升级事件。
- Kappa：`/admin/strategy-runs`、`/admin/strategy-signals`、`/admin/strategy-decisions`、`/admin/strategy-escalations`。
- Upsilon：Strategy 分组展示策略运行、信号、决策和升级事件。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
./scripts/report_phi_strategy.py --resource run-all --as-of-date 2026-07-27 --environment local --trigger-mode smoke
./scripts/report_kappa_admin.py --resource strategy-decisions --run-code phi-local-20260727
```

当前本地验收状态：

- Phi run：`status=warning`、`highest=high`、`signals=7`、`decisions=5`、`escalations=2`。
- 决策：质量门禁 `hold_production/block`，商业风险 `open_review/escalate`，运行容量 `monitor/review`，供应商 `keep_backup/watch`，回款收入 `monitor/allow`。
- Kappa overview：`latest_strategy_status=warning`、`latest_strategy_severity=high`、`open_strategy_escalation_count=2`。
- Docker Kappa smoke：strategy_runs=1、strategy_signals=7、strategy_decisions=5、strategy_escalations=2。

## 多租户治理 Chi

Chi 阶段把 Iota 的租户权限从“能校验”推进到“可审计、可追责、可运营”：

- 权限边界：ACL 严格按 principal > project > tenant 匹配，主体级策略不会再被同租户其他主体误用。
- 审计表：`access_decision_audit` 记录 allow/deny、effective_scope、access_level、字段拒绝、token、接口和 request_id。
- 项目治理：`project_governance_snapshot` 汇总活跃主体/token/ACL、7 日请求、拒绝访问、预算、账单和开放治理动作。
- 治理动作：`governance_action` 对 warning/critical 项目生成 review_budget、review_access_policy 等可跟进任务。
- Kappa：`/admin/access-decisions`、`/admin/project-governance`、`/admin/governance-actions`。
- Upsilon：Governance 分组展示权限决策、项目治理和治理动作。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
./scripts/report_chi_governance.py --resource evaluate-access --tenant-code demo --project-code quant-research --principal-code research-bot --dataset-code daily_bar --api-name price --fields close,volume --request-id chi-smoke-allow --write-audit
./scripts/report_chi_governance.py --resource evaluate-access --tenant-code demo --project-code quant-research --principal-code research-bot --dataset-code financial_statement --api-name fundamentals --request-id chi-smoke-deny --write-audit
./scripts/report_chi_governance.py --resource collect-snapshots --snapshot-date 2026-07-27 --tenant-code demo --project-code quant-research --write-db --write-actions
./scripts/report_kappa_admin.py --resource project-governance --project-code quant-research
```

当前本地验收状态：

- Migration：`0022_postgresql_governance_chi.sql` 已在 Docker PostgreSQL 真实应用。
- 权限审计：允许 `daily_bar/price`，拒绝 `financial_statement/fundamentals`，access audit 当前可查 6 行。
- 项目治理：`quant-research` 快照 status=`critical`、risk_score=`49.0`、denied_access_7d_count=`1`、budget_status=`exceeded`。
- 治理动作：生成 `review_budget` 高优先级 open action。
- Kappa overview：`access_denied_24h_count=1`、`project_governance_critical_count=1`、`open_governance_action_count=1`。
- Docker Upsilon smoke：`upsilon_console=ok html_bytes=71638 markers=22`。

## 自动化执行层 Psi

Psi 阶段把 Phi 策略决策和 Chi 治理动作接入统一自动化执行队列：

- 执行表：`automation_run` 记录每次 Psi run 的 dry-run/execute、计数、状态和来源过滤。
- 动作表：`automation_action` 记录 action_code、source_type、source_code、action_type、safety_level、approval_required、planned_effect、executed_effect 和 rollback_hint。
- 来源：Phi `strategy_decision` 和 Chi `governance_action`。
- 护栏：默认 `dry_run`；degrade_vendor、repair_data_quality、freeze_budget、rotate_token 等高风险动作在 execute 下需要审批。
- 幂等：同一 source/action_type 使用稳定 idempotency_key，已成功执行的动作再次执行会被跳过。
- Kappa：`/admin/automation-runs`、`/admin/automation-actions`。
- Upsilon：Automation 分组展示 Psi run/action。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
./scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode dry_run
./scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode execute --no-chi --source-run-code phi-local-20260727 --run-code psi-local-20260727-execute-phi-safe
./scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode execute --no-phi --tenant-code demo --project-code quant-research --run-code psi-local-20260727-execute-chi-guard
./scripts/report_kappa_admin.py --resource automation-actions --limit 10
```

当前本地验收状态：

- Migration：`0023_postgresql_automation_psi.sql` 已在 Docker PostgreSQL 真实应用。
- Dry-run：`psi-local-20260727-dry_run` 生成 5 个动作，覆盖 repair_data_quality、degrade_vendor、freeze_budget、notify_owner、escalate_commercial，全部未真实执行。
- Execute：`psi-local-20260727-execute-phi-safe` 成功执行 2 个中风险动作，2 个高风险动作进入 approval_required。
- Chi 护栏：`psi-local-20260727-execute-chi-guard` 的 freeze_budget 高风险动作进入 approval_required，未冻结生产配置。
- Kappa overview：automation_24h_run_count=`4`、automation_24h_action_count=`11`、automation_approval_required_count=`2`、latest_automation_status=`success`。

## 自动化控制层 Omega

Omega 阶段把 Psi 的“待执行动作”推进到生产级控制面：

- 审批：`automation_approval` 记录 pending/approved/rejected/expired/cancelled，拒绝后不会被执行器自动绕过。
- 执行器：`automation_executor` 登记 noop/webhook/script 三类 executor，默认本地 executor 全部为 noop。
- 执行尝试：`automation_execution_attempt` 记录每次 attempt、executor、payload、状态、错误和 retry 计划。
- 重试：失败动作会根据 executor 的 max_retry_count/backoff 写入 retry_scheduled，不会无限重试。
- 回滚：`automation_rollback` 保存 rollback_plan/rollback_result，支持 noop/manual/webhook/script 回滚演练。
- 安全：Kappa 只读查询对 token/secret/password 等嵌套敏感字段做脱敏，接口仍走 admin scope。
- Kappa：`/admin/automation-approvals`、`/admin/automation-executors`、`/admin/automation-attempts`、`/admin/automation-rollbacks`。
- Upsilon：Automation 分组展示 Omega approval/executor/attempt/rollback。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
./scripts/report_omega_control.py --resource execute --run-code psi-local-20260727-execute-phi-safe --trigger-mode smoke --requested-by omega-smoke
./scripts/report_omega_control.py --resource decide-approval --approval-code <approval_code> --decision approved --decided-by platform-lead
./scripts/report_omega_control.py --resource execute --action-code <action_code> --trigger-mode smoke --requested-by omega-smoke
./scripts/report_omega_control.py --resource request-rollback --action-code <action_code> --requested-by omega-smoke --reason "smoke rollback drill"
./scripts/report_omega_control.py --resource run-rollback --rollback-code <rollback_code> --executed-by platform-lead
```

当前本地验收状态：

- Migration：`0024_postgresql_automation_omega.sql` 已在 Docker PostgreSQL 真实应用。
- 审批：Omega 为 3 个高风险 Psi 动作生成 approval，其中 degrade_vendor 已 approved。
- 执行器：默认 11 个 noop executor 可用；smoke 额外注册 1 个 force_fail retry executor。
- 执行：approved degrade_vendor 通过 `omega-noop-degrade-vendor` 成功记录，无真实外部副作用。
- 重试：`omega-smoke-retry-action` 通过 force_fail executor 进入 retry_scheduled。
- 回滚：degrade_vendor 成功动作完成 noop rollback，rollback status=`success`。
- Kappa overview：automation_pending_approval_count=`2`、automation_retry_scheduled_count=`1`、automation_rollback_required_count=`0`、latest_automation_attempt_status=`retry_scheduled`。

## 白名单外部执行沙箱 Alpha-2

Alpha-2 阶段把 Omega 的 webhook/script executor 从“注册可观测”推进到“沙箱内真实 dispatch”：

- 白名单：`automation_executor_allowlist` 记录 executor_type、target_pattern、sandbox_only 和 timeout。
- 密钥引用：`automation_secret_ref` 只保存 secret_ref、kind、owner 和 env_var 元数据，不保存密钥明文。
- 执行器安全字段：`automation_executor` 新增 sandbox_mode、allowlist_code、secret_ref、signing_algorithm 和 allowed_target。
- 脚本沙箱：只允许仓库内相对路径 Python 脚本，禁止绝对路径和 `..` 逃逸。
- Webhook 沙箱：只允许 allowlist URL，支持 HMAC-SHA256 签名，attempt 记录 status_code、响应体摘要和 signed=true/false。
- Kappa：新增 `/admin/automation-allowlists`、`/admin/automation-secrets`，overview 展示 Alpha2 executor/allowlist/secret ref 计数。
- Upsilon：Automation 分组展示 Automation Allowlists 和 Automation Secrets。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
.venv312/bin/python scripts/report_omega_control.py --resource allowlists
.venv312/bin/python scripts/report_omega_control.py --resource secrets
.venv312/bin/python scripts/report_omega_control.py --resource execute --action-code omega-smoke-retry-action --executor-code alpha2-script-notify-owner --allow-external --trigger-mode smoke --requested-by alpha2-smoke
QDATA_ALPHA2_HMAC_SECRET=alpha2-local-secret .venv312/bin/python scripts/report_omega_control.py --resource execute --action-code omega-smoke-retry-action --executor-code alpha2-webhook-notify-owner --allow-external --trigger-mode smoke --requested-by alpha2-smoke
```

当前本地验收状态：

- Migration：`0025_postgresql_automation_alpha2.sql` 已在 Docker PostgreSQL 真实应用。
- Registry：automation executors=`14`，Alpha-2 allowlists=`2`，secret refs=`1`。
- Script sandbox：`alpha2-script-notify-owner` 真实执行成功，returncode=`0`、sandbox_dispatch=`true`、external_side_effect=`false`。
- Webhook sandbox：`alpha2-webhook-notify-owner` 对本地 webhook 真实 POST 成功，status_code=`200`、signed=`true`、sandbox_dispatch=`true`。
- Kappa Admin API smoke：automation_allowlists=`2`、automation_secrets=`1`、automation_executors=`14`、automation_attempts=`9`、console html_bytes=`74772`。
- Upsilon smoke：`upsilon_console=ok html_bytes=74772 markers=24`。
- 根路径：`GET /` 本地开发模式重定向到 `/admin/console?token=devtoken`，浏览器不再只显示 missing bearer token JSON。

## 通知审批联调闭环 Beta-2

Beta-2 阶段把 Alpha-2 的外部执行沙箱升级为可恢复的通知/审批联调闭环：

- 通道：`automation_external_channel` 记录 webhook/飞书/企业微信/邮件等通道的 endpoint、allowlist、secret_ref、retry、重复窗口和 owner。
- Dispatch：`automation_external_dispatch` 记录每次外部通知/审批请求，覆盖 acknowledged、suppressed、retry_scheduled、dead_letter、recovered。
- Runbook：`automation_recovery_runbook` 记录失败类型、严重级别、恢复步骤和回滚步骤。
- 重复抑制：同一 action/channel/dispatch_type 在 duplicate_window 内已有成功 dispatch 时，只写 suppressed，不重复调用外部系统。
- 失败恢复：失败按通道 retry budget 进入 retry_scheduled 或 dead_letter，人工 recovery 会保留原失败证据并写 recovered_by/recovery_reason。
- Kappa：新增 `/admin/automation-channels`、`/admin/automation-dispatches`、`/admin/automation-runbooks`。
- Upsilon：Automation 分组展示 Automation Channels、Automation Dispatches 和 Automation Runbooks。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
.venv312/bin/python scripts/report_beta2_external.py --resource channels
.venv312/bin/python scripts/report_beta2_external.py --resource dispatch --action-code omega-smoke-retry-action --channel-code beta2-local-approval-webhook --allow-external --trigger-mode smoke --requested-by beta2-smoke
.venv312/bin/python scripts/report_beta2_external.py --resource dispatch --action-code omega-smoke-retry-action --channel-code beta2-local-approval-webhook --allow-external --trigger-mode smoke --requested-by beta2-smoke
.venv312/bin/python scripts/report_beta2_external.py --resource dispatch --action-code omega-smoke-retry-action --channel-code beta2-local-deadletter-webhook --allow-external --trigger-mode smoke --requested-by beta2-smoke
.venv312/bin/python scripts/report_beta2_external.py --resource recover --dispatch-code <dead_letter_dispatch_code> --recovered-by beta2-smoke --reason "manual recovery smoke" --runbook-code beta2-webhook-timeout
```

当前本地验收状态：

- Migration：`0026_postgresql_automation_beta2.sql` 已在 Docker PostgreSQL 真实应用。
- Registry：Beta-2 自有 channels=`2`，runbooks=`2`。
- Dispatch：本地 approval webhook 成功 acknowledged；重复触发写入 suppressed，未重复调用外部系统。
- Dead-letter：本地 dead-letter webhook 失败后进入 dead_letter，并可按 `beta2-webhook-timeout` runbook 恢复为 recovered。
- Kappa Admin API smoke：Beta-2 endpoints 已覆盖；Gamma-2 接入后全局 automation_channels=`5`、automation_dispatches=`6`、automation_runbooks=`4`。
- Upsilon smoke：Beta-2 阶段为 `upsilon_console=ok html_bytes=78927 markers=27`；Gamma-2 接入后的当前结果见下文。

## 多环境通道与密钥轮换 Gamma-2

Gamma-2 阶段把 Beta-2 的 dispatch 能力升级成可灰度接真实通知系统的控制面：

- Profile：`automation_channel_profile` 记录 provider_code、environment、dry_run/live endpoint、secret_ref、next_secret_ref、readiness_status 和 owner。
- Validation：`automation_channel_validation` 记录 dry-run、live、secret rotation、rollback drill 的联调结果和 dispatch 证据。
- Rotation：`automation_secret_rotation` 记录 secret_ref -> next_secret_ref 的验证、apply、rollback 和证据 fingerprint。
- 候选密钥验证：`report_gamma2_external.py --resource rotate` 会先用 target_secret_ref 触发签名 dispatch，验证成功后才允许 `--apply-rotation`。
- 本地 smoke：`smoke_gamma2_external.py` 自动启动签名 webhook，完成 current validation、next secret validation、apply、rollback、post-rollback validation。
- Kappa：新增 `/admin/automation-channel-profiles`、`/admin/automation-channel-validations`、`/admin/automation-secret-rotations`。
- Upsilon：Automation 分组展示 Automation Channel Profiles、Automation Channel Validations 和 Automation Secret Rotations。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
.venv312/bin/python scripts/smoke_gamma2_external.py
.venv312/bin/python scripts/report_gamma2_external.py --resource profiles
.venv312/bin/python scripts/report_gamma2_external.py --resource validations --limit 5
.venv312/bin/python scripts/report_gamma2_external.py --resource rotations --limit 5
```

Gamma-2 阶段验收状态：

- Migration：`0027_postgresql_automation_gamma2.sql` 已在 Docker PostgreSQL 真实应用。
- Registry：Gamma-2 profiles=`3`，active secret refs=`3`，automation channels=`5`，runbooks=`4`。
- Smoke：`gamma2_smoke=ok profiles=3 ready_profiles=1 validations=6 rotations=2 current_validation=success rotation=applied rollback=rolled_back post_rollback_validation=success`。
- Rotation：`gamma2-local-hmac-current -> gamma2-local-hmac-next` 候选签名验证成功，apply 后已 rollback，affected_channel_count=`1`。
- Kappa Admin API smoke：Gamma-2 endpoints 已覆盖；Delta-2 接入后的全局当前行数见下文。
- Upsilon smoke：Gamma-2 页面区块已覆盖；Delta-2 接入后的当前控制台验收见下文。
- API audit：Delta-2 接入后的当前审计结果见下文。

## 企业微信 live validation Delta-2

Delta-2 阶段把 Gamma-2 的企业微信 dry-run 通道升级为可控 live validation：

- Live receipt：`automation_live_provider_receipt` 记录企业微信机器人 HTTP 状态、`errcode/errmsg`、请求/响应摘要、发送时间、确认时间和错误原因。
- Endpoint secret：真实企业微信 webhook URL 只从 `QDATA_DELTA2_WECOM_WEBHOOK_URL` 读取；数据库、Kappa API、CLI 和 Upsilon 都只展示 `delta2-wecom-webhook-url` / env var 引用，不保存 URL 明文。
- Safe default：未显式 `--allow-external` 时只写 `blocked` receipt，`external_side_effect=false`，不会向企业微信发消息。
- Require live：`--require-live` 会在缺少 webhook env 时直接失败，避免把本地 blocked 验收误判成真实企业微信联调成功。
- Kappa：新增 `/admin/automation-live-receipts`，overview 展示 live receipt 数、企业微信成功数和最新 receipt 状态。
- Upsilon：Automation 分组展示 Automation Live Receipts，并在顶部展示 Delta2 Live/WeCom/Receipt。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
.venv312/bin/python scripts/smoke_delta2_wecom.py
export QDATA_DELTA2_WECOM_WEBHOOK_URL='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=replace-with-wecom-robot-key'
.venv312/bin/python scripts/smoke_delta2_wecom.py --allow-external --require-live
.venv312/bin/python scripts/report_delta2_wecom.py --resource receipts --profile-code delta2-wecom-live-profile --provider-code wecom --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource automation-live-receipts --limit 5
```

当前本地验收状态：

- Migration：`0028_postgresql_automation_delta2.sql` 已在 Docker PostgreSQL 真实应用。
- Registry：active automation secret refs=`4`，automation channels=`6`，automation profiles=`4`，runbooks=`5`。
- Safe smoke：`delta2_wecom_smoke=ok mode=blocked status=blocked ... provider_errcode=None`，当前已写入 2 条 blocked receipt。
- Require-live 保护：当前 shell 未配置 `QDATA_DELTA2_WECOM_WEBHOOK_URL`，`--allow-external --require-live` 正确失败为 `missing_env`，所以本轮没有向真实企业微信群发送消息。
- Kappa Admin API smoke：`automation_live_receipts=ok rows=2`，overview 输出 `automation_24h_live_receipt_count=2`、`automation_24h_wecom_success_count=0`、`latest_automation_live_receipt_status=blocked`。
- Upsilon smoke：`upsilon_console=ok html_bytes=93565 markers=31`。
- 根路径：`GET /` 返回 `302 Location: /admin/console?token=devtoken`，浏览器打开 `http://127.0.0.1:18080/` 不再停在 missing bearer token JSON。
- API audit：requests=`2630`，failed=`4`；失败均为无 Bearer token 的浏览器/curl 验证访问。

## 真实供应商 Live Gate Epsilon-3

Epsilon-3 阶段把 Pi 的 5/20/60 供应商 readiness 结论升级为真实 vendor token 上线门禁：

- Gate：`vendor_live_gate_run` 记录每次真实供应商门禁的 run_mode、status、必需窗口、已执行窗口、profile/review/suite 证据和阻塞原因。
- Env-only：真实供应商 `BASE_URL` 和 `TOKEN` 只从 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 读取，不写入数据库、Kappa 输出或 Upsilon HTML。
- Safe default：未显式 `--allow-live` 时只写 blocked gate，不调用外部供应商。
- Require live：`--require-live` 会在缺少真实供应商环境时失败，避免把本地 blocked smoke 误判为真实 vendor 联调成功。
- Profile aware：如果未显式设置 `QDATA_VENDOR_AUTH_MODE`，Epsilon-3 会继承 DB vendor profile 的 `auth_mode`，当前默认 bearer，因此缺 token 会被识别为阻塞。
- Kappa：新增 `/admin/vendor-live-gates`，overview 展示 Vendor Gates、Gate Blocked、Gate Live 和 Gate Status。
- Upsilon：Vendor 分组展示 Vendor Live Gates 表。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
.venv312/bin/python scripts/smoke_epsilon3_vendor_live_gate.py
.venv312/bin/python scripts/smoke_epsilon3_vendor_live_gate.py --allow-live --require-live
.venv312/bin/python scripts/run_epsilon3_vendor_live_gate.py --resource runs --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-gates --limit 5
```

当前本地验收状态：

- Migration：`0029_postgresql_vendor_epsilon3_live_gate.sql` 已在 Docker PostgreSQL 真实应用。
- Safe smoke：`epsilon3_vendor_live_gate_smoke=ok mode=blocked status=blocked ... live_base_url_present=False live_token_present=False`，最新 blocked gate 已落库。
- Require-live 保护：当前 shell 未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`，`--allow-live --require-live` 正确失败为 `missing_vendor_live_env`，所以本轮没有调用真实外部供应商。
- Kappa：`vendor-live-gates --limit 5` 可查最近 blocked gate；Eta-3 编排后 overview 输出 `vendor_24h_live_gate_count=18`、`vendor_24h_live_gate_blocked_count=18`、`vendor_24h_live_gate_executed_count=0`、`latest_vendor_live_gate_status=blocked`。
- Upsilon smoke：`upsilon_console=ok html_bytes=123188 markers=31`，Vendor 分组已渲染 Vendor Live Gates、Vendor Onboarding 和 Vendor Live Closure 表。
- 根路径：`GET /` 返回 `302 Location: /admin/console?token=devtoken`。
- API audit：requests=`5833`，failed=`5`；失败主要为无 Bearer token 的浏览器/curl 验证访问。

## 真实供应商 Onboarding Zeta-3

Zeta-3 阶段把 Epsilon-3 的单次 live gate 扩成真实供应商接入流程：

- Run：`vendor_onboarding_run` 记录 env/profile/contract/rate limit/dataset 预检、金丝雀、gate、编排状态和推荐角色。
- Dataset result：`vendor_onboarding_dataset_result` 记录 daily_bar、security_master、adjustment_factor、limit_price_daily 每个数据集的阻塞原因、next action 和关联 gate。
- Safe default：未显式 `--allow-live --run-benchmarks` 时只写 blocked 审计，不调用外部供应商。
- Require live：`--require-live` 会在缺少真实供应商环境时失败，避免把本地 blocked smoke 误判为真实联调成功。
- Kappa：新增 `/admin/vendor-onboarding-runs` 和 `/admin/vendor-onboarding-results`，overview 展示 Onboarding、Onboard Blocked 和 Onboard Status。
- Upsilon：Vendor 分组展示 Vendor Onboarding Runs、Vendor Onboarding Results 和 Vendor Live Gates。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
.venv312/bin/python scripts/smoke_zeta3_vendor_onboarding.py
.venv312/bin/python scripts/smoke_zeta3_vendor_onboarding.py --allow-live --require-live
.venv312/bin/python scripts/run_zeta3_vendor_onboarding.py --resource runs --limit 5
.venv312/bin/python scripts/run_zeta3_vendor_onboarding.py --resource results --limit 20
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-onboarding-runs --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-onboarding-results --limit 20
```

当前本地验收状态：

- Migration：`0030_postgresql_vendor_zeta3_onboarding.sql` 已在 Docker PostgreSQL 真实应用。
- Safe smoke：`zeta3_vendor_onboarding_smoke=ok mode=blocked status=blocked run_code=zeta3-onboarding-vendor_http-blocked-5d289f7340 dataset_count=4 gate_count=4 live_base_url_present=False live_token_present=False`；Theta-3 编排后当前 6 条 onboarding run 和 24 条 dataset result 已落库。
- Require-live 保护：当前 shell 未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`，`--allow-live --require-live` 正确失败为 `missing_vendor_live_env`，本轮没有调用真实外部供应商。
- Query：`run_zeta3_vendor_onboarding.py --resource runs` 输出 blocked onboarding run；`--resource results --limit 100` 当前输出 24 条 blocked dataset result，其中 `security_master` 被明确标记为 `dataset_not_enabled:security_master`。
- Kappa/Upsilon：`vendor_onboarding_runs=ok rows=6`、`vendor_onboarding_results=ok rows=24`、`vendor_live_gates=ok rows=26`，Vendor 分组已新增 Vendor Onboarding Runs、Vendor Onboarding Results、Eta-3 Live Closure 和 Theta-3 Live Pilot 表。

## 真实供应商 Live Closure Eta-3

Eta-3 阶段把 Zeta-3 onboarding 再向前推一步，形成真实供应商 live 接入闭环：

- Closure：`vendor_live_closure_run` 记录 profile、合同、再分发、限频、endpoint probe、onboarding、promotion 和推荐角色。
- Endpoint probe：`vendor_live_endpoint_probe` 按 daily_bar、security_master、adjustment_factor、limit_price_daily 记录 endpoint path、auth/schema 状态、missing fields 和阻塞原因。
- Safe default：未显式 `--allow-live` 时只写 blocked 审计，不调用外部供应商。
- Profile guard：只有显式 `--allow-profile-write` 才会更新供应商 profile 的 endpoint、dataset、合同、授权、限频或 active 状态。
- Require live：`--require-live` 会在缺少真实供应商 env、合同、授权、限频或必要 dataset/profile 条件时失败，避免把本地 blocked smoke 误判为真实联调成功。
- Kappa：新增 `/admin/vendor-live-closures` 和 `/admin/vendor-live-probes`，overview 展示 Live Closures、Closure Blocked 和 Closure Status。
- Upsilon：Vendor 分组展示 Vendor Live Closures 和 Vendor Live Probes。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
.venv312/bin/python scripts/smoke_eta3_vendor_live_closure.py
.venv312/bin/python scripts/smoke_eta3_vendor_live_closure.py --allow-live --require-live
.venv312/bin/python scripts/run_eta3_vendor_live_closure.py --resource runs --limit 5
.venv312/bin/python scripts/run_eta3_vendor_live_closure.py --resource probes --limit 10
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-closures --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-probes --limit 10
```

真实供应商 profile 激活示例：

```bash
.venv312/bin/python scripts/run_eta3_vendor_live_closure.py \
  --resource run \
  --allow-profile-write \
  --activate-profile \
  --enable-profile-datasets \
  --commercial-contract-ref <contract_ref> \
  --redistribution-allowed true \
  --rate-limit-per-min <rate_limit> \
  --allow-live \
  --run-endpoint-probes \
  --run-benchmarks
```

当前本地验收状态：

- Migration：`0031_postgresql_vendor_eta3_live_closure.sql` 已在 Docker PostgreSQL 真实应用。
- Safe smoke：`eta3_vendor_live_closure_smoke=ok mode=blocked status=blocked closure_code=eta3-live-closure-vendor_http-blocked-b7fcf54a19 probe_count=4 onboarding_status=blocked live_base_url_present=False live_token_present=False`，只写 closure/probe/onboarding 审计，没有真实外部供应商请求。
- Require-live 保护：当前 shell 未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`，`--allow-live --require-live` 正确失败为 `missing_vendor_live_env`。
- Query：`run_eta3_vendor_live_closure.py --resource runs` 输出 4 条 blocked closure；`--resource probes` 输出 16 条 probe，其中最新 `daily_bar` probe 已检查 `close/symbol/trade_date`，`security_master` 会记录 `dataset_not_enabled:security_master`。
- Kappa/Upsilon：`vendor_live_closures=ok rows=4`、`vendor_live_probes=ok rows=16`，Vendor 分组已新增 Vendor Live Closures 和 Vendor Live Probes。`/tmp/theta3-upsilon-desktop.png` 和 `/tmp/theta3-upsilon-mobile.png` 已生成并非空。

## 真实供应商 Live Pilot Theta-3

Theta-3 阶段把 Eta-3 closure 变成真实供应商试运行批次：

- Pilot run：`vendor_live_pilot_run` 记录 pilot_scope、closure/onboarding/endpoint/benchmark 状态、signoff_status、recommendation、risk_level 和 dataset 聚合计数。
- Dataset result：`vendor_live_pilot_dataset_result` 按 daily_bar、security_master、adjustment_factor、limit_price_daily 记录 closure/probe/gate/schema/benchmark 证据和阻塞原因。
- Safe default：默认复用 Eta-3 blocked closure 证据，只写审计，不调用外部供应商。
- Require live：`--allow-live --require-live` 会在缺少真实供应商 env、合同、授权、限频、schema 或 onboarding 条件时失败。
- Kappa：新增 `/admin/vendor-live-pilots` 和 `/admin/vendor-live-pilot-results`，overview 展示 Live Pilots、Pilot Blocked 和 Pilot Status。
- Upsilon：Vendor 分组展示 Vendor Live Pilots 和 Vendor Live Pilot Results。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
.venv312/bin/python scripts/smoke_theta3_vendor_live_pilot.py
.venv312/bin/python scripts/smoke_theta3_vendor_live_pilot.py --allow-live --require-live
.venv312/bin/python scripts/run_theta3_vendor_live_pilot.py --resource runs --limit 5
.venv312/bin/python scripts/run_theta3_vendor_live_pilot.py --resource results --limit 20
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-pilots --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-pilot-results --limit 20
```

当前本地验收状态：

- Migration：`0032_postgresql_vendor_theta3_live_pilot.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback。
- Safe smoke：`theta3_vendor_live_pilot_smoke=ok mode=blocked status=blocked pilot_code=theta3-live-pilot-vendor_http-blocked-b7f52ed98c closure_status=blocked dataset_count=4 signoff_status=not_ready risk_level=high live_base_url_present=False live_token_present=False`，没有真实外部供应商请求。
- Require-live 保护：当前 shell 未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`，`--allow-live --require-live` 正确失败为 `theta3_vendor_live_pilot_smoke=failed reason=missing_vendor_live_env`。
- Query：`run_theta3_vendor_live_pilot.py --resource runs` 输出 2 条 blocked pilot；`--resource results` 输出 8 条 dataset result，覆盖 4 个数据集的 closure/probe/gate 证据。
- Kappa/Upsilon：`vendor_live_pilots=ok rows=2`、`vendor_live_pilot_results=ok rows=8`，Vendor 分组已新增 Vendor Live Pilots 和 Vendor Live Pilot Results；`/tmp/theta3-upsilon-desktop.png` 和 `/tmp/theta3-upsilon-mobile.png` 已生成并非空。

## 免费源联盟 Free Source Fabric Iota-3

Iota-3 阶段把免费源做成研发、备份和校验层：

- Candidate catalog：登记 `csv/csv_mirror/akshare/baostock/tushare_free/cninfo_public/sse_public/szse_public/nbs_public`，记录 provider、外部调用、授权状态和覆盖数据集。
- Fabric run：`free_source_fabric_run` 记录 source_codes、dataset_codes、coverage_rate、conflict_rate_bps、license_review_required_count、recommendation 和 risk_level。
- Dataset result：`free_source_fabric_dataset_result` 按数据集记录 coverage_status、consistency_status、license_status、freshness_status、baseline_source_code 和 source evidence。
- Safe default：默认只跑本地 `csv/csv_mirror`，不调用外部免费网站。
- External guard：只有显式 `--allow-external` 后才允许试运行 AKShare 等外部免费源；`--require-commercial-clearance` 打开时，research_only/review_required 源不会被误推为生产主源。
- Kappa/Upsilon：新增 `/admin/free-source-fabric-runs`、`/admin/free-source-fabric-results` 和 Free Sources 分组。

本地运行：

```bash
./scripts/apply_postgres_migrations.sh
.venv312/bin/python scripts/run_iota3_free_source_fabric.py --resource catalog
.venv312/bin/python scripts/smoke_iota3_free_source_fabric.py
.venv312/bin/python scripts/run_iota3_free_source_fabric.py --resource run --dataset-codes daily_bar --csv-mirror-close-offset-bps 10
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-runs --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-results --limit 20
```

当前本地验收状态：

- Migration：`0033_postgresql_free_source_iota3_fabric.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback。
- Safe smoke：默认使用 `csv/csv_mirror`，当前输出 status=`success`、dataset_count=`5`、coverage_rate=`1.000000`、conflict_rate_bps=`0.000000`，无外部副作用。
- Conflict smoke：`--csv-mirror-close-offset-bps 10` 会让 daily_bar result 进入 consistency warning，用于验证免费源冲突检测链路。
- Kappa/Upsilon：Iota-5 canary 后当前 Free Sources 分组已展示 Free Source Fabric Runs 和 Free Source Fabric Results，Iota-5 degraded run 已可通过 Kappa 查询。

## 外部免费源真实 Canary Iota-4

Iota-4 阶段把 AKShare 从“候选目录”推进到“真实外部 canary”：

- Live-only canary：默认只跑 `akshare`，验证外部免费源真实请求、字段解析、覆盖率和 fabric 审计落库。
- Compare-local canary：可跑 `csv/csv_mirror/akshare`，验证 AKShare 能进入多源 fabric 比对；本地 fixture 只用于研发对照，不作为真实价格基准。
- 成功口径：`iota4_external_free_source_canary=ok` 表示外部源真实执行且覆盖达标；fabric 仍可为 warning，因为 AKShare 保持 `research_only`，商业生产前仍需授权复核。
- 复用 Iota-3 表和 Kappa/Upsilon，不新增数据库结构。

本地运行：

```bash
.venv312/bin/python scripts/smoke_iota4_external_free_source_canary.py
.venv312/bin/python scripts/smoke_iota4_external_free_source_canary.py --mode compare-local
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-runs --requested-by iota4 --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-results --source-code akshare --limit 10
```

当前本地验收状态：

- AKShare live-only canary 已真实执行，daily_bar/security_master/trading_calendar 覆盖率为 `1.000000`，baseline_source_code=`akshare`。
- AKShare compare-local canary 已真实执行，csv/csv_mirror/akshare 三源进入同一 fabric，外部执行数为 `1`。
- 输出状态为 canary ok、fabric warning、recommendation=`research_only`、commercial_clearance=`blocked`，符合“技术可用但不能直接商业生产”的边界。
- Kappa 可按 `requested_by=iota4` 查询 3 条 run，可按 `source_code=akshare` 查询 9 条 dataset result。

## 多免费源 Adapter Pool Iota-5

Iota-5 阶段把免费源从 AKShare 单点 canary 扩展为 adapter pool：

- BaoStock：新增 explicit-symbol daily_bar/security_master/trading_calendar provider，并加 socket timeout，防止公网端口不可达时挂住。
- TuShare free：新增 Pro HTTP provider，必须配置 `QDATA_TUSHARE_TOKEN` 或 `--tushare-token` 才会真实执行。
- 官方公开源：CNINFO/SSE/SZSE/NBS 已从 provider_not_implemented 升级为 scaffold-only provider，等待 endpoint、授权和字段口径确认。
- Pool smoke：新增 `scripts/smoke_iota5_free_source_adapter_pool.py`，输出 ok/degraded/failed，并继续写入 Iota-3 fabric 审计。
- 商业边界：所有免费源仍保持 research_only/review_required，不会被误推为商业 primary。

本地运行：

```bash
.venv312/bin/python scripts/smoke_iota5_free_source_adapter_pool.py --baostock-timeout-seconds 3
.venv312/bin/python scripts/smoke_iota5_free_source_adapter_pool.py --require-ok --tushare-token <token>
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-runs --requested-by iota5 --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-results --source-code baostock --limit 10
```

当前本地验收状态：

- AKShare 真实执行成功，coverage_rate=`1.000000`。
- BaoStock 当前网络连接 `www.baostock.com:10030` 超时，已被 timeout guard 收敛成 `baostock_source_failed`。
- TuShare 当前未配置 token，正确输出 `tushare_token_missing`，没有伪造成功。
- 官方公开源当前为 `official_public_scaffold_pending`，没有抓取未确认授权的网页正文。
- Iota-5 smoke 当前输出 `iota5_free_source_adapter_pool=degraded`；严格两源成功可用 `--require-ok`。

## 免费源可靠性评分 Kappa-5

Kappa-5 阶段把 Iota-3/Iota-5 的 fabric 结果转成可排序、可降级的 source+dataset 评分：

- Snapshot：新增 `free_source_reliability_snapshot`，按 source_code、dataset_code、as_of_date 记录 reliability_score、success_rate、coverage_rate、conflict_rate_bps、连续失败次数、授权状态、商业清晰度、降级原因和恢复动作。
- Scoring：新增 `qdata.kappa5_free_source_reliability`，从最近 fabric result 展开 source 级观察，输出 ready/watch/degraded/rejected/no_data。
- 自动降级：BaoStock 连接失败、TuShare token 缺失、官方源 scaffold、冲突率过高或商业授权未清晰时，会进入 degraded/rejected/research_only，而不是生产主源。
- Kappa/Upsilon：新增 `/admin/free-source-reliability`；overview 展示 free_source_24h_reliability_count、ready/degraded/rejected 和 latest_free_source_reliability_status；Free Sources 分组展示 Free Source Reliability 表。
- 本机服务：Kappa-5 验收时使用 `http://127.0.0.1:18082/`；Lambda-5 验收时使用临时 `http://127.0.0.1:18083/`。

本地运行：

```bash
.venv312/bin/python scripts/run_kappa5_free_source_reliability.py --resource score --lookback-hours 72
.venv312/bin/python scripts/smoke_kappa5_free_source_reliability.py --lookback-hours 72
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-reliability --limit 5
.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18082 --token devtoken --trade-date 2026-07-28
```

当前本地验收状态：

- Migration：`0034_postgresql_free_source_kappa5_reliability.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback，并已在本机 PostgreSQL 应用成功。
- Score smoke：`kappa5_free_source_reliability_smoke=ok snapshot_count=28 ready=0 watch=11 degraded=2 rejected=15 no_data=0 min_score=0.0000 max_score=72.0000`。
- Kappa 查询：`free-source-reliability` 当前可返回 `rows=20`，csv/csv_mirror 因 local_smoke 保持 watch，AKShare 因授权/冲突降级，BaoStock/TuShare/official scaffold 进入 rejected 或 degraded。
- API smoke：Kappa-5 验收服务 18082 下 `free_source_reliability=ok rows=20`，console HTML 为 `189161` bytes。

## 免费源恢复编排 Lambda-5

Lambda-5 阶段把 Kappa-5 的评分结果转成可审计的恢复动作：

- Recovery run/action：新增 `free_source_recovery_run` 和 `free_source_recovery_action`，记录每次恢复编排、重试、告警、人工复核和观察动作。
- Worker task：`free_source_recovery` 已接入 Lambda worker 和 Mu schedule，默认 30 分钟扫描最近 72 小时 Kappa-5 snapshot。
- 告警闭环：high/critical 恢复动作幂等写入通用 `alert_event`，`alert_type=free_source_recovery_required`，可复用既有通知投递链路。
- Kappa/Upsilon：新增 `/admin/free-source-recovery-runs` 和 `/admin/free-source-recovery-actions`；overview 展示恢复 run、action、alert 和 latest status；Free Sources 分组展示恢复表。
- 商业边界：恢复动作只做研发、校验、备份和人工复核，不会把免费源提升为商业生产主源。

本地运行：

```bash
.venv312/bin/python scripts/smoke_lambda5_free_source_recovery.py --lookback-hours 72
.venv312/bin/python scripts/run_lambda5_free_source_recovery.py --resource runs --limit 5
.venv312/bin/python scripts/run_lambda5_free_source_recovery.py --resource actions --limit 10
.venv312/bin/python scripts/run_lambda_worker.py --task free_source_recovery --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-recovery-runs --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-recovery-actions --limit 5
```

当前本地验收状态：

- Migration：`0035_postgresql_free_source_lambda5_recovery.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback，并已在本机 PostgreSQL 应用成功。
- Recovery smoke：`lambda5_free_source_recovery_smoke=ok status=warning recovery_code=lambda5-free-source-recovery-2026-07-28-4982cec0f2 snapshot_count=28 action_count=28 retry=0 alerts=17 manual_review=17`。
- Worker dry-run：`free_source_recovery` task 输出 `status=skipped processed=28 warning=28`，且 dry-run 没有新增恢复 run。
- Kappa 查询：`free-source-recovery-runs` 当前返回 `rows=2`，`free-source-recovery-actions` 可返回 action 明细，包含 source_code、dataset_code、action_type、severity、reason_code、alert_id。
- API smoke：18083 最新服务下 `free_source_recovery_runs=ok rows=2`、`free_source_recovery_actions=ok rows=20`，console HTML 为 `202887` bytes。

## 免费源恢复执行闭环 Mu-5

Mu-5 阶段把 Lambda-5 的恢复动作推进到执行闭环：

- Execution audit：新增 `free_source_recovery_execution`，记录每条 action 的执行类型、状态、Iota-5 fabric、审批号、企业微信回执号和结果摘要。
- Retry canary：`retry_canary` 动作接入 Iota-5 canary；只有 `iota5_pool_status=ok` 才回写 recovered，degraded/failed 回写 failed。
- Manual review：`manual_review` 动作生成标准 `automation_action` 和 `automation_approval`，并调用 Delta-2 企业微信 live validation；默认不外发，只写 blocked receipt。
- Worker/Mu：新增 `free_source_recovery_execute` task 和 `mu_free_source_recovery_execute_30m` schedule。
- Kappa/Upsilon：新增 `/admin/free-source-recovery-executions`；Free Sources 分组展示 Recovery Executions。
- 安全边界：TuShare token、Authorization header、企业微信 webhook URL 和未确认授权的原始网页正文不会进入数据库、CLI、Kappa API 或 Upsilon HTML。

本地运行：

```bash
.venv312/bin/python scripts/smoke_mu5_free_source_recovery_executor.py
.venv312/bin/python scripts/run_mu5_free_source_recovery_executor.py --resource execute --max-actions 5 --no-retry-canary
.venv312/bin/python scripts/run_mu5_free_source_recovery_executor.py --resource executions --limit 10
.venv312/bin/python scripts/run_lambda_worker.py --task free_source_recovery_execute --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-recovery-executions --limit 5
```

当前本地验收状态：

- Migration：`0036_postgresql_free_source_mu5_recovery_execution.sql` 已在本机 PostgreSQL 连续应用两次，`free_source_recovery_execution` 表存在，`mu_free_source_recovery_execute_30m` schedule_count=`1`。
- Manual-review smoke：`mu5_free_source_recovery_smoke=ok status=warning candidates=1 executions=1 recovered=0 failed=0 suppressed=0 review_requested=1 blocked=0`，生成 pending approval，并写入企业微信 blocked receipt。
- Retry-canary smoke：`mu5_free_source_recovery_execute status=success candidates=1 executions=1 recovered=1 failed=0 suppressed=0 review_requested=0 blocked=0`，`execution_type=retry_canary status=recovered iota5_pool_status=ok`。
- Worker dry-run：`free_source_recovery_execute` task 输出 `status=skipped processed=20 warning=20`，dry-run 不写 execution。
- Kappa 查询：`free-source-recovery-executions` 当前返回 `rows=3`，包含 `retry_canary/recovered` 和 `manual_review/review_requested`。
- Docker API/Upsilon smoke：18080 真机服务下 `free_source_recovery_executions=ok rows=3`，console HTML 为 `210213` bytes，核心数据 API smoke 通过。

企业微信真实外发需要显式配置并允许：

```bash
export QDATA_DELTA2_WECOM_WEBHOOK_URL='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...'
.venv312/bin/python scripts/run_mu5_free_source_recovery_executor.py --resource execute --action-types manual_review --allow-wecom-external
```

## 免费源恢复健康与 SLA Nu-5

Nu-5 阶段把 Mu-5 执行闭环变成可长期运行的健康层：

- Health snapshot：新增 `free_source_recovery_health_snapshot`，记录 backlog、pending retry/manual_review、审批 pending/overdue、执行失败率、调度陈旧度、latest worker/schedule/execution status。
- SLA guardrail：审批超时、backlog 超阈值、失败率过高、Mu-5 schedule 陈旧或 worker failed 会进入 `critical`；未清空 backlog、待审批、近期失败/抑制会进入 `warning`。
- Runbook：每次快照输出 `health_issues` 和 `runbook_actions`，明确先处理审批、清 backlog、复核 Iota-5 canary、重启或强制 Mu scheduler。
- Worker/Mu：新增 `free_source_recovery_health` task 和 `nu_free_source_recovery_health_15m` schedule；critical 会映射为 worker failed，便于调度层感知。
- Kappa/Upsilon：新增 `/admin/free-source-recovery-health`；overview 展示 Recovery Health、Health Snapshots、Overdue Approvals 和 Recovery Backlog；Free Sources 分组展示 Recovery Health 表。
- 安全边界：Nu-5 只读取 Mu-5 action/execution、Omega approval、worker schedule/run 证据，不改写恢复 action、审批、行情、供应商、账单、权限或生产事实。

本地运行：

```bash
.venv312/bin/python scripts/smoke_nu5_free_source_recovery_health.py
.venv312/bin/python scripts/run_nu5_free_source_recovery_health.py --resource snapshots --limit 5
.venv312/bin/python scripts/run_lambda_worker.py --task free_source_recovery_health --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-recovery-health --limit 5
```

当前本地验收状态：

- Migration：`0037_postgresql_free_source_nu5_recovery_health.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback，并已在本机 PostgreSQL 连续应用两次，`nu_free_source_recovery_health_15m` schedule_count=`1`。
- Health smoke：`nu5_free_source_recovery_health_smoke=ok status=warning snapshot_code=nu5-recovery-health-2cebd0d243 backlog=34 approvals=2 overdue=0 failures=0 stale_schedule=0`。
- Worker dry-run：`free_source_recovery_health` task 输出 `status=skipped processed=1 warning=1`，dry-run 不写 snapshot。
- Worker/Mu 调度：非 dry-run worker 输出 `status=warning processed=1 warning=1`；强制触发 `nu_free_source_recovery_health_15m` 后 tick status=`warning`、worker_run_id=`14`。
- Kappa 查询：`free-source-recovery-health` 当前返回 `rows=3`，latest status=`warning`，health_issues 包含 `recovery_backlog_pending/manual_review_approval_pending/manual_review_requested_recently`。
- Kappa overview：`free_source_24h_recovery_health_count=3`、`latest_free_source_recovery_health_status=warning`、`free_source_recovery_overdue_approval_count=0`、`free_source_recovery_backlog_count=34`。
- Docker API/Upsilon smoke：18080 真机服务下 `free_source_recovery_health=ok rows=3`，console HTML 为 `215245` bytes，核心数据 API smoke 通过；Playwright 已生成 `/tmp/nu5-upsilon-desktop.png` 和 `/tmp/nu5-upsilon-mobile.png`。

## 免费源授权准入矩阵 Xi-5

Xi-5 阶段把“免费源/低价平替源能不能用于生产”变成可审计的准入矩阵：

- Admission profile：新增 `free_source_admission_profile`，按 source 记录 license_type、license_status、commercial_clearance、redistribution_allowed、contract_status、contract_ref、terms_review_status、rate_limit_per_min、daily_quota 和 max_allowed_role。
- Admission snapshot：新增 `free_source_admission_snapshot`，按 source+dataset 合并 profile、Kappa-5 reliability 和 Iota-3/Iota-5 fabric 证据，输出 `approved/conditional/review_required/blocked/no_data` 和 `admission_role`。
- 生产边界：只有合同 active、商用许可 clear、再分发 yes、条款 approved、限频/日配额齐全且可靠性达标时，才可能成为 `primary_candidate`；免费/研究/待复核源只能作为研发、校验或备份证据。
- Worker/Mu：新增 `free_source_admission_review` task 和 `xi_free_source_admission_review_6h` schedule。
- Kappa/Upsilon：新增 `/admin/free-source-admission-profiles` 和 `/admin/free-source-admission`；overview 展示 24h admission、approved/conditional/review_required/blocked/no_data 和 primary_candidate 数量；Free Sources 分组展示准入档案和准入矩阵。

本地运行：

```bash
.venv312/bin/python scripts/smoke_xi5_free_source_admission.py
.venv312/bin/python scripts/run_xi5_free_source_admission.py --resource snapshots --limit 5
.venv312/bin/python scripts/run_lambda_worker.py --task free_source_admission_review --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-admission --limit 5
```

当前本地验收状态：

- Migration：`0038_postgresql_free_source_xi5_admission.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback，并已在本机 PostgreSQL 应用成功，默认写入 9 条 admission profile 和 `xi_free_source_admission_review_6h` schedule。
- Xi-5 smoke：`xi5_free_source_admission_smoke=ok snapshots=38 approved=0 conditional=0 review_required=11 blocked=17 no_data=10 primary_candidate=0`。
- Worker/Mu：dry-run 输出 `processed=38 warning=38`；非 dry-run worker 输出 `status=warning processed=38 warning=38`；强制触发 `xi_free_source_admission_review_6h` 后 tick status=`warning`、worker_run_id=`17`。
- Kappa 查询：`free-source-admission` 当前返回准入矩阵，overview 显示 `free_source_24h_admission_count=114`、`free_source_24h_admission_review_required_count=33`、`free_source_primary_candidate_count=0`。
- Docker API/Upsilon smoke：18080 真机服务下 `free_source_admission_profiles=ok rows=9`、`free_source_admission=ok rows=20`，console HTML 为 `254026` bytes，核心数据 API smoke 通过。
- Playwright 已生成 `/tmp/xi5-upsilon-desktop.png` 和 `/tmp/xi5-upsilon-mobile.png`，桌面和移动视口均渲染非空 Upsilon 页面。

## 真实主供应商采购/合同闭环 Omicron-5

Omicron-5 阶段把“谁能成为授权主供应商”变成可审计、可调度、可展示的采购 readiness：

- Contract profile：新增 `vendor_contract_profile`，记录采购状态、合同状态、商用许可、再分发/缓存权、生产使用权、contract_ref、SLA、限频、quota、账单口径和负责人。
- Dataset entitlement：新增 `vendor_contract_dataset_entitlement`，按 dataset 记录授权角色、商用/再分发/生产使用、schema、字段映射、endpoint、限频、quota 和阻断原因。
- Procurement readiness：新增 `vendor_procurement_readiness_snapshot`，合并合同、授权、供应商 profile 和 Pi/Epsilon-3/Zeta-3/Eta-3/Theta-3 live 证据，输出 ready/conditional/review_required/blocked/no_contract。
- Worker/Mu：新增 `vendor_contract_readiness_review` task 和 `omicron5_vendor_contract_readiness_6h` schedule。
- Kappa/Upsilon：新增 `/admin/vendor-contract-profiles`、`/admin/vendor-contract-entitlements`、`/admin/vendor-procurement-readiness`；Vendor 分组展示合同、授权和采购 readiness 表。
- 生产边界：只有合同 active、商用 clear、再分发 yes、生产使用允许、合同引用存在、dataset entitlement active、schema/field mapping validated、限频/日配额/SLA 齐全且 live 证据未 blocked，才可能成为 `primary_candidate`。

本地运行：

```bash
.venv312/bin/python scripts/smoke_omicron5_vendor_contract.py
.venv312/bin/python scripts/run_omicron5_vendor_contract.py --resource readiness --limit 5
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_contract_readiness_review --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code omicron5_vendor_contract_readiness_6h --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-procurement-readiness --limit 5
```

当前本地验收状态：

- Migration：`0039_postgresql_vendor_omicron5_contract.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback，并已在本机 PostgreSQL 连续应用两次。
- Procurement smoke：`omicron5_vendor_contract_smoke=ok snapshots=7 ready=0 conditional=0 review_required=3 blocked=4 no_contract=0 primary_candidate=0`。
- Worker/Mu：dry-run 输出 `status=skipped processed=7 warning=7`；非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`；强制触发 `omicron5_vendor_contract_readiness_6h` 后 tick status=`warning`、worker_run_id=`20`。
- Kappa 查询：`vendor-contract-profiles` 返回 1 条 `vendor_http` draft/review_required 合同模板，`vendor-contract-entitlements` 返回 7 个核心 dataset 授权模板，`vendor-procurement-readiness` 返回 review_required/blocked 采购结论。
- Docker API/Upsilon smoke：18080 真机服务下 `vendor_contract_profiles=ok rows=1`、`vendor_contract_entitlements=ok rows=7`、`vendor_procurement_readiness=ok rows=20`，console HTML 为 `302589` bytes，核心数据 API smoke 通过。
- Playwright 已生成 `/tmp/omicron5-upsilon-desktop.png` 和 `/tmp/omicron5-upsilon-mobile.png`，桌面和移动视口均渲染非空 Upsilon 页面。
- 当前没有正式合同、再分发授权、生产使用授权和完整 SLA/quota，因此 `primary_candidate=0` 是正确结果。

## 授权主供应商生产切换 Pi-5

Pi-5 阶段把 Omicron-5、Pi、Theta-3 的证据合成“能不能把授权供应商切为生产主源”的 promotion guardrail。默认只审查并落库，不改写 `source_priority`；只有显式传入 `--apply-routing` 且全部 dataset 通过时，才会把目标 source 提升到指定 priority。

- Promotion run：新增 `vendor_primary_promotion_run`，记录 source、primary、as_of_date、promotion_scope、apply_mode、routing_change_allowed/applied、dataset 计数、required_windows、签批策略、阻断原因和 required_actions。
- Dataset result：新增 `vendor_primary_promotion_dataset_result`，按 dataset 绑定 Omicron-5 procurement snapshot、Pi readiness review、Theta-3 canary/full-market pilot、当前主源 priority 和切主结论。
- 证据闸门：要求 Omicron-5 为 `ready/primary_candidate`，Pi 5/20/60 readiness 为 `ready/approve_primary/primary`，Theta-3 canary 通过；默认还要求 full-market pilot 通过且 canary/full-market 签批均 approved。
- Worker/Mu：新增 `vendor_primary_promotion_review` task 和 `pi5_vendor_primary_promotion_6h` schedule，默认 `pi5_apply_routing=false`。
- Kappa/Upsilon：新增 `/admin/vendor-primary-promotions`、`/admin/vendor-primary-promotion-results`；Vendor 分组展示 promotion run/result 和 overview 指标。

本地运行：

```bash
.venv312/bin/python scripts/smoke_pi5_vendor_primary_promotion.py
.venv312/bin/python scripts/run_pi5_vendor_primary_promotion.py --resource runs --limit 5
.venv312/bin/python scripts/run_pi5_vendor_primary_promotion.py --resource results --limit 20
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_promotion_review --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code pi5_vendor_primary_promotion_6h --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-promotions --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-promotion-results --limit 20
```

当前本地验收状态：

- Migration：`0040_postgresql_vendor_pi5_primary_promotion.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback，并已在本机 PostgreSQL 连续应用两次。
- Pi-5 smoke：`pi5_vendor_primary_promotion_smoke=ok status=blocked datasets=7 approved=0 pending=0 blocked=7 applied=0 routing_allowed=False routing_applied=False`。
- Worker/Mu：dry-run 输出 `status=skipped processed=7 warning=7`；非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`；强制触发 `pi5_vendor_primary_promotion_6h` 后 tick status=`warning`、worker_run_id=`23`。
- Kappa 查询：`vendor-primary-promotions` 当前返回 3 条 blocked promotion run；`vendor-primary-promotion-results` 可返回 20 条 dataset result；overview 显示 `vendor_24h_primary_promotion_count=3`、`vendor_24h_primary_promotion_blocked_count=21`、`latest_vendor_primary_promotion_status=blocked`、`vendor_primary_promotion_routing_allowed_count=0`。
- Docker API/Upsilon smoke：18080 真机服务下 `vendor_primary_promotions=ok rows=3`、`vendor_primary_promotion_results=ok rows=20`，console HTML 为 `337318` bytes，Upsilon markers=`33`，核心数据 API smoke 通过。
- Playwright 已生成 `/tmp/pi5-upsilon-desktop.png` 和 `/tmp/pi5-upsilon-mobile.png`，桌面和移动视口均渲染非空 Upsilon 页面。
- 当前切主保护为 review-only；要真正切主，必须显式设置 `--apply-routing` 或 `QDATA_PI5_APPLY_ROUTING=true`，并确保所有 dataset 已是 `approved_for_primary` 或 `applied`。

## 主源切换后影子对账和回滚闭环 Rho-5

Rho-5 阶段把 Pi-5 的生产切主结果接到事后监控、影子对账和可回滚操作。默认仍是 review-only：没有 applied Pi-5 promotion 时会明确输出 `no_applied_promotion`，不会出现空白页或静默成功；只有显式设置 `--apply-rollback` / `QDATA_RHO5_APPLY_ROLLBACK=true` 且 dataset 触发 rollback guardrail 时，才会回写 `source_priority`。

- Monitor run：新增 `vendor_post_promotion_monitor_run`，记录 promotion、source、monitor_scope、rollback_mode、dataset 计数、shadow 阈值、rollback_allowed/applied、阻断原因和 required_actions。
- Dataset monitor：新增 `vendor_post_promotion_dataset_monitor`，按 dataset 追踪 Pi-5 promotion result、当前主源、前一主源、影子冲突率、失败率、陈旧分钟数和回滚建议。
- Worker/Mu：新增 `vendor_post_promotion_monitor` task 和 `rho5_post_promotion_monitor_1h` schedule。
- Kappa/Upsilon：新增 `/admin/vendor-post-promotion-monitors`、`/admin/vendor-post-promotion-results`；Vendor 分组展示 post-promotion monitor/result。

本地运行：

```bash
.venv312/bin/python scripts/smoke_rho5_post_promotion_monitor.py
.venv312/bin/python scripts/run_rho5_post_promotion_monitor.py --resource runs --limit 5
.venv312/bin/python scripts/run_rho5_post_promotion_monitor.py --resource results --limit 20
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_post_promotion_monitor --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code rho5_post_promotion_monitor_1h --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-post-promotion-monitors --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-post-promotion-results --limit 20
```

当前本地验收状态：

- Migration：`0041_postgresql_vendor_rho5_post_promotion_monitor.sql` 已在本机 PostgreSQL 连续应用两次。
- Rho-5 smoke：`rho5_post_promotion_monitor_smoke=ok status=no_applied_promotion datasets=7 healthy=0 warning=0 rollback_recommended=0 rolled_back=0 blocked=0 no_applied=7 rollback_allowed=False rollback_applied=False`。
- Worker/Mu：dry-run 输出 `status=skipped processed=7 warning=7`；非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`；强制触发 `rho5_post_promotion_monitor_1h` 后 tick status=`warning`、worker_run_id=`26`。
- Kappa 查询：`vendor-post-promotion-monitors` 当前返回 3 条 monitor run；`vendor-post-promotion-results` 当前可查 20 条 dataset monitor；overview 显示 `vendor_24h_post_promotion_monitor_count=3`、`vendor_24h_post_promotion_no_applied_count=21`、`latest_vendor_post_promotion_status=no_applied_promotion`。
- Docker API/Upsilon smoke：18080 真机服务下 `vendor_post_promotion_monitors=ok rows=3`、`vendor_post_promotion_results=ok rows=20`，console HTML 为 `364331` bytes，markers=`35`，核心数据 API smoke 通过。
- Playwright 已生成 `/tmp/rho5-upsilon-desktop.png` 和 `/tmp/rho5-upsilon-mobile.png`，桌面和移动视口均渲染非空 Upsilon 页面。

## 主供应商长期生产稳定性 Sigma-5

Sigma-5 阶段把“主供应商切过去以后能不能长期稳定跑”变成一套可审计的 SLA、容量、成本和调度闭环。没有 applied Pi-5 promotion 或当前主源未切到供应商时，它会明确输出 `no_primary_promotion`，不会再让控制台看起来像空白。

- Stability snapshot：新增 `vendor_primary_stability_snapshot`，聚合主供应商、当前主源、Pi-5/Rho-5、API audit、worker/scheduler、capacity alert、SLA 阈值、成本和稳定性评分。
- Dataset snapshot：新增 `vendor_primary_stability_dataset_snapshot`，按 dataset 追踪授权、生产使用权、schema、当前主源、promotion、post-promotion 和 API SLA 指标。
- Worker/Mu：新增 `vendor_primary_stability_monitor` task 和 `sigma5_vendor_primary_stability_1h` schedule。
- Kappa/Upsilon：新增 `/admin/vendor-primary-stability`、`/admin/vendor-primary-stability-datasets`；Vendor 分组展示 primary stability snapshot/dataset，overview 展示 24h 稳定性、critical、no_primary、cost 和 scheduler lag。
- 生产边界：Sigma-5 默认只读，不修改 `source_priority`、合同、授权或 promotion；critical SLA/Rho rollback/capacity alert 会映射为 worker failed，no_primary/blocked/warning 会映射为 worker warning。

本地运行：

```bash
.venv312/bin/python scripts/smoke_sigma5_vendor_primary_stability.py
.venv312/bin/python scripts/run_sigma5_vendor_primary_stability.py --resource snapshots --limit 5
.venv312/bin/python scripts/run_sigma5_vendor_primary_stability.py --resource datasets --limit 20
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_stability_monitor --dry-run --trade-date 2026-07-28
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_stability_monitor --trade-date 2026-07-28
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code sigma5_vendor_primary_stability_1h --trade-date 2026-07-28
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-stability --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-stability-datasets --limit 20
```

当前本地验收状态：

- Migration：`0042_postgresql_vendor_sigma5_primary_stability.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback。
- Sigma-5 smoke：当前未 applied Pi-5 promotion 时输出 `sigma5_primary_stability_smoke=ok status=no_primary_promotion role=watch datasets=7 primary=0 healthy=0 warning=0 critical=0 blocked=0 no_primary=7 api_success_rate=0.999307 scheduler_lag=0 backlog=1 score=0.0000`，并保留 required_actions。
- Worker/Mu：dry-run 输出 `status=skipped processed=7 warning=7`；非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`；强制触发 `sigma5_vendor_primary_stability_1h` 后 tick 输出 `status=warning lock_acquired=True worker_run_id=29`。
- Kappa 查询：`vendor-primary-stability` 输出 `rows=1 status=no_primary_promotion primary_dataset_count=0 no_primary_dataset_count=7 api_success_rate=0.999307`；`vendor-primary-stability-datasets` 输出 `rows=3`，dataset 明细保留 entitlement、promotion、当前主源和 schema 状态。
- Docker API/Upsilon smoke：18080 真机服务下 `vendor_primary_stability=ok rows=3`、`vendor_primary_stability_datasets=ok rows=20`，console HTML 为 `401847` bytes，markers=`37`，核心数据 API smoke 通过。
- Playwright 已生成 `/tmp/sigma5-upsilon-desktop.png`、`/tmp/sigma5-upsilon-mobile.png`、`/tmp/sigma5-upsilon-desktop-viewport.png` 和 `/tmp/sigma5-upsilon-mobile-viewport.png`，桌面和移动视口均渲染非空 Upsilon 页面。

## 主供应商组合成本优化 Tau-5

Tau-5 阶段把 Sigma-5 的长期稳定性水位接到采购成本、quota 和路由权重建议。当前如果没有 applied Pi-5 promotion 或当前主源未真正切到供应商，Tau-5 会明确输出 `no_primary_promotion`，把供应商 primary weight 置为 0，不会伪造“成本已优化”。

- Cost optimization snapshot：新增 `vendor_cost_optimization_snapshot`，聚合稳定性、合同授权、API 用量、预算、quota、推荐权重和 required_actions。
- Route weight plan：新增 `vendor_route_weight_plan`，按 dataset 生成 primary/backup/free 权重建议、预算占用、quota 压力、阻断原因和是否允许路由变更。
- Budget stress：新增 `vendor_budget_stress_dataset_snapshot`，按 dataset 和压力倍数输出 1x/5x/10x 预算与 quota 风险。
- Worker/Mu：新增 `vendor_cost_optimizer` task 和 `tau5_vendor_cost_optimizer_6h` schedule。
- Kappa/Upsilon：新增 `/admin/vendor-cost-optimizations`、`/admin/vendor-route-weight-plans`、`/admin/vendor-budget-stress`；Vendor 分组展示 cost optimization、route weight 和 budget stress 表，overview 展示 Cost Plans、Cost Status、Primary Weight、Budget Usage 和 Quota Usage。
- 生产边界：Tau-5 默认只读，不修改 `source_priority`、合同、授权或实际路由；`blocked/over_budget` 映射为 worker failed，`no_primary_promotion/quota_risk/watch` 映射为 worker warning。

本地运行：

```bash
.venv312/bin/python scripts/smoke_tau5_vendor_cost_optimization.py --as-of-date 2026-07-29
.venv312/bin/python scripts/run_tau5_vendor_cost_optimization.py --resource optimizations --limit 5
.venv312/bin/python scripts/run_tau5_vendor_cost_optimization.py --resource plans --limit 20
.venv312/bin/python scripts/run_tau5_vendor_cost_optimization.py --resource stress --limit 20
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_cost_optimizer --dry-run --trade-date 2026-07-29
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_cost_optimizer --trade-date 2026-07-29
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code tau5_vendor_cost_optimizer_6h --trade-date 2026-07-29
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-cost-optimizations --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-route-weight-plans --limit 20
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-budget-stress --limit 20
```

当前本地验收状态：

- Migration：`0043_postgresql_vendor_tau5_cost_optimization.sql` 已加入增量迁移、Docker init、总表 DDL 和 rollback；本机 PostgreSQL 连续应用两次，第二次跳过已存在对象且 schedule `INSERT 0 0`。
- Tau-5 smoke：当前未 applied Pi-5 promotion 时输出 `tau5_vendor_cost_smoke=ok status=no_primary_promotion role=watch datasets=7 optimized=0 watch=0 over_budget=0 quota_risk=0 blocked=0 no_primary=7 primary_weight=0.0000 backup_weight=100.0000 free_weight=0.0000 budget_pct=0E-8 monthly_quota_pct=0E-8 score=0.0000 stress=21`。
- Worker/Mu：dry-run 输出 `status=skipped processed=7 warning=7`；非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`；强制触发 `tau5_vendor_cost_optimizer_6h` 后 tick 输出 `status=warning lock_acquired=True worker_run_id=32`。
- Kappa 查询：`vendor-cost-optimizations` 输出 `rows=1 status=no_primary_promotion dataset_count=7 no_primary_dataset_count=7 recommended_primary_weight_pct=0.0000`；`vendor-route-weight-plans` 输出 `rows=3`；`vendor-budget-stress` 输出 `rows=3 recommended_action=wait_primary_promotion`。
- Docker API/Upsilon smoke：18080 真机服务下 `vendor_cost_optimizations=ok rows=3`、`vendor_route_weight_plans=ok rows=20`、`vendor_budget_stress=ok rows=20`，console HTML 为 `461265` bytes，markers=`40`，核心数据 API smoke 通过。
- Playwright 已生成 `/tmp/tau5-upsilon-desktop-viewport.png`、`/tmp/tau5-upsilon-desktop-long.png`、`/tmp/tau5-upsilon-mobile-viewport.png` 和 `/tmp/tau5-upsilon-mobile.png`，桌面和移动视口均渲染非空 Upsilon 页面。

## 路由权重执行护栏 Upsilon-5

Upsilon-5 阶段把 Tau-5 的权重建议推进到“可审批、可灰度、可回滚”的执行控制面。当前如果没有 applied Pi-5 promotion 或 Tau-5 没有可执行 primary weight，Upsilon-5 会输出 `no_primary_promotion`，保持 applied primary weight 为 0，且不会写入 active policy。

- Route execution run：新增 `vendor_route_weight_execution_run`，记录执行模式、审批状态、灰度策略、目标权重、实际权重、阻断原因和 required_actions。
- Dataset execution：新增 `vendor_route_weight_execution_dataset`，按 dataset 追踪 Tau-5 plan、当前主源、approval、stage、target/applied 权重和 rollback 标记。
- Rollout stage：新增 `vendor_route_weight_rollout_stage`，记录每个 dataset 的灰度阶段、gate status、目标权重和是否已应用。
- Policy 控制面：新增 `source_route_weight_policy`，只在显式 `execution_mode=apply` 且审批通过时写入，不直接改写 `source_priority`。
- Worker/Mu：新增 `vendor_route_weight_executor` task 和 `upsilon5_vendor_route_weight_executor_1h` schedule。
- Kappa/Upsilon：新增 `/admin/vendor-route-executions`、`/admin/vendor-route-execution-datasets`、`/admin/vendor-route-rollout-stages`、`/admin/source-route-weight-policies`；Vendor 分组展示四张执行闭环表，overview 展示 Route Execs、Route Pending、Route Status、Route Applied Wt 和 Active Policies。

本地运行：

```bash
.venv312/bin/python scripts/smoke_upsilon5_route_weight_execution.py --as-of-date 2026-07-29
.venv312/bin/python scripts/run_upsilon5_route_weight_execution.py --resource executions --limit 5
.venv312/bin/python scripts/run_upsilon5_route_weight_execution.py --resource datasets --limit 20
.venv312/bin/python scripts/run_upsilon5_route_weight_execution.py --resource stages --limit 20
.venv312/bin/python scripts/run_upsilon5_route_weight_execution.py --resource policies --limit 20
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_route_weight_executor --dry-run --trade-date 2026-07-29
.venv312/bin/python scripts/run_lambda_worker.py --task vendor_route_weight_executor --trade-date 2026-07-29
.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code upsilon5_vendor_route_weight_executor_1h --trade-date 2026-07-29
.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-route-executions --limit 5
.venv312/bin/python scripts/report_kappa_admin.py --resource source-route-weight-policies --limit 20
```

当前本地验收状态：

- Migration：`0044_postgresql_vendor_upsilon5_route_execution.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback；本机 PostgreSQL 连续应用两次，第一次创建 schedule，第二次 schedule `INSERT 0 0`。
- Upsilon-5 smoke：当前未 applied Pi-5 promotion 时输出 `upsilon5_route_execution_smoke=ok status=no_primary_promotion datasets=7 pending=0 approved=0 staged=0 applied=0 blocked=0 no_primary=7 target_primary=0.0000 applied_primary=0.0000 policies=0 stages=7`。
- Worker/Mu：dry-run 输出 `task name=vendor_route_weight_executor status=skipped processed=7 warning=7`；非 dry-run 输出 `status=warning processed=7 warning=7 failed=0`；强制触发 `upsilon5_vendor_route_weight_executor_1h` 后 tick 输出 `status=warning lock_acquired=True worker_run_id=35`。
- Kappa 查询：overview 显示 `vendor_24h_route_execution_count=3`、`vendor_24h_route_blocked_count=21`、`latest_vendor_route_execution_status=no_primary_promotion`、`active_source_route_weight_policy_count=0`；四个 Upsilon-5 endpoint 均可查。
- Docker API/Upsilon smoke：Upsilon-5 阶段验收时，18080 真机服务下 route execution、dataset、stage 和 policy endpoint 均 ok，console HTML 为 `506948` bytes，markers=`44`，核心数据 API smoke 通过；Phi-5 后的当前 route policy/decision 数字见下一节。
- Playwright 已生成 `/tmp/upsilon5-upsilon-desktop-viewport.png` 和 `/tmp/upsilon5-upsilon-mobile-viewport.png`，桌面和移动首屏均渲染非空 Upsilon 页面，并确认 Vendor Route Executions 与 Source Route Weight Policies 存在。

## 路由策略生产运行时 Phi-5

Phi-5 阶段把 Upsilon-5 写入的 active `source_route_weight_policy` 接到真实查询和采集运行时。现在它不只是“控制台里有策略”，而是 API 与 ingest 可以按策略选源、按 fallback 兜底，并把每一次决策写成可审计记录。

- Route decision audit：新增 `qmeta.source_route_decision_audit`，记录 requested/selected/final source、route mode、decision status、fallback、row_count、duration 和 request context。
- Runtime resolver：新增 `qdata.phi5_route_policy`，按 dataset、requested source、as_of_date 和 request key 读取 active policy，用 deterministic bucket 做稳定权重选择。
- Sync 接入：`scripts/sync_daily_market.py --use-route-policy` 会优先使用策略选中的 provider，失败或无数据时尝试 fallback，并在结果里返回 `route_decision`。
- API 接入：`/price`、`/matrix`、`/constraints` 会在 `meta.route_policy` 返回路由决策，并把 API 查询路径写入审计。
- Kappa/Upsilon：新增 `/admin/source-route-decisions`，overview 增加 Route Decisions、Route Fallbacks、Route Final，Vendor 分组展示 Source Route Decisions 表。

本地运行：

```bash
python3 scripts/smoke_phi5_route_policy_runtime.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata --trade-date 2024-01-04
python3 scripts/sync_daily_market.py --provider csv --trade-date 2024-01-04 --symbols 600519.SH --dry-run --use-route-policy
python3 scripts/report_kappa_admin.py --resource source-route-decisions --limit 5
curl -s -H 'Authorization: Bearer devtoken' 'http://127.0.0.1:18080/price?symbols=600519.SH,000001.SZ&start_date=2024-01-04&end_date=2024-01-04'
```

当前本地验收状态：

- Migration：`0045_postgresql_vendor_phi5_route_policy_runtime.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback；本机 PostgreSQL 连续应用两次，第二次跳过已存在对象。
- Phi-5 smoke：输出 `phi5_route_policy_smoke=ok policy_code=phi5-smoke-policy-20260729023952118375 selected=csv_mirror final=csv_mirror fallback=False audits=1`。
- API 元信息：`/price` 响应已包含 `meta.route_policy`，当前默认路径输出 `decision_context=api`、`route_mode=default`、`decision_status=success`、`selected_source_code=csv`、`final_source_code=csv`。
- Kappa 查询：`admin.source-route-decisions rows=5`，可同时看到 sync policy_weighted 决策和 API default 决策。
- Docker API/Upsilon smoke：18080 真机服务下 `source_route_weight_policies=ok rows=2`、`source_route_decisions=ok rows=6`、console HTML 为 `511564` bytes，markers=`45`，核心数据 API smoke 通过。
- Playwright 已生成 `/tmp/phi5-upsilon-desktop-viewport.png` 和 `/tmp/phi5-upsilon-mobile-viewport.png`，桌面和移动首屏均渲染非空 Upsilon 页面。

## 路由策略反馈闭环 Chi-5

Chi-5 阶段把 Phi-5 写下来的每一次真实路由决策，变成可长期运行的健康反馈闭环。现在系统能按 source+dataset 聚合成功率、失败率、fallback、空响应和延迟，自动打开/保持/关闭 circuit breaker，并把恢复探测写成审计记录。

- Route health snapshot：新增 `qmeta.source_route_health_snapshot`，记录每个 source+dataset 的健康窗口、阈值、熔断动作和 runbook。
- Circuit breaker：新增 `qmeta.source_route_circuit_breaker`，维护 open/closed 状态、`open_until`、最近健康快照、最近恢复探测和打开原因。
- Recovery probe：新增 `qmeta.source_route_recovery_probe`，记录熔断恢复窗口里的 observed success rate、required success rate 和 recovered/failed 结论。
- Phi-5 resolver 接入：运行时读取 open circuit，跳过仍在 `open_until` 内的候选源；若所有候选都被跳过，则 fail-open 并在 `meta.route_policy` 里标记。
- Worker/Mu：新增 `source_route_feedback_monitor` task 和 `chi5_source_route_feedback_15m` schedule。
- Kappa/Upsilon：新增 `/admin/source-route-health`、`/admin/source-route-circuit-breakers`、`/admin/source-route-recovery-probes`，Vendor 分组展示三张 Chi-5 表，overview 展示 Route Health、Open Circuits 和 Recovery Probes。

本地运行：

```bash
python3 scripts/smoke_chi5_route_feedback.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_chi5_route_feedback.py --resource check --requested-by chi5-cli --trigger-mode manual --environment local
python3 scripts/run_chi5_route_feedback.py --resource health --dataset-code daily_bar --source-code baostock --limit 5
python3 scripts/run_chi5_route_feedback.py --resource circuits --dataset-code daily_bar --source-code baostock --limit 5
python3 scripts/run_chi5_route_feedback.py --resource probes --dataset-code daily_bar --source-code baostock --limit 5
python3 scripts/run_lambda_worker.py --task source_route_feedback_monitor --dry-run --trade-date 2026-07-29
python3 scripts/run_lambda_worker.py --task source_route_feedback_monitor --trade-date 2026-07-29
python3 scripts/run_mu_scheduler.py --once --force-due --schedule-code chi5_source_route_feedback_15m --trade-date 2026-07-29
python3 scripts/report_kappa_admin.py --resource source-route-health --limit 5
python3 scripts/report_kappa_admin.py --resource source-route-circuit-breakers --limit 5
python3 scripts/report_kappa_admin.py --resource source-route-recovery-probes --limit 5
```

当前本地验收状态：

- Migration：`0046_postgresql_vendor_chi5_route_feedback.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback；Docker PostgreSQL 连续应用两次，第二次跳过已存在对象且 schedule `INSERT 0 0`。
- Chi-5 smoke：输出 `chi5_route_feedback_smoke=ok first_status=critical second_status=healthy health=2 circuit=closed probe=recovered ...`，验证失败开闸、健康恢复和 recovery probe。
- CLI 查询：`source-route-health` 可看到 `status=healthy circuit_action=close_circuit` 与 `status=degraded circuit_action=open_circuit`；`source-route-circuit-breakers` 可看到 `status=open open_until=...`；`source-route-recovery-probes` 可看到 `status=recovered/failed`。
- Worker/Mu：dry-run 输出 `task name=source_route_feedback_monitor status=skipped processed=4 warning=4`；非 dry-run 输出 `status=warning processed=4`；强制触发 `chi5_source_route_feedback_15m` 后 tick 输出 `status=warning lock_acquired=True worker_run_id=38`。
- Kappa Admin API smoke：`source_route_health=ok rows=17`、`source_route_circuit_breakers=ok rows=4`、`source_route_recovery_probes=ok rows=3`、console HTML 为 `534442` bytes。
- Upsilon smoke：`upsilon_console=ok html_bytes=534442 markers=48`，Vendor 分组已渲染 Source Route Health、Source Route Circuit Breakers 和 Source Route Recovery Probes。
- Docker app profile：`qdata-api=healthy`，PostgreSQL/ClickHouse 均 healthy，`18080/devtoken` 下核心数据 API、Kappa Admin API 和 Upsilon console smoke 均通过。
- Playwright 已生成 `/tmp/chi5-upsilon-desktop-viewport.png` 和 `/tmp/chi5-upsilon-mobile-viewport.png`，桌面和移动首屏均渲染非空 Upsilon 页面。

## 路由故障自动处置闭环 Psi-5

Psi-5 阶段把 Chi-5 的 open circuit、failed probe、recovered probe 和 degraded health 信号接入自动化动作。现在系统不只知道某个 source+dataset 熔断了，还会生成可审计、可审批、可查询、可展示的处置动作。

- Route incident action：新增 `qmeta.source_route_incident_action`，按 route 信号记录 incident action、automation run/action、dataset/source、熔断/探测状态、指标、owner、planned/executed effect 和 rollback hint。
- Psi route source：`run_psi_automation(... include_route=True)` 会把 `circuit_open` 映射为高风险 `degrade_vendor` 审批动作，把 `recovery_failed` 映射为 owner 通知，把 `recovered` 映射为恢复监控动作。
- Worker/Mu：新增 `route_incident_automation` task 和 `psi5_route_incident_automation_15m` schedule；dry-run 只预览，非 dry-run 写入自动化 run/action 和 route incident action。
- Kappa/Upsilon：新增 `/admin/source-route-incident-actions`，Vendor 分组展示 Source Route Incident Actions 表，overview 展示 24h route action、pending action 和 latest action status。
- Smoke：新增 `scripts/smoke_psi5_route_incident_automation.py`，串起 “Chi-5 失败开闸 -> Psi-5 审批动作 -> Chi-5 恢复探测 -> Psi-5 恢复动作”。

本地运行：

```bash
python3 scripts/smoke_psi5_route_incident_automation.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_psi5_route_incident_automation.py --resource run --execution-mode execute
python3 scripts/run_psi5_route_incident_automation.py --resource route-actions --limit 5
python3 scripts/report_psi_automation.py --resource route-actions --limit 5
python3 scripts/run_lambda_worker.py --task route_incident_automation --dry-run --trade-date 2026-07-29
python3 scripts/run_lambda_worker.py --task route_incident_automation --trade-date 2026-07-29
python3 scripts/run_mu_scheduler.py --once --force-due --schedule-code psi5_route_incident_automation_15m --trade-date 2026-07-29
python3 scripts/report_kappa_admin.py --resource source-route-incident-actions --limit 5
```

当前本地验收状态：

- Migration：`0047_postgresql_automation_psi5_route_incident.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback。
- 单元测试：`249` 个 unittest 通过，Psi 映射、Worker/Mu 参数、Kappa endpoint、Upsilon marker 已覆盖。
- Psi-5 smoke：输出 `psi5_route_incident_smoke=ok open_action=approval_required recovered_action=success source=psi5_smoke_a25466319c incidents=2 ...`。
- CLI/Worker/Mu：`source-route-incident-actions` 查询输出 `rows=5`；Worker dry-run 输出 `task name=route_incident_automation status=skipped processed=8 warning=8`；非 dry-run 输出 `status=success processed=8 warning=8`；Mu 强制触发 `psi5_route_incident_automation_15m` 后 tick 输出 `status=success lock_acquired=True worker_run_id=41`。
- Kappa Admin API smoke：`source_route_incident_actions=ok rows=10`，console HTML 为 `558721` bytes。
- Upsilon smoke：`upsilon_console=ok html_bytes=558721 markers=49`，HTML 检查 `incident_table=True incident_rows=10`。
- Playwright 已生成 `/tmp/psi5-upsilon-desktop-viewport.png` 和 `/tmp/psi5-upsilon-mobile-viewport.png`，桌面和移动首屏均渲染非空 Upsilon 页面。

## 路由故障真实审批与通知闭环 Omega-5

Omega-5 阶段把 Psi-5 生成的 route incident action 接入真实审批、企业微信通知回执、执行尝试和回滚计划。默认不会向外部企业微信发送消息；未显式允许外发时仍会写入 blocked/success receipt 和 acknowledged dispatch 审计，方便本机和 Docker smoke 验证完整链路。

- Route incident control：新增 `qmeta.source_route_incident_control`，把 incident action、automation action、approval、dispatch、attempt、WeCom receipt 和 rollback 串成一条控制记录。
- Worker/Mu：新增 `route_incident_control` task 和 `omega5_route_incident_control_15m` schedule；dry-run 只预览，非 dry-run 写入 approval、notification audit、rollback plan 和 control 状态。
- Kappa/Upsilon：新增 `/admin/source-route-incident-controls`，overview 展示 24h control、pending control 和 latest control stage，Vendor 分组展示 Source Route Incident Controls。
- Smoke：新增 `scripts/smoke_omega5_route_incident_control.py`，串起 “Chi-5 开闸 -> Psi-5 高风险动作 -> Omega-5 pending approval/WeCom receipt/rollback -> auto approval -> Omega execution attempt”。

本地运行：

```bash
python3 scripts/smoke_omega5_route_incident_control.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_omega5_route_incident_control.py --resource run --execution-mode review_only
python3 scripts/run_omega5_route_incident_control.py --resource run --execution-mode execute --auto-approve --approved-by route-control-ops
python3 scripts/run_omega5_route_incident_control.py --resource controls --limit 5
python3 scripts/run_lambda_worker.py --task route_incident_control --dry-run --trade-date 2026-07-29
python3 scripts/run_lambda_worker.py --task route_incident_control --trade-date 2026-07-29
python3 scripts/run_mu_scheduler.py --once --force-due --schedule-code omega5_route_incident_control_15m --trade-date 2026-07-29
python3 scripts/report_kappa_admin.py --resource source-route-incident-controls --limit 5
```

当前本地验收状态：

- Migration：`0048_postgresql_automation_omega5_route_incident_control.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback。
- 单元测试：`252` 个 unittest 通过，新增 Omega-5 plan/summary/report 覆盖，并扩展 Worker、Mu、Kappa 和 Upsilon marker。
- Omega-5 smoke：输出 `omega5_route_incident_smoke=ok pending_approval=pending approved=approved dispatch=acknowledged receipt=blocked attempt=success rollback=planned control=executed source=omega5_smoke_fdfbf1016a`。
- CLI/Worker/Mu：`source-route-incident-controls` 查询输出 `rows=5`；Worker dry-run 和非 dry-run 当前因无待处理候选输出 `task name=route_incident_control status=skipped processed=0`；Mu 强制触发 `omega5_route_incident_control_15m` 后 tick 输出 `status=skipped lock_acquired=True worker_run_id=44`。
- Kappa Admin API smoke：`source_route_incident_controls=ok rows=11`，console HTML 为 `587502` bytes。
- Upsilon smoke：`upsilon_console=ok html_bytes=587502 markers=50`，已覆盖 Source Route Incident Controls。
- Playwright 已生成 `/tmp/omega5-upsilon-desktop-viewport.png` 和 `/tmp/omega5-upsilon-mobile-viewport.png`，桌面和移动首屏均渲染非空 Upsilon 页面。
- 企业微信：默认 `allow_wecom_external=false`，不会外发真实企业微信；配置 `QDATA_DELTA2_WECOM_WEBHOOK_URL` 后可加 `--allow-wecom-external` 验证真实 `errcode=0` 回执。

## 路由故障控制健康运维 Alpha-6

Alpha-6 阶段把 Omega-5 的 route incident control 闭环升级为长期生产运维健康层：持续检查审批 SLA、控制积压、企业微信回执、执行失败率、回滚计划和 Mu 调度陈旧度。它只读证据、写健康快照和 runbook，不直接审批、执行或回滚业务动作。

- Health snapshot：新增 `qmeta.source_route_incident_control_health_snapshot`，记录 control_count、pending_control_count、approval_overdue_count、blocked_receipt_rate、execution_failure_rate、missing_rollback_count、stale_schedule_count、latest worker/schedule/control stage。
- Worker/Mu：新增 `route_incident_control_health` task 和 `alpha6_route_incident_control_health_15m` schedule；critical 会映射为 worker failed，warning 映射为 worker warning。
- Kappa/Upsilon：新增 `/admin/source-route-incident-control-health`，overview 展示最新控制健康状态、issue_count、overdue approval 和 blocked receipt，Vendor 分组展示 Source Route Incident Control Health 表。
- Smoke：新增 `scripts/smoke_alpha6_route_incident_control_health.py`，复用 Omega-5 smoke 造控制证据，再写 Alpha-6 健康快照。

本地运行：

```bash
python3 scripts/smoke_alpha6_route_incident_control_health.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_alpha6_route_incident_control_health.py --resource check --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_alpha6_route_incident_control_health.py --resource health --limit 5
python3 scripts/run_lambda_worker.py --task route_incident_control_health --dry-run --trade-date 2026-07-29
python3 scripts/run_lambda_worker.py --task route_incident_control_health --trade-date 2026-07-29
python3 scripts/run_mu_scheduler.py --once --force-due --schedule-code alpha6_route_incident_control_health_15m --trade-date 2026-07-29
python3 scripts/report_kappa_admin.py --resource source-route-incident-control-health --limit 5
```

当前本地验收状态：

- Migration：`0049_postgresql_automation_alpha6_route_incident_control_health.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback，并已在 Docker PostgreSQL 连续应用两次。
- 单元测试：`257` 个 unittest 通过，新增 Alpha-6 health/runbook/report 覆盖，并扩展 Worker、Mu、Kappa 和 Upsilon marker。
- Alpha-6 smoke：输出 `alpha6_route_incident_control_health_smoke=ok status=warning snapshot_code=alpha6-route-control-health-ae3a392e4e controls=15 pending=0 blocked_receipts=4 failed_execution=0 stale=0 latest_stage=executed`。
- CLI/Worker/Mu：health 查询输出 `rows=1`；Worker dry-run 输出 `task name=route_incident_control_health status=skipped processed=1 warning=1`，非 dry-run 输出 `status=warning processed=1 warning=1`；Mu 强制触发后 tick 输出 `status=warning lock_acquired=True worker_run_id=48`。
- Kappa Admin API smoke：`source_route_incident_control_health=ok rows=3`，console HTML 为 `609089` bytes；核心 API smoke 通过。
- Upsilon smoke：`upsilon_console=ok html_bytes=609089 markers=51`，已覆盖 Source Route Incident Control Health。
- Playwright 已生成 `/tmp/alpha6-upsilon-desktop-viewport.png` 和 `/tmp/alpha6-upsilon-mobile-viewport.png`，桌面和移动首屏均渲染非空 Upsilon 页面。

## 路由故障控制操作队列 Beta-6

Beta-6 阶段把 Alpha-6 的健康发现推进到可运营队列：对 Omega-5 pending controls 做批量 approve/reject/hold，生成企业微信通知降噪摘要，并沉淀全市场 route incident 压测计划证据。默认 `approval_decision=hold`、`apply_decisions=false`，不会外发企业微信或执行真实路由变更；只有显式开启 apply 时才通过 Omega approval 控制面改写审批状态。

- Operation batch/item：新增 `qmeta.source_route_incident_operation_batch` 和 `qmeta.source_route_incident_operation_item`，记录候选数、eligible、approved/rejected/held、suppressed notification、stress scenario 和每个 control 的审批前后状态。
- Worker/Mu：新增 `route_incident_operations` task 和 `beta6_route_incident_operations_30m` schedule；默认定时刷新队列和压测证据，不自动 approve。
- Kappa/Upsilon：新增 `/admin/source-route-incident-operation-batches`、`/admin/source-route-incident-operation-items`，overview 展示最新 operation status、queue、dedupe 和 stress；Vendor 分组展示 Operation Batches/Items 表。
- Smoke：新增 `scripts/smoke_beta6_route_incident_operations.py`，造一个 pending route control，再用 Beta-6 批量 approve 并校验 batch/item 持久化。

本地运行：

```bash
python3 scripts/smoke_beta6_route_incident_operations.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_beta6_route_incident_operations.py --resource run --approval-decision hold --dry-run --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_beta6_route_incident_operations.py --resource batches --limit 5
python3 scripts/run_beta6_route_incident_operations.py --resource items --limit 5
python3 scripts/run_lambda_worker.py --task route_incident_operations --dry-run --trade-date 2026-07-29
python3 scripts/run_mu_scheduler.py --once --force-due --schedule-code beta6_route_incident_operations_30m --trade-date 2026-07-29
python3 scripts/report_kappa_admin.py --resource source-route-incident-operation-batches --limit 5
python3 scripts/report_kappa_admin.py --resource source-route-incident-operation-items --limit 5
```

当前本地验收状态：

- Migration：`0050_postgresql_automation_beta6_route_incident_operations.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback，并已在 Docker PostgreSQL 连续应用两次。
- 单元测试：`262` 个 unittest 通过，新增 Beta-6 queue/dedupe/stress/report 覆盖，并扩展 Worker、Mu、Kappa 和 Upsilon marker。
- Beta-6 smoke：输出 `beta6_route_incident_operations_smoke=ok status=success batch_code=beta6-route-ops-4811dfb7e6 eligible=1 approved=1 suppressed=0 stress_scenarios=16 items=1 source=beta6_smoke_4bb79a186c`。
- CLI/Worker/Mu：batch 查询输出 `admin.source-route-incident-operation-batches rows=3`，item 查询输出 `rows=1`；Worker dry-run 输出 `task name=route_incident_operations status=skipped processed=0 warning=1`；非 dry-run 当前无待处理队列输出 `status=skipped processed=0`；Mu 强制触发输出 `tick schedule=beta6_route_incident_operations_30m task=route_incident_operations status=skipped lock_acquired=True worker_run_id=51`。
- Kappa Admin API smoke：`source_route_incident_operation_batches=ok rows=3`、`source_route_incident_operation_items=ok rows=1`，console HTML 为 `632573` bytes；核心 API smoke 通过。
- Upsilon smoke：`upsilon_console=ok html_bytes=632573 markers=53`，已覆盖 Source Route Incident Operation Batches/Items。

## 路由故障可写审批 API Gamma-6

Gamma-6 阶段把 Beta-6 的运维队列升级为可写审批控制面：支持 API 提交 approve/reject/hold，记录 command/item/signature 三层审计，支持多审批人 quorum、幂等重放和 Upsilon 行级操作按钮。审批落地仍通过 Omega approval 控制面，不绕过原有审批表；企业微信交互目前只记录 preview，不默认外发。

- Writable approval API：新增 `POST /admin/source-route-incident-approval-commands`，必须 admin token，body 支持 `decision`、`control_code/approval_code/batch_code` 三选一、`required_approvals`、`idempotency_key`、`requested_by/principal_code`。
- Command/item/signature：新增 `qmeta.source_route_incident_approval_command`、`qmeta.source_route_incident_approval_command_item`、`qmeta.source_route_incident_approval_signature`，可审计每次签批、quorum、应用状态和幂等重放。
- Kappa/Upsilon：新增 `/admin/source-route-incident-approval-commands`、`/admin/source-route-incident-approval-command-items`、`/admin/source-route-incident-approval-signatures`；Vendor 分组展示三张表，Operation Items 行内提供 Approve/Reject/Hold 按钮。
- Smoke：新增 `scripts/smoke_gamma6_route_incident_approval_api.py`，造 pending route control，通过真实 HTTP POST 先得到 `pending_quorum`，第二个审批人签名后变为 `applied`，并校验幂等重放。

本地运行：

```bash
python3 scripts/smoke_gamma6_route_incident_approval_api.py --base-url http://127.0.0.1:18080 --token devtoken --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_gamma6_route_incident_approval_api.py --resource commands --limit 5 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_gamma6_route_incident_approval_api.py --resource items --limit 5 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_gamma6_route_incident_approval_api.py --resource signatures --limit 5 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/report_kappa_admin.py --resource source-route-incident-approval-commands --limit 5
python3 scripts/report_kappa_admin.py --resource source-route-incident-approval-command-items --limit 5
python3 scripts/report_kappa_admin.py --resource source-route-incident-approval-signatures --limit 5
```

当前本地验收状态：

- Migration：`0051_postgresql_automation_gamma6_route_incident_approval_api.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback，并已在 Docker PostgreSQL 连续应用两次。
- 单元测试：`269` 个 unittest 通过，新增 Gamma-6 quorum/command issue/API POST/Kappa/Upsilon 覆盖。
- Gamma-6 smoke：输出 `gamma6_route_approval_api_smoke=ok first=pending_quorum second=applied quorum=met signatures=2 approved=approved`，包含 command_code、control 和 source。
- CLI/Kappa：commands/items/signatures 查询均可返回 `rows>=1`；Kappa Admin API smoke 新增 `source_route_incident_approval_commands=ok`、`source_route_incident_approval_command_items=ok`、`source_route_incident_approval_signatures=ok`。
- Upsilon/API：`upsilon_console=ok html_bytes=659294 markers=57`，核心 REST smoke 继续输出 health/price/constraints/tradable/matrix 全部 ok。

## 路由故障审批治理层 Delta-6

Delta-6 阶段把 Gamma-6 的可写签批升级成生产可控的审批治理层：企业微信交互回调先做 HMAC 验签、nonce 防重放、RBAC 角色、职责分离和策略 quorum 检查；只有治理通过后才调用 Gamma-6，再由 Gamma-6/Omega 控制面改写审批状态。

- Governance schema：新增 `qmeta.source_route_incident_approval_role_binding`、`qmeta.source_route_incident_approval_policy`、`qmeta.source_route_incident_approval_callback`、`qmeta.source_route_incident_approval_escalation`，记录审批角色、策略、签名回调、拒绝/重放/超时/撤销升级。
- Signed callback：新增 `POST /webhooks/wecom/source-route-incident-approval-callbacks`，不要求 Bearer token，但必须带 `X-QData-Timestamp`、`X-QData-Nonce`、`X-QData-Signature: sha256=<hmac>`；签名密钥只从 `QDATA_DELTA6_WECOM_CALLBACK_SECRET` 读取。
- Admin callback：新增 `POST /admin/source-route-incident-approval-wecom-callbacks`，要求 admin token，并复用同一套企业微信回调验签和治理规则。
- Kappa/Upsilon：新增 role bindings、policies、callbacks、escalations 四个 GET endpoint；Upsilon Vendor 分组展示四张治理表和 replay/denied/escalation 指标。
- CLI/smoke：新增 `scripts/run_delta6_route_incident_approval_governance.py` 和 `scripts/smoke_delta6_route_incident_approval_governance.py`，覆盖自批拒绝、第一签 pending quorum、超时升级、nonce replay 拒绝和第二签 applied。

本地运行：

```bash
python3 scripts/smoke_delta6_route_incident_approval_governance.py --base-url http://127.0.0.1:18080 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_delta6_route_incident_approval_governance.py --resource role-bindings --limit 5 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_delta6_route_incident_approval_governance.py --resource policies --limit 5 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_delta6_route_incident_approval_governance.py --resource callbacks --limit 5 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_delta6_route_incident_approval_governance.py --resource escalations --limit 5 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/report_kappa_admin.py --resource source-route-incident-approval-callbacks --limit 5
python3 scripts/report_kappa_admin.py --resource source-route-incident-approval-escalations --limit 5
```

当前本地验收状态：

- Migration：`0052_postgresql_automation_delta6_route_incident_approval_governance.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback，并已在 Docker PostgreSQL 连续应用两次；`scripts/apply_postgres_migrations.sh` 现在会检测当前库已应用到的 PostgreSQL migration prefix，避免在持久卷上反复重放旧约束。
- 单元测试：`276` 个 unittest 通过，覆盖 Delta-6 纯函数、API 签名回调免 Bearer 分发、admin callback 鉴权、Kappa endpoint 和 Upsilon marker。
- Delta-6 smoke：输出 `delta6_route_approval_governance_smoke=ok denied=denied first=pending_quorum second=applied replay=replay_rejected replay_count=1 escalations=3 approved=approved`，包含 callback_code、command_code、control 和 source。
- CLI/Kappa：role-bindings/policies/callbacks/escalations 查询均可返回 `rows>=1`；Kappa Admin API smoke 新增 `source_route_incident_approval_role_bindings=ok rows=2`、`source_route_incident_approval_policies=ok rows=1`、`source_route_incident_approval_callbacks=ok rows=3`、`source_route_incident_approval_escalations=ok rows=5`。
- Upsilon/API：`upsilon_console=ok html_bytes=688976 markers=61`，核心 REST smoke 继续输出 health/price/constraints/tradable/matrix 全部 ok。
- 安全边界：浏览器直接访问需要 token 的 `/admin/*` 仍会返回 `missing bearer token`；企业微信回调入口不靠 Bearer 放行，而靠 HMAC 签名、nonce 和治理策略放行。

## 路由故障审批韧性层 Epsilon-6

Epsilon-6 阶段把 Delta-6 的生产审批治理继续加固成长期可运行的韧性层：所有企业微信审批回调先拿 PostgreSQL advisory lock，再经过状态机守卫，之后写入不可变审计哈希链；超时审批会自动生成 SLA planned action，恢复演练会验证 DB reconnect、哈希链、锁 key 和终态阻断。

- Concurrency lock：新增 `qmeta.source_route_incident_approval_lock_event`，按 `control_code/approval_code/batch_code` 生成 deterministic lock scope 和 signed bigint advisory lock key，记录 acquired/busy/released、nonce、request_hash、held_ms 和错误。
- State transition：新增 `qmeta.source_route_incident_approval_state_transition`，在调用 Delta-6 前后记录 approval/control 状态；已 approved/rejected/cancelled/expired 的终态目标会被 Epsilon-6 阻断，不再进入 Delta-6/Gamma-6。
- Immutable audit chain：新增 `qmeta.source_route_incident_approval_audit_hash`，对 callback、state transition、SLA action 和 recovery drill 生成 `previous_hash -> payload_hash -> entry_hash` 链，可按 chain scope 校验篡改。
- SLA/recovery：新增 `qmeta.source_route_incident_approval_sla_action` 和 `qmeta.source_route_incident_approval_recovery_drill`；SLA 自动处置只写 planned action，不外发真实消息，恢复演练只写检查证据。
- API/Kappa/Upsilon：企业微信 webhook 和 admin callback 已升级为 Epsilon wrapper；新增 lock events、state transitions、audit chain、SLA actions、recovery drills 五个 Kappa endpoint 和 Upsilon Vendor 表。

本地运行：

```bash
python3 scripts/smoke_epsilon6_route_incident_approval_resilience.py --base-url http://127.0.0.1:18080 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_epsilon6_route_incident_approval_resilience.py --resource lock-events --limit 5
python3 scripts/run_epsilon6_route_incident_approval_resilience.py --resource state-transitions --limit 5
python3 scripts/run_epsilon6_route_incident_approval_resilience.py --resource audit-chain --limit 5
python3 scripts/run_epsilon6_route_incident_approval_resilience.py --resource sla-actions --limit 5
python3 scripts/run_epsilon6_route_incident_approval_resilience.py --resource recovery-drills --limit 5
python3 scripts/run_epsilon6_route_incident_approval_resilience.py --resource verify-chain
python3 scripts/run_epsilon6_route_incident_approval_resilience.py --resource sla-automation
python3 scripts/run_epsilon6_route_incident_approval_resilience.py --resource recovery-drill --drill-type full --trigger-mode manual
python3 scripts/run_lambda_worker.py --task route_incident_approval_resilience --dry-run --trade-date 2026-07-29
python3 scripts/run_mu_scheduler.py --once --force-due --schedule-code epsilon6_route_incident_approval_resilience_15m --trade-date 2026-07-29
python3 scripts/report_kappa_admin.py --resource source-route-incident-approval-lock-events --limit 5
python3 scripts/report_kappa_admin.py --resource source-route-incident-approval-audit-chain --limit 5
python3 scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18080 --token devtoken,smoketoken --trade-date 2026-07-29
```

当前本地验收状态：

- Migration：`0053_postgresql_automation_epsilon6_route_incident_approval_resilience.sql` 已加入增量迁移、Docker init、`db/update.sql`、`db/table.sql` 和 rollback，并已在 Docker PostgreSQL 连续应用两次；`scripts/apply_postgres_migrations.sh` 输出 `Detected applied PostgreSQL migration prefix: 0053`。
- 单元测试：`Ran 281 tests ... OK`，覆盖 Epsilon-6 锁 key、状态机、哈希链、API wrapper、Kappa、Upsilon、Lambda worker 和 Mu 参数透传。
- Epsilon-6 smoke：输出 `epsilon6_route_approval_resilience_smoke=ok first=pending_quorum second=applied terminal_block=invalid_terminal_state audit_broken=0 sla_actions=1 lock_events=3 transitions=3 audit_hashes=5 drills=1 approved=approved`。
- CLI/Worker/Mu：`verify-chain` 输出 `broken_count=0`；lock-events/state-transitions/audit-chain/sla-actions/recovery-drills 查询均返回真实行；Worker dry-run 输出 `task name=route_incident_approval_resilience status=skipped processed=18 warning=18`，非 dry-run 输出 `status=warning processed=18 success=3 warning=4 failed=0`；Mu 强制触发输出 `tick schedule=epsilon6_route_incident_approval_resilience_15m task=route_incident_approval_resilience status=warning lock_acquired=True worker_run_id=54`。
- Kappa/Upsilon/API：Kappa Admin API smoke 使用 `devtoken,smoketoken` 轮换 token 后通过，Epsilon 五个端点输出 `lock_events=ok rows=6`、`state_transitions=ok rows=6`、`audit_chain=ok rows=20`、`sla_actions=ok rows=7`、`recovery_drills=ok rows=4`；Upsilon 输出 `upsilon_console=ok html_bytes=730051 markers=66`；核心 REST smoke 继续输出 health/price/constraints/tradable/matrix 全部 ok。
- 安全边界：Epsilon-6 不保存企业微信密钥，不产生真实外部副作用；它只在 Delta-6/Gamma-6/Omega 审批控制面前后增加并发一致性、状态守卫、审计和恢复证据。

## 路由故障审批发布闸门 Zeta-6

Zeta-6 阶段把 Epsilon-6 的韧性层推进到长期发布和值守：上线前先跑跨环境 preflight，企业微信回调入口支持 current/next 双密钥验签选择，发布/压测/审计证据进入 Kappa/Upsilon，可导出监管审计包。

- Release preflight：新增 `qmeta.source_route_incident_approval_release_preflight`，检查 DB reconnect、Epsilon audit chain、最新 recovery drill、worker schedule 和 current/next secret 配置。
- Secret rotation：新增 `qmeta.source_route_incident_approval_secret_rotation`，记录 current/next 哪个 label 命中、signature digest、nonce、request_hash 和摘要证据；不落库密钥原文。
- Concurrency/audit：新增 `qmeta.source_route_incident_approval_concurrency_test` 和 `qmeta.source_route_incident_approval_audit_export`，保存并发回调压测摘要和可复验的审计导出包 hash。
- API/Kappa/Upsilon：企业微信 webhook 先尝试 current，再尝试 `QDATA_ZETA6_WECOM_CALLBACK_SECRET_NEXT`；新增 release preflights、secret rotations、concurrency tests、audit exports 四个 Kappa endpoint 和 Upsilon Vendor 表。
- Worker/Mu：新增 `route_incident_approval_release` task 和 `zeta6_route_incident_approval_release_30m` schedule，定时跑 preflight 和 audit export。

本地运行：

```bash
python3 scripts/run_zeta6_route_incident_approval_release.py --resource preflight --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_zeta6_route_incident_approval_release.py --resource secret-rotation-check --next-secret zeta6-next-local-secret
python3 scripts/run_zeta6_route_incident_approval_release.py --resource audit-export --chain-scope route-approval:control_code:<control_code>
python3 scripts/smoke_zeta6_route_incident_approval_release.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_lambda_worker.py --task route_incident_approval_release --dry-run --trade-date 2026-07-30
python3 scripts/report_kappa_admin.py --resource source-route-incident-approval-release-preflights --limit 5
```

浏览器访问说明：直接打开 `/admin/source-route-incident-approval-*` 这类 API 会返回 `missing bearer token` 是正常保护行为；打开 `http://127.0.0.1:18080/` 会自动跳到控制台，或使用 `/admin/console?token=devtoken`。

当前本地验收状态：

- Migration：Docker PostgreSQL 已应用到 `0054_postgresql_automation_zeta6_route_incident_approval_release.sql`，再次执行 `scripts/apply_postgres_migrations.sh` 会识别 `Detected applied PostgreSQL migration prefix: 0054` 并跳过旧迁移。
- 单元测试：`Ran 287 tests ... OK`，覆盖 Zeta-6 双密钥验签脱敏、API next secret 选择、Kappa/Upsilon、Lambda worker、Mu 参数透传和既有全链路回归。
- Zeta-6 smoke：输出 `zeta6_route_approval_release_smoke=ok preflight=success rotation=success verified_secret=next concurrency=success export=success broken_hashes=0 package_hash=e3b7713ad306473145af28d3b0b5595ea915cd2b3b964e4bc0801d70b5688b09`。
- CLI/Worker：release-preflights、secret-rotations、concurrency-tests、audit-exports 查询均返回真实行；Worker dry-run 输出 `task name=route_incident_approval_release status=skipped processed=7 warning=7`，非 dry-run 输出 `task name=route_incident_approval_release status=success processed=7 success=7 warning=0 failed=0`。
- Kappa/Upsilon/API：Kappa Admin API smoke 输出四个 Zeta endpoint `rows>=1`，Upsilon 输出 `upsilon_console=ok html_bytes=735818 markers=70`，核心 REST smoke 继续输出 health/price/constraints/tradable/matrix 全部 ok。

## 真实供应商生产主源闭环 Eta-6

Eta-6 阶段把“授权主供应商能不能当生产主源”做成最终闭环判定：它读取 Omicron-5 合同/entitlement、Theta-3 live pilot、Pi-5 promotion、Sigma-5 稳定性、Tau-5 成本、Upsilon-5 路由执行和回滚 guard，输出 run、dataset check、decision 三层审计。默认是 review-only，不调用外部供应商，不保存 token 明文。

- Production run：新增 `qmeta.vendor_production_source_run`，记录生产闭环 status、role、ready/blocked dataset 计数、live env presence、生产评分和脱敏 evidence。
- Dataset check：新增 `qmeta.vendor_production_source_dataset_check`，逐 dataset 记录合同、授权、pilot、promotion、稳定性、成本、路由执行和 rollback guard。
- Decision：新增 `qmeta.vendor_production_source_decision`，逐 gate 记录 profile/env、contract、live_pilot、primary_promotion、stability、cost_quota、route_execution、rollback_guard 和 final_decision。
- Worker/Mu：新增 `vendor_production_source_closure` task 和 `eta6_vendor_production_source_closure_30m` schedule，可长期 30 分钟复核一次。
- Kappa/Upsilon：新增 `/admin/vendor-production-source-runs`、`/admin/vendor-production-source-dataset-checks`、`/admin/vendor-production-source-decisions` 三个 endpoint，并在 Vendor 分组展示三张表。

本地运行：

```bash
python3 scripts/run_eta6_vendor_production_source.py --resource run --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/smoke_eta6_vendor_production_source.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata
python3 scripts/run_lambda_worker.py --task vendor_production_source_closure --dry-run --trade-date 2026-07-30
python3 scripts/run_mu_scheduler.py --schedule-code eta6_vendor_production_source_closure_30m --force-due --once --trade-date 2026-07-30
python3 scripts/report_kappa_admin.py --resource vendor-production-source-runs --limit 5
```

当前本地验收状态：

- Migration：Docker PostgreSQL 已应用到 `0055_postgresql_vendor_eta6_production_source_closure.sql`，再次执行 `scripts/apply_postgres_migrations.sh` 会识别 `Detected applied PostgreSQL migration prefix: 0055` 并跳过旧迁移。
- 单元测试：`Ran 291 tests ... OK`，覆盖 Eta-6 token 脱敏、生产 ready/monitoring 判定、Kappa/Upsilon、Lambda worker、Mu 参数透传、因子回测 demo 和既有全链路回归。
- Eta-6 smoke：输出 `eta6_vendor_production_source_smoke=ok status=blocked role=blocked datasets=7 production_ready=0 blocked=7 decisions=63 live_base_url_present=False live_token_present=True score=12.5000`。
- CLI/Worker/Mu：runs、dataset-checks、decisions 查询均返回真实行；Worker dry-run 输出 `task name=vendor_production_source_closure status=skipped processed=7 success=0 warning=7 failed=0`，非 dry-run 输出 `status=warning processed=7 success=0 warning=7 failed=0`；Mu 强制触发输出 `tick schedule=eta6_vendor_production_source_closure_30m task=vendor_production_source_closure status=warning lock_acquired=True worker_run_id=59`。
- Kappa/Upsilon/API：Kappa Admin API smoke 输出 Eta-6 三个 endpoint 均 ok：production runs `rows=3`、dataset checks `rows=20`、decisions `rows=20`；Upsilon 输出 `upsilon_console=ok html_bytes=807462 markers=73`；核心 REST smoke 继续输出 health/price/constraints/tradable/matrix 全部 ok。
- 当前 blocked 是正确保护：本机没有真实 `QDATA_VENDOR_BASE_URL`，且合同/entitlement、full-market pilot、promotion、稳定性、成本和路由执行证据仍未全部达到生产主源标准，因此 Eta-6 不会误报 production_ready。

## 下一步

- 下一阶段做真实供应商资料填充和 live pilot 扩大：配置真实 `QDATA_VENDOR_BASE_URL`、`QDATA_VENDOR_TOKEN`、`QDATA_VENDOR_AUTH_MODE=bearer`、合同引用、再分发授权、生产限频、日配额和 SLA。
- 把 Omicron-5 合同和 entitlement 从模板状态更新为正式授权后，再跑 Eta-3 endpoint probe、Zeta-3 onboarding、Epsilon-3 gate、Theta-3 canary/full-market pilot、Pi-5 promotion 和 Eta-6 closure。
- Theta-3 canary 通过后，把 `--pilot-scope full_market --full-market --max-symbols <n>` 扩大到全市场，并把 5/20/60 窗口结果作为 Pi-5 主源切换和 Eta-6 production_ready 证据。
- 企业微信仍可单独配置 `QDATA_DELTA2_WECOM_WEBHOOK_URL`，用于后续真实告警通知闭环。
