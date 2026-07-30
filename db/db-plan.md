# 数据库变更计划

## 1. 目标

建立 A 股量化数据底座 MVP 的第一版数据库结构，支持：

- 证券主数据。
- 数据源、数据集、批次和版本管理。
- 交易日历。
- 复权因子、停复牌、涨跌停。
- Point-in-Time 财务、业绩预告、业绩快报。
- 指数成分、行业分类、股票池。
- 公司事件。
- 因子定义、因子版本、因子值。
- 数据质量检查。
- 查询审计。

## 2. 脚本清单

| 文件 | 数据库 | 类型 | 说明 |
|---|---|---|---|
| `db/migrations/0001_postgresql_init.sql` | PostgreSQL | 初始化 | 创建 `qmeta`、`qpit` schema 及元数据/PIT 表 |
| `db/migrations/0002_clickhouse_init.sql` | ClickHouse | 初始化 | 创建 `qts` 库及行情/因子时间序列表 |
| `db/migrations/0003_postgresql_pipeline_scheduler.sql` | PostgreSQL | 增量 | 新增 pipeline job/run/watermark 调度表 |
| `db/migrations/0004_postgresql_full_market_pipeline.sql` | PostgreSQL | 增量 | 为全市场生产新增批次、完整性和缺失证券字段 |
| `db/migrations/0005_postgresql_production_gamma.sql` | PostgreSQL | 增量 | 新增交易所级完整率字段和生产修复队列表 |
| `db/migrations/0006_postgresql_quant_market_delta.sql` | PostgreSQL | 增量 | 新增复权/约束/universe 查询索引和矩阵导出审计表 |
| `db/migrations/0007_postgresql_service_fusion_epsilon.sql` | PostgreSQL | 增量 | 新增多源优先级、字段冲突、API token、请求审计和多源质量日报表 |
| `db/migrations/0008_postgresql_ops_zeta.sql` | PostgreSQL | 增量 | 新增 SLA 策略、告警事件和运维看板快照表 |
| `db/migrations/0009_postgresql_vendor_eta.sql` | PostgreSQL | 增量 | 新增供应商接入配置、provider 错误事件、压测运行和供应商评分表 |
| `db/migrations/0010_postgresql_vendor_theta.sql` | PostgreSQL | 增量 | 新增供应商字段映射、分片压测 suite、上线决策报告，并扩展 provider SLA 阈值 |
| `db/migrations/0011_postgresql_ops_iota.sql` | PostgreSQL | 增量 | 新增租户/项目/主体/数据集权限、API 用量日报、通知通道和供应商压测调度 |
| `db/migrations/0012_postgresql_ops_lambda.sql` | PostgreSQL | 增量 | 新增后台自动化 worker run/task run 运行记录 |
| `db/migrations/0013_postgresql_ops_mu.sql` | PostgreSQL | 增量 | 新增 worker schedule、lock、heartbeat 和 scheduler tick 调度运行层 |
| `db/migrations/0014_postgresql_ops_nu.sql` | PostgreSQL | 增量 | 新增部署 release、健康快照、健康检查明细和部署事件 |
| `db/migrations/0015_postgresql_product_xi.sql` | PostgreSQL | 增量 | 新增数据产品、价格计划、订阅、预算策略、预算快照和预算告警 |
| `db/migrations/0016_postgresql_billing_omicron.sql` | PostgreSQL | 增量 | 新增账单、账单明细和账单事件，用于收入、应收和实收状态 |
| `db/migrations/0017_postgresql_vendor_pi.sql` | PostgreSQL | 增量 | 新增供应商上线复核、5/20/60 窗口压测结论和推荐角色 |
| `db/migrations/0018_postgresql_revenue_rho.sql` | PostgreSQL | 增量 | 新增收入对账、账单重算差异、AR aging 和客户健康快照 |
| `db/migrations/0019_postgresql_runtime_sigma.sql` | PostgreSQL | 增量 | 新增运行日志、运行指标、运行日报和容量告警，并扩展 alert_event 运行告警类型 |
| `db/migrations/0020_postgresql_payments_tau.sql` | PostgreSQL | 增量 | 新增真实回款导入批次、付款流水、发票匹配、收入 ledger 和日汇率表 |
| `db/migrations/0021_postgresql_strategy_phi.sql` | PostgreSQL | 增量 | 新增统一策略、策略运行、策略信号、策略决策和升级事件表 |
| `db/migrations/0022_postgresql_governance_chi.sql` | PostgreSQL | 增量 | 新增权限决策审计、项目治理快照和治理动作表 |
| `db/migrations/0023_postgresql_automation_psi.sql` | PostgreSQL | 增量 | 新增决策自动化执行 run/action 审计表 |
| `db/migrations/0024_postgresql_automation_omega.sql` | PostgreSQL | 增量 | 新增自动化审批、执行器、执行尝试、重试和回滚控制表 |
| `db/migrations/0025_postgresql_automation_alpha2.sql` | PostgreSQL | 增量 | 新增 webhook/script 沙箱执行白名单、secret 引用和沙箱 executor |
| `db/migrations/0026_postgresql_automation_beta2.sql` | PostgreSQL | 增量 | 新增外部通知/审批通道、dispatch 审计和恢复 runbook |
| `db/migrations/0027_postgresql_automation_gamma2.sql` | PostgreSQL | 增量 | 新增多环境通知通道 profile、联调验证记录和密钥轮换演练 |
| `db/migrations/0028_postgresql_automation_delta2.sql` | PostgreSQL | 增量 | 新增企业微信 live provider 回执审计和 live profile |
| `db/migrations/0029_postgresql_vendor_epsilon3_live_gate.sql` | PostgreSQL | 增量 | 新增真实供应商 live token 压测门禁审计 |
| `db/migrations/0030_postgresql_vendor_zeta3_onboarding.sql` | PostgreSQL | 增量 | 新增真实供应商接入运营化 run/result 审计 |
| `db/migrations/0031_postgresql_vendor_eta3_live_closure.sql` | PostgreSQL | 增量 | 新增真实供应商 live 接入闭环 run/probe 审计 |
| `db/migrations/0032_postgresql_vendor_theta3_live_pilot.sql` | PostgreSQL | 增量 | 新增真实供应商 live pilot run/result 试运行审计 |
| `db/migrations/0033_postgresql_free_source_iota3_fabric.sql` | PostgreSQL | 增量 | 新增免费源联盟 fabric run/result 审计和免费源候选登记 |
| `db/migrations/0034_postgresql_free_source_kappa5_reliability.sql` | PostgreSQL | 增量 | 新增免费源 source+dataset 可靠性评分和自动降级快照 |
| `db/migrations/0035_postgresql_free_source_lambda5_recovery.sql` | PostgreSQL | 增量 | 新增免费源恢复 run/action、告警和 worker task |
| `db/migrations/0036_postgresql_free_source_mu5_recovery_execution.sql` | PostgreSQL | 增量 | 新增免费源恢复 execution、审批通知证据和结果回写 |
| `db/migrations/0037_postgresql_free_source_nu5_recovery_health.sql` | PostgreSQL | 增量 | 新增免费源恢复健康快照、审批 SLA、backlog、失败率和调度陈旧度监控 |
| `db/migrations/0038_postgresql_free_source_xi5_admission.sql` | PostgreSQL | 增量 | 新增免费源准入档案、授权/转授权/合同/配额矩阵和 source+dataset 准入快照 |
| `db/migrations/0039_postgresql_vendor_omicron5_contract.sql` | PostgreSQL | 增量 | 新增真实主供应商合同 profile、dataset entitlement、采购 readiness 快照和 6h worker schedule |
| `db/migrations/0040_postgresql_vendor_pi5_primary_promotion.sql` | PostgreSQL | 增量 | 新增授权主供应商生产切主 promotion run/result、证据闸门和 6h worker schedule |
| `db/migrations/0041_postgresql_vendor_rho5_post_promotion_monitor.sql` | PostgreSQL | 增量 | 新增主源切换后 monitor run/result、影子对账、回滚建议和 1h worker schedule |
| `db/migrations/0042_postgresql_vendor_sigma5_primary_stability.sql` | PostgreSQL | 增量 | 新增主供应商生产 SLA、容量、成本和调度稳定性 snapshot/result，以及 1h worker schedule |
| `db/migrations/0043_postgresql_vendor_tau5_cost_optimization.sql` | PostgreSQL | 增量 | 新增主供应商成本优化、路由权重计划和预算压测 snapshot，以及 6h worker schedule |
| `db/migrations/0044_postgresql_vendor_upsilon5_route_execution.sql` | PostgreSQL | 增量 | 新增路由权重执行、dataset、灰度 stage、active policy 控制面和 1h worker schedule |
| `db/migrations/0045_postgresql_vendor_phi5_route_policy_runtime.sql` | PostgreSQL | 增量 | 新增 active route policy 运行时决策审计，并补齐本地/免费/商业 provider source seed |
| `db/migrations/0046_postgresql_vendor_chi5_route_feedback.sql` | PostgreSQL | 增量 | 新增路由策略健康快照、自动熔断器、恢复探测和 15m worker schedule |
| `db/migrations/0047_postgresql_automation_psi5_route_incident.sql` | PostgreSQL | 增量 | 新增路由故障处置 action 审计和 15m worker schedule |
| `db/migrations/0048_postgresql_automation_omega5_route_incident_control.sql` | PostgreSQL | 增量 | 新增路由故障审批、企业微信回执、执行和回滚控制闭环 |
| `db/migrations/0049_postgresql_automation_alpha6_route_incident_control_health.sql` | PostgreSQL | 增量 | 新增路由故障控制健康快照、审批 SLA、企业微信回执、执行失败、回滚和调度陈旧度监控 |
| `db/migrations/0050_postgresql_automation_beta6_route_incident_operations.sql` | PostgreSQL | 增量 | 新增路由故障操作批次、审批队列明细、通知降噪和全市场压测证据 |
| `db/migrations/0051_postgresql_automation_gamma6_route_incident_approval_api.sql` | PostgreSQL | 增量 | 新增路由故障可写审批 command/item/signature、多审批人 quorum 和幂等签名审计 |
| `db/migrations/0052_postgresql_automation_delta6_route_incident_approval_governance.sql` | PostgreSQL | 增量 | 新增路由故障审批角色、策略、企业微信签名回调、超时/撤销升级和 15m 治理调度 |
| `db/migrations/0053_postgresql_automation_epsilon6_route_incident_approval_resilience.sql` | PostgreSQL | 增量 | 新增路由故障审批并发锁、状态机转移、不可变审计哈希链、SLA 动作、恢复演练和 15m 韧性调度 |
| `db/migrations/0054_postgresql_automation_zeta6_route_incident_approval_release.sql` | PostgreSQL | 增量 | 新增路由故障审批跨环境发布 preflight、密钥轮换证据、并发压测摘要、监管审计导出包和 30m 发布调度 |
| `db/migrations/0055_postgresql_vendor_eta6_production_source_closure.sql` | PostgreSQL | 增量 | 新增真实供应商生产主源闭环 run、dataset check、decision 审计和 30m 调度 |
| `db/seed/postgresql_seed.sql` | PostgreSQL | 初始化数据 | 写入本地联调最小主数据、PIT、指数、行业和因子元数据 |
| `db/seed/clickhouse_seed.sql` | ClickHouse | 初始化数据 | 写入本地联调最小行情、分钟线和因子值 |
| `db/table.sql` | PostgreSQL + ClickHouse | 汇总 | 与根目录 `core-data-model-ddl.sql` 保持一致的建表汇总 |
| `db/update.sql` | PostgreSQL + ClickHouse | 增量占位 | MVP 之后的兼容变更入口 |
| `db/rollback.sql` | PostgreSQL + ClickHouse | 回滚 | 删除本次初始化创建的对象 |

