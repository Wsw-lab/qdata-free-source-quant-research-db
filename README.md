# QData

[English](README_EN.md) · [不可变快照 ADR](docs/adr/0001-research-snapshot-and-time-contract.md) · [信号时序 ADR](docs/adr/0002-after-close-signal-timing.md)

QData 是一个 A 股研究数据工程原型。当前可在无网络、无 Docker、无付费数据的环境中，用确定性合成 fixture 验证 Python SDK、`research_snapshot_v1` 合约和因子 API 的时序算术。它不是已验证的生产数据服务，也不提供策略收益证据。

## 能力矩阵

| 能力 | 当前状态 | 可复验证据与边界 |
|---|---|---|
| `research_snapshot_v1` | 已实现 | 构建规范化 CSV/JSON manifest，记录 SHA-256、cutoff、timezone、source、data version、行数和质量状态；验证未知 schema、篡改、重复主键、缺失字段和晚到数据时 fail closed。公开 fixture 是合成合约样本，不是市场数据。 |
| 本地 Python SDK | 已实现 | 默认 mock 后端可离线查询证券、日历、价格、交易约束、PIT 基本面、指数/行业、股票池、因子和健康信息。 |
| 因子 API 时序算术 | 已实现 | 收盘后信号 → 下一交易日开盘成交 → 当日收盘计值；只验证 API/时序对齐，不代表回测、收益或交易建议。 |
| 质量、版本与批次语义 | 单元验证 | 严格完整率门禁、显式分钟频率失败、PIT/版本过滤、不可变版本和批次生命周期由确定性 fake/unit test 覆盖。 |
| ClickHouse vintage 迁移 selector | 本地集成验证 | 已在本地 Docker 的 ClickHouse 24.8.14.39 上，以 fresh old-key full schemas 和 four source rows in one old-key part（四行位于一个旧键 part）跑通 create-copy-EXCHANGE、old-key backup 及 OPTIMIZE FINAL 后验证。该证据只覆盖迁移 selector，不覆盖生产运行；CI does not run database integration。 |
| PostgreSQL 查询选择器 | 本地部分集成验证 | 已在一次性 Postgres 16 数据库中从零应用 `0001`、`0006` 和 seed，并通过真实 psycopg 验证 PostgreSQL array binding、`DISTINCT ON`、PIT 基本面以及 `asof`/`vintage` 版本与复权因子选择。行情边界仍为确定性 fake；query plans、cross-store transactions、故障恢复、性能和长期运行仍未验证，且 CI does not run database integration。 |
| 免费数据源适配 | 研究候选 | 覆盖、稳定性、限频、服务承诺、许可和再分发权取决于上游；商业或生产使用前必须单独完成法律、合同、覆盖和 SLA 审查。 |

## 全新 checkout 的唯一离线绿色路径

前置条件：Python 3.9–3.12。在仓库根目录执行：

