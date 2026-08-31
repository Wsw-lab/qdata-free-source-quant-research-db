# QData

[English](README_EN.md) · [不可变快照 ADR](docs/adr/0001-research-snapshot-and-time-contract.md) · [信号时序 ADR](docs/adr/0002-after-close-signal-timing.md)

QData 是一个 A 股研究数据工程原型。当前可在无网络、无 Docker、无付费数据的环境中，用确定性合成 fixture 验证 Python SDK、`research_snapshot_v1` 合约和因子 API 的前复权参考算术。它不是已验证的生产数据服务，也不提供策略收益证据。

## 能力矩阵

| 能力 | 当前状态 | 可复验证据与边界 |
|---|---|---|
| `research_snapshot_v1` | 已实现 | 构建规范化 CSV/JSON manifest，记录 SHA-256、cutoff、timezone、source、data version、行数和质量状态；build 与 verify 均校验 `close_adjusted = close_raw * adjustment_factor`（绝对容差 `0.000001`），并在未知 schema、篡改、重复主键、缺失字段、晚到数据或矛盾价格三元组时 fail closed。公开 fixture 是合成合约样本，不是市场数据。 |
| 本地 Python SDK | 已实现 | 默认 mock 后端可离线查询证券、日历、价格、交易约束、PIT 基本面、指数/行业、股票池、因子和健康信息。公开 `get_factor` 与 `get_adjustment_factor` 均支持 `latest`、带时区 `asof_time` 的 `asof` 和固定 `data_version` 的 `vintage`；模式与选择器不匹配时 fail closed。SQL selector 只接纳 PostgreSQL 中成功、已完成且未 recalled 的精确 batch-bound dataset version。 |
| 因子 API 前复权参考算术 | 已实现 | 收盘后信号 → 下一交易日前复权开盘参考值 → 同日前复权收盘标记；只验证 API、排序和参考值算术，未验证下一交易日可交易性，不是成交、执行或回测，也不是市场或投资证据。 |
| 质量、版本与批次语义 | 单元验证 | 严格完整率门禁、显式分钟频率失败、PIT/版本过滤、不可变版本和批次生命周期由确定性 fake/unit test 覆盖。 |
| ClickHouse vintage 迁移 selector | 本地集成验证 | 已在本地 Docker 的 ClickHouse 24.8.14.39 上从 fresh old-key full schemas 与 four source rows in one old-key part 跑通行情/因子 create-copy-EXCHANGE、old-key backup 与 OPTIMIZE FINAL。因子 fresh schema 和 `0062` 使用 plain `MergeTree` 保留等时刻冲突证据；完全相同重试折叠，不同 payload 会 fail closed。该证据不覆盖生产运行；CI does not run database integration。 |
| PostgreSQL 查询选择器 | 本地部分集成验证 | 已在一次性 Postgres 16 数据库中从零应用 `0001`、`0006`、`0058`–`0061` 和 seed，并通过真实 psycopg 验证 PostgreSQL array binding、`DISTINCT ON`、显式上海日终 cutoff、稳定 ID rename/冲突拒绝、历史标签、PIT 基本面/成员关系、成功批次和 active/superseded version 门禁、suspension-only 约束、不可变 universe type、空股票池快照与同日重跑；与 ClickHouse 的因子 version admission 也做了有界实库测试。query plans、cross-store transactions、故障恢复、性能和长期运行仍未验证，且 CI does not run database integration。 |
| 免费数据源适配 | 研究候选 | 覆盖、稳定性、限频、服务承诺、许可和再分发权取决于上游；商业或生产使用前必须单独完成法律、合同、覆盖和 SLA 审查。 |

## 全新 checkout 的唯一离线绿色路径

前置条件：Python 3.10–3.12。在仓库根目录执行：