## 3. 执行顺序

1. 在 PostgreSQL 执行 `db/migrations/0001_postgresql_init.sql`。
2. 在 ClickHouse 执行 `db/migrations/0002_clickhouse_init.sql`。
3. 在 PostgreSQL 执行 `db/seed/postgresql_seed.sql`。
4. 在 ClickHouse 执行 `db/seed/clickhouse_seed.sql`。
5. 跑数据质量检查任务，确认表结构和索引可用。

本地 Docker 环境会自动按以上顺序执行。

## 4. 兼容旧数据

当前仓库没有历史业务表，因此本次是全新初始化，不涉及旧表迁移。

`0003` 到 `0055` 均为兼容增量：

- 新表使用 `CREATE TABLE IF NOT EXISTS`。
- 新字段使用 `ADD COLUMN IF NOT EXISTS`。
- 新约束先 `DROP CONSTRAINT IF EXISTS` 再创建，便于重复执行。
- 旧 `pipeline_run` 记录的新增字段允许 NULL 或有默认值。
- `0005` 新增的 JSONB 字段默认 `{}`，`repair_status` 默认 `none`，不影响旧 run 查询。
- `pipeline_repair_queue` 只追加新表，不改写历史业务数据。
- `0006` 新增索引使用 `CREATE INDEX IF NOT EXISTS`，矩阵导出审计表只追加元数据，不影响行情表读写。
- `0007` 新表只追加多源融合、REST 鉴权和请求审计元数据，不改变现有行情/PIT 主键。
- `0008` 新表只追加 SLA、告警和看板快照，不改写 pipeline、质量检查或 API 审计明细。
- `0009` 新表只追加 vendor 接入、错误归因、benchmark 和评分记录，不改写既有 source/fusion 明细。
- `0010` 对 `sla_policy` 只追加 nullable provider 阈值字段，新增字段映射、分片压测和上线决策表，不改写 Eta 压测历史。
- `0011` 对 `api_token` 和 `api_request_audit` 只追加 nullable 租户/项目/主体字段，新增通知、权限、用量和调度表，不影响未配置租户的旧 token。
- `0012` 只追加 worker 运行记录表，不改写 Iota/Kappa 运营数据，worker 失败不会影响 API 查询主链路。
- `0013` 只追加 scheduler 配置、锁、心跳和 tick 观测表，并通过 `ON CONFLICT DO NOTHING` 初始化默认调度，不覆盖运维后续改动。
- `0014` 只追加部署发布和健康巡检元数据，不改变 API、worker、scheduler 的业务执行路径；健康检查失败只写状态，不回滚业务数据。
- `0015` 只追加产品、价格、订阅和预算治理元数据；预算 hard limit 只对已绑定租户/项目/主体的 token 生效，未配置预算的旧 token 保持兼容。
- `0016` 只追加账单、账单明细和账单事件；账单生成读取 Xi 订阅和 Iota 用量，重复生成保持同账期账单幂等，不改写已支付或作废账单的业务含义。
- `0017` 只追加供应商 readiness 复核结论和窗口明细，读取 Theta benchmark suite，不改写原始压测和供应商评分事实。
- `0018` 只追加收入对账、账单重算差异、AR aging 和客户健康快照；Rho 重算不覆盖 Omicron 原始账单，只保存差异和经营分析结论。
- `0019` 只追加运行日志、指标快照、运行日报和容量告警；Sigma 告警同步写入既有 `alert_event`，只扩展枚举，不改变旧告警状态语义。
- `0020` 只追加真实回款、发票匹配、ledger 和汇率事实；Tau 自动匹配只更新对应发票/付款状态和幂等分录，不改写 Omicron 原始开票口径或 Rho 对账历史。
- `0021` 只追加 Phi 策略元数据、信号、决策和升级事件；策略引擎读取既有质量、供应商、运行、商业和回款事实，不改写源事实表。
- `0022` 只追加 Chi 权限决策审计、项目治理快照和治理动作；ACL 层修正为 principal > project > tenant 严格匹配，不改变旧 token 表结构或数据 API 入参。
- `0023` 只追加 Psi 自动化 run/action 审计；dry-run 默认不改写源事实，execute 模式仅对低风险跟进动作做幂等状态推进，高风险动作需要审批。
- `0024` 只追加 Omega 审批、执行器、执行尝试和回滚控制元数据；默认 executor 为 noop，真实 webhook/script 需显式配置并通过审批护栏。
- `0025` 只追加 Alpha-2 白名单、secret 引用和沙箱 executor 元数据；secret 表只保存引用和元信息，不保存密钥明文。
- `0026` 只追加 Beta-2 外部通道、dispatch 审计和恢复 runbook；重复触发通过 suppressed dispatch 记录，不重复调用外部系统。
- `0027` 只追加 Gamma-2 通道 profile、validation 和 secret rotation 审计；默认写入本地 dry-run provider profile，不启用真实外部 endpoint。
- `0028` 只追加 Delta-2 企业微信 live receipt 审计和 env-var endpoint 引用；真实 webhook URL 不落库，未显式 `--allow-external` 不发送企业微信消息。
- `0029` 只追加 Epsilon-3 真实供应商 live gate 审计；真实 vendor token 只从 `QDATA_VENDOR_TOKEN` 读取，不落库，未显式 `--allow-live` 不调用外部供应商。
- `0030` 只追加 Zeta-3 供应商 onboarding run/result 审计；默认只编排 preflight/canary/gate 证据，真实供应商请求仍必须显式 `--allow-live --run-benchmarks`。
- `0031` 只追加 Eta-3 供应商 live closure run/probe 审计；默认不写 profile、不调用外部供应商，真实 endpoint 探针必须显式 `--allow-live` 且 endpoint probes 未被 `--no-endpoint-probes` 关闭，可加 `--run-endpoint-probes` 表明真实探针意图。
- `0032` 只追加 Theta-3 供应商 live pilot run/result 审计；默认复用 Eta-3 blocked closure 作为准入证据，不调用外部供应商，真实 pilot 必须显式 `--allow-live --require-live` 并满足合同、授权、限频、schema 和 onboarding 条件。
- `0033` 只追加 Iota-3 免费源联盟 run/result 审计和 `source_system` 候选源登记；默认只跑本地 `csv/csv_mirror` fixture，不调用外部免费源，真实免费源试运行必须显式 `--allow-external`，且免费源默认只能作为 research/backup 证据，不能替代商业授权主源。
- `0034` 只追加 Kappa-5 免费源可靠性快照；从 Iota-3 fabric result 生成 source+dataset score、连续失败、授权状态、商业清晰度和恢复动作，不改写 fabric、行情、供应商、账单、权限或生产事实。
- `0035` 只追加 Lambda-5 免费源恢复 run/action 审计，并扩展 worker task 枚举和通用告警枚举；恢复动作只编排重试、告警和人工复核，不改写 Kappa-5 snapshot、fabric、行情、供应商、账单、权限或生产事实。
- `0036` 只追加 Mu-5 免费源恢复 execution 审计，并扩展恢复 action 状态和 worker task 枚举；执行器只回写恢复 action 状态、审批/回执证据和 canary 结论，不改写 Kappa-5 snapshot、Iota-3/Iota-5 fabric 原始结论、行情、供应商、账单、权限或生产事实。
- `0037` 只追加 Nu-5 免费源恢复健康快照，并扩展 worker task 枚举；健康检查只读取 Mu-5 execution/action、Omega approval、worker schedule/run 证据，输出 SLA、backlog、失败率、调度陈旧度和 runbook 建议，不改写恢复动作、审批、行情、供应商、账单、权限或生产事实。
- `0038` 只追加 Xi-5 免费源准入档案和准入快照，并扩展 worker task 枚举；准入复核只读取 source profile、Kappa-5 reliability 和 Iota-3/Iota-5 证据，输出授权、转授权、合同、配额、可靠性和准入角色，不改写行情、供应商、账单、权限或生产事实。
- `0039` 只追加 Omicron-5 真实主供应商合同档案、dataset entitlement 和采购 readiness 快照，并扩展 worker task 枚举；采购复核只读取合同、授权、供应商 profile、Pi/Epsilon-3/Zeta-3/Eta-3/Theta-3 证据，输出主源候选、备源、校验源或阻断结论，不改写行情、免费源、账单、权限或生产事实。
- `0040` 只追加 Pi-5 授权主供应商 promotion run/result 审计，并扩展 worker task 枚举；promotion 默认 review-only，只读取 Omicron-5、Pi、Theta-3 和 `source_priority` 证据，只有显式启用 apply 且所有 dataset 通过时才幂等更新 `source_priority`。
- `0041` 只追加 Rho-5 主源切换后 monitor run/result 审计，并扩展 worker task 枚举；monitor 默认 review-only，只读取 Pi-5 promotion 和当前 `source_priority` 证据，只有显式启用 rollback apply 且 dataset 触发 rollback guardrail 时才幂等回滚 `source_priority`。
- `0042` 只追加 Sigma-5 主供应商稳定性 snapshot/result 审计，并扩展 worker task 枚举；稳定性监控默认只读，输出 SLA、容量、成本、调度滞后和 post-promotion 风险，不修改 `source_priority`、合同、授权或 promotion 状态。
- `0043` 只追加 Tau-5 主供应商成本优化 snapshot、route weight plan 和 budget stress 审计，并扩展 worker task 枚举；成本优化默认只读，只输出 primary/backup/free 权重建议、预算和 quota 风险，不修改 `source_priority`、合同、授权或实际路由。
- `0044` 只追加 Upsilon-5 路由权重执行 run/dataset/stage 审计和 `source_route_weight_policy` 控制面表，并扩展 worker task 枚举；执行器默认 `review_only` 且人工审批 pending，不改写 `source_priority`，只有显式 `execution_mode=apply` 且审批通过后才写入独立 policy 表，支持灰度放量和回滚记录。
- `0045` 只追加 Phi-5 route policy runtime 决策审计和 provider source seed；运行时读取 `source_route_weight_policy`，按 deterministic bucket 选择源并记录 fallback，不改写 `source_priority`、policy 或供应商合同。
- `0046` 只追加 Chi-5 route feedback 健康快照、source+dataset 熔断器和恢复探测审计，并扩展 worker task 枚举；反馈监控读取 `source_route_decision_audit`，自动跳过 open circuit 源，但不修改 `source_priority`、合同、授权或 route policy。
- `0047` 只追加 Psi-5 route incident action 审计，并扩展 automation source_type 与 worker task 枚举；自动化读取 Chi-5 open/recovered/failed/degraded 信号生成审批/通知/监控动作，不改写 `source_priority`、合同、授权或 route policy。
- `0048` 只追加 Omega-5 route incident control 审计，并扩展 worker task 枚举；控制闭环读取 Psi-5 incident action，串联 Omega approval、Delta-2 企业微信回执、dispatch 审计、execution attempt 和 rollback plan，不改写 `source_priority`、合同、授权或 route policy，真实企业微信外发必须显式允许。
- `0049` 只追加 Alpha-6 route incident control health 快照和 15m schedule，并扩展 worker task 枚举；健康层只读取 Omega-5 控制、审批、回执、执行和调度证据，不发起真实外部动作，不直接审批、执行或回滚业务动作。
- `0050` 只追加 Beta-6 route incident operation batch/item 和 30m schedule，并扩展 worker task 枚举；默认 `approval_decision=hold`、`apply_decisions=false`，只写操作队列、通知降噪和压测证据，只有显式启用 apply 时才通过 Omega approval 控制面批量 approve/reject。
- `0051` 只追加 Gamma-6 approval command/item/signature 三张审计表；POST 审批必须走 admin token、幂等键和 quorum 判断，quorum 满足后仍通过 Omega approval 控制面改写审批状态，不直接改 source route policy，不默认外发企业微信。
- `0052` 只追加 Delta-6 approval role/policy/callback/escalation 四张治理表和 15m schedule；企业微信回调必须先通过 HMAC 签名、nonce 防重放、RBAC、职责分离和策略 quorum 检查，治理通过后才调用 Gamma-6/Omega 控制面，密钥只来自环境变量，不落库。
- `0053` 只追加 Epsilon-6 approval lock/state/audit/SLA/recovery 五张韧性表和 15m schedule；企业微信回调在 Delta-6 前先进入 advisory lock、状态机守卫和不可变审计哈希链，SLA 自动处置只生成 planned action 和恢复演练证据，不产生真实外部副作用，不绕过 Delta-6/Gamma-6/Omega 审批控制面。
- `0054` 只追加 Zeta-6 release preflight、secret rotation evidence、concurrency test、audit export 四张发布/审计表和 30m schedule；企业微信回调支持 current/next 双密钥验签选择，但只记录 secret label 和摘要证据，不保存密钥原文。
- `0055` 只追加 Eta-6 真实供应商生产主源闭环 run、dataset check、decision 三张审计表和 30m schedule；闭环读取 Omicron-5 到 Upsilon-5 的合同、pilot、promotion、稳定性、成本和路由证据，只保存 token digest/脱敏配置，不保存 `QDATA_VENDOR_TOKEN` 原文，不直接改写 source priority 或 route policy。