```bash
snapshot_root="$(mktemp -d)"
python3 examples/build_research_snapshot.py build "$snapshot_root/research_snapshot_v1"
python3 examples/build_research_snapshot.py verify "$snapshot_root/research_snapshot_v1"

python3 examples/quickstart.py
python3 examples/factor_api_arithmetic_demo.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

这条路径直接从 checkout 导入仓库代码，不启动数据库、不调用外部数据源，也不需要付费凭据。snapshot build 不会覆盖不同内容的既有目录；verify 会重新校验文件集合、内容哈希和合约语义。CI workflow 配置为在 Python 3.9、3.10、3.11 和 3.12 上先固定 packaging toolchain，再离线执行本地 editable install、全量 unittest、两个公开示例及 snapshot build/verify/repeatability 检查；这里不声称远端 GitHub CI 已实际运行。

## `research_snapshot_v1` 优先工作流

构建公开合成 fixture：

```bash
python3 examples/build_research_snapshot.py build /tmp/qdata-research-snapshot-v1
```

在研究消费前验证：

```bash
python3 examples/build_research_snapshot.py verify /tmp/qdata-research-snapshot-v1
```

正式研究输入应固定到已验证的不可变 snapshot，不应直接依赖未固定的 `latest` 响应。字段的经济日期不等于研究者当时已知；`available_at` 必须不晚于 snapshot cutoff。完整决策见[不可变快照 ADR](docs/adr/0001-research-snapshot-and-time-contract.md)。

## Quickstart

```bash
python3 examples/quickstart.py
```

该示例使用默认 mock 后端展示 SDK 查询形态，并显式支持直接从 fresh checkout 导入本仓库代码。

## 收盘后信号 → 下一开盘算术

```bash
python3 examples/factor_api_arithmetic_demo.py
```

示例的时间轴是：

1. `2024-01-02` 收盘后取得 mock `momentum_20d` 信号；
2. 按因子值排序合成股票池；
3. `2024-01-03` 开盘作为成交价；
4. `2024-01-03` 收盘作为计值价；
5. 对每个样本计算 `close / open - 1`，再展示桶和基准的纯算术。

输出会明确显示 `after_close`、`next_session_open` 和 `next_session_close`。这些数字来自确定性 mock fixture，仅用于验证 API、排序和时间对齐，不是策略表现、真实市场证据或投资建议。完整决策见[信号时序 ADR](docs/adr/0002-after-close-signal-timing.md)。

## 测试

全量离线 unittest：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

聚焦验证公开时序算术：

```bash
python3 -m unittest -v tests.test_factor_api_arithmetic_demo
```

若调用者另行提供已加载 `0001`、`0006` 和 seed 的一次性 PostgreSQL
数据库，可运行有副作用隔离要求的真实驱动测试：

```bash
QDATA_TEST_POSTGRES_DSN='postgresql://...' \
  python3 -m unittest -v tests.test_postgres_sql_backend_integration
```

未设置该变量时，真实数据库用例明确 skip；seed 的历史 `ingest_time`
契约仍由离线测试覆盖。不要把该变量指向生产库或共享数据库。

本 README 不记录易过期的测试数量；以当前命令输出和 CI 为准。

## 可选数据库拓扑与安全默认值

`docker-compose.yml` 将 PostgreSQL、ClickHouse 和 API 的宿主端口绑定到 `127.0.0.1`。可先做不启动 daemon 的静态检查：

```bash
docker compose config --quiet
```

数据库容器、迁移和 SQL backend 不属于上面的离线绿色路径。ClickHouse migration selector 已在本地 Docker 的 ClickHouse 24.8.14.39 上，用 fresh old-key full schemas 与 four source rows in one old-key part（四行位于一个旧键 part）验证 create-copy-EXCHANGE、old-key backup 和 OPTIMIZE FINAL；这不是整套后端的生产验证。PostgreSQL 侧已在一次性 Postgres 16 数据库中真实执行 array binding、`DISTINCT ON`、PIT、`asof` 和 `vintage` 选择，但 ClickHouse 行情边界在该测试中仍为 fake。query plans、cross-store transactions、故障恢复、性能和长期运行仍需真实集成测试，且 CI does not run database integration。尤其要注意：修正 ClickHouse sorting key 的迁移只能保护未来 merge；旧 key 已经合并丢失的 vintage 无法由迁移恢复，只能从保留的源数据或历史已验证 snapshot 重建。

## 项目边界

- 当前交付物是研究数据工程原型，不是商业级行情再分发或生产 SLA 承诺。
- mock 和 synthetic fixture 只证明确定性接口与合约行为，不证明覆盖率、正确率、可交易性或投资收益。
- 免费/公开源的许可、条款、归属、缓存、再分发、覆盖、限频和 SLA 必须逐源复核。
- 真实 PostgreSQL 数据访问已有上述限定 selector 证据；query plans、cross-store transactions 与完整双库后端仍待验证，局部真实测试和单元 fake 都不能替代生产证据。
- `.env`、本地报告、构建产物和生成型研究输出默认不进入版本控制；凭据不得提交。