```bash
snapshot_root="$(mktemp -d)"
python3 examples/build_research_snapshot.py build "$snapshot_root/research_snapshot_v1"
python3 examples/build_research_snapshot.py verify "$snapshot_root/research_snapshot_v1"

python3 examples/quickstart.py
python3 examples/factor_api_arithmetic_demo.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

这条路径直接从 checkout 导入仓库代码，不启动数据库、不调用外部数据源，也不需要付费凭据。snapshot build 不会覆盖不同内容的既有目录；verify 会重新校验文件集合、内容哈希和合约语义。CI workflow 配置为在 Python 3.10、3.11 和 3.12 上先固定 packaging toolchain，再离线执行本地 editable install、全量 unittest、两个公开示例及 snapshot build/verify/repeatability 检查；这里不声称远端 GitHub CI 已实际运行。

## `research_snapshot_v1` 优先工作流

构建公开合成 fixture：

```bash
python3 examples/build_research_snapshot.py build /tmp/qdata-research-snapshot-v1
```

在研究消费前验证：

```bash
python3 examples/build_research_snapshot.py verify /tmp/qdata-research-snapshot-v1
```

正式研究输入应固定到已验证的不可变 snapshot，不应直接依赖未固定的 `latest` 响应。字段的经济日期不等于研究者当时已知；`available_at` 必须不晚于 snapshot cutoff。成对行情的信号可用时间取 daily bar 与 tradability 的较晚时间，并要求其在 manifest 时区内落在 `trade_date`。V1 只对 snapshot 中实际出现的市场日期检查活跃证券完整性；它不含交易所日历，因而无法识别所有证券均缺失的整日，要求连续交易日的研究需另行固定并校验权威日历。完整决策见[不可变快照 ADR](docs/adr/0001-research-snapshot-and-time-contract.md)。

价格、复权因子与因子值接口都通过相同的严格选择器表达 `latest`、`asof` 和 `vintage`。`asof` 必须提供带时区的 `asof_time`，并同时约束版本生效/批次完成时间以及行级 ingest、announce、effective 或 calc 时间；`vintage` 必须提供唯一、精确 batch-bound 的 `data_version`。SQL selector 会先从 PostgreSQL 解析成功、已完成且状态为 `active`/`superseded` 的 dataset versions，再限制 ClickHouse/复权行；orphan、running、failed 与 recalled 版本不可见。完全相同的因子重试可折叠，同一 identity/data-version/calc-time 下 payload 不同则 fail closed。`start_date`/`end_date` 只过滤经济日期，只有 `asof_time` 才是历史可见性边界。

SQL 主数据 producer 同样 fail closed：只有 symbol/name 的 placeholder 可建立当前行情映射，但不会写入 PIT 历史；ticker rename 必须携带稳定 `security_id` 和 effective date，若目标 ticker 已由另一 ID（包括 placeholder）占用则在主数据 batch 前拒绝，不做跨库自动 re-key。范围行情/复权/因子结果按每个 `trade_date` 标注历史 ticker，ticker recycling 造成多 ID 歧义时要求改用 stable ID。PIT 日期截止统一为 `Asia/Shanghai` 次日零点的排他边界。行业/指数/非规则股票池先选 natural-key revision，再只保留实体最新有效 episode；`universe_type` 不可原地改写。交易约束中的 ST 来自 PIT status，过滤依赖的字段缺少证据时排除该成员。

## Quickstart

```bash
python3 examples/quickstart.py
```

该示例使用默认 mock 后端展示 SDK 查询形态，并显式支持直接从 fresh checkout 导入本仓库代码。

## 收盘后信号 → 下一日前复权参考算术

```bash
python3 examples/factor_api_arithmetic_demo.py
```

示例的时间轴是：

1. `2024-01-02` 收盘后取得 mock `momentum_20d` 信号；
2. 对信号日筛选出的合成股票池按因子值排序；这个筛选未验证下一交易日可交易性；
3. 读取 `adjust="forward"` 的 `2024-01-03` 开盘值作为 `adjusted_open_reference`；
4. 读取同日的前复权收盘值作为 `adjusted_close_mark`；
5. 对每个样本计算 `marked_change = adjusted_close_mark / adjusted_open_reference - 1`，再展示最高/最低因子样本及全体均值的纯算术。

输出会明确显示 `signal_timing=after_close`、`reference_timing=next_session_forward_adjusted_open_to_close` 和 `next_session_tradability_verified=false`。这些数字来自确定性 mock fixture，仅用于验证 API、排序和前复权参考算术；它不是成交、执行或回测，不是可交易价格、真实市场证据或投资建议。完整决策见[信号时序 ADR](docs/adr/0002-after-close-signal-timing.md)。

## 测试

全量离线 unittest：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

聚焦验证公开前复权参考算术：

```bash
python3 -m unittest -v tests.test_factor_api_arithmetic_demo
```

若调用者另行提供已加载 `0001`、`0006`、`0058`–`0061` 和 seed 的一次性 PostgreSQL
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

数据库容器、迁移和 SQL backend 不属于上面的离线绿色路径。ClickHouse 24.8.14.39 已验证行情/因子 create-copy-EXCHANGE、old-key backup、plain-MergeTree 冲突保留和 OPTIMIZE FINAL；PostgreSQL 16 已验证 PIT 身份、批次/version/cutoff/revision、约束与股票池快照选择，并与 ClickHouse 做了 orphan/冲突因子 admission 测试。这不是生产验证：query plans、跨库原子性、故障恢复、性能和长期运行仍待验证，且 CI does not run database integration。迁移只能保护尚未被旧 ReplacingMergeTree 合并掉的行；已丢失的 vintage 或冲突证据只能从保留源数据或历史已验证 snapshot 重建。

## 项目边界

- 当前交付物是研究数据工程原型，不是商业级行情再分发或生产 SLA 承诺。
- mock 和 synthetic fixture 只证明确定性接口与合约行为，不证明覆盖率、正确率、可交易性或投资收益。
- 免费/公开源的许可、条款、归属、缓存、再分发、覆盖、限频和 SLA 必须逐源复核。
- 真实 PostgreSQL 数据访问已有上述限定 selector 证据；query plans、cross-store transactions 与完整双库后端仍待验证，局部真实测试和单元 fake 都不能替代生产证据。
- `.env`、本地报告、构建产物和生成型研究输出默认不进入版本控制；凭据不得提交。