后续如果已有客户数据，需要遵守：

- 不直接修改业务主键语义。
- 不删除已发布字段。
- 新字段优先允许 NULL 或提供默认值。
- 枚举新增保持旧客户端兼容。
- PIT 表新增版本时只追加，不覆盖历史版本。

## 5. 回滚策略

初始化阶段可通过 `db/rollback.sql` 删除所有新建对象。

限制：

- 回滚会删除 `qmeta`、`qpit`、`qts` 下所有对象。
- 若环境中已有同名 schema/database，执行前必须人工确认。
- 生产环境不应直接执行全量 drop，应改用备份恢复或版本化下线。

## 6. 灰度建议

MVP 阶段建议先用独立库实例验证：

- PostgreSQL：开发库 -> 测试库 -> 试点客户库。
- ClickHouse：单节点开发实例 -> 测试集群 -> 试点集群。

每次迁移后检查：

- 表是否全部创建成功。
- 主键、索引、约束是否生效。
- ClickHouse 分区和排序键是否符合查询模式。
- SDK mock 查询和真实连接查询的字段名是否一致。

## 7. 待补初始化数据

本地 smoke 已包含：

- 3 只 A 股证券。
- 2 个交易日。
- 日线、分钟线和复权因子。
- PIT 财务报表和财务指标。
- 沪深 300、中证 1000 样例成分。
- 申万一级行业样例。
- 2 个日频因子。
- 数据质量样例。

后续生产初始化应补充：

- 首批数据源。
- 数据集目录。
- 常用交易所枚举。
- 核心指数定义。
- 申万/中信行业体系定义。
- 基础因子定义。
