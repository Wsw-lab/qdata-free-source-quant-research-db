# 量化数据底座 API 契约

## 1. 文档目标

本文定义 A 股量化数据底座 MVP 的 REST API 和 Python SDK 契约，包括接口清单、鉴权、请求参数、响应结构、错误码、分页、兼容性和联调注意事项。

API 的核心目标是服务量化研究、因子计算、回测和后续实盘数据链路。

## 2. 设计原则

### 2.1 时点语义明确

凡是可能引发未来函数的数据，接口必须显式支持查询模式：

- `latest`：当前最新版本。
- `asof`：历史时点可见版本。
- `vintage`：指定数据版本。

### 2.2 批量查询优先

量化场景下，接口优先支持：

- 多证券。
- 多日期。
- 多字段。
- 多因子。
- 股票池和指数成分批量查询。

### 2.3 返回结构稳定

响应统一包含：

- `request_id`
- `status`
- `data`
- `meta`
- `errors`

新增字段必须兼容，删除或改名必须经过版本周期。

## 3. 基础约定

### 3.1 Base URL

```text
https://api.example.com/v1
```

私有化部署时由客户环境配置。

### 3.2 鉴权

所有接口使用 Bearer Token。

```http
Authorization: Bearer <token>
```

### 3.3 内容类型

```http
Content-Type: application/json
Accept: application/json
```

### 3.4 时间格式

- 日期：`YYYY-MM-DD`
- 时间戳：ISO 8601，例如 `2026-07-23T15:00:00+08:00`
- 默认时区：`Asia/Shanghai`

仅接收日期的 PIT selector 将该日期解释为 `Asia/Shanghai` 自然日，并以“次日
00:00（上海时区）”作为排他 knowledge cutoff；它不依赖 PostgreSQL session
timezone。需要盘中边界的接口必须传入带时区的 `asof_time`，不能用无时区时间戳。

### 3.5 证券代码格式

外部接口使用标准代码：

```text
600519.SH
000001.SZ
920001.BJ
```

服务内部使用 `security_id`，响应可同时返回 `security_id` 和 `symbol`。

### 3.6 通用响应结构

```json
{
  "request_id": "req_202607230001",
  "status": "success",
  "data": {
    "columns": ["symbol", "trade_date", "close"],
    "rows": [
      ["600519.SH", "2026-07-23", 1688.12]
    ]
  },
  "meta": {
    "query_mode": "asof",
    "data_versions": ["daily_bar:202607230001"],
    "row_count": 1,
    "next_cursor": null
  },
  "errors": []
}
```

### 3.7 通用错误结构

```json
{
  "request_id": "req_202607230002",
  "status": "failed",
  "data": null,
  "meta": {},
  "errors": [
    {
      "code": "PARAM_001",
      "message": "start_date must be less than or equal to end_date",
      "field": "start_date",
      "detail": {}
    }
  ]
}
```

### 3.8 分页和大查询

MVP 同步接口默认限制：

- 最大证券数：5000。
- 最大日期跨度：10 年日频或 30 个交易日分钟级。
- 最大返回行数：100 万行。

超过限制时返回 `QUERY_001`，后续版本提供异步导出任务。

分页参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `limit` | integer | `100000` | 最大返回行数 |
| `cursor` | string | `null` | 下一页游标 |

## 4. 接口清单

### 4.1 Epsilon 当前已实现 REST 端点

本仓库当前服务由 `scripts/run_api_server.py` 启动，默认本地地址为 `http://127.0.0.1:18080`。受保护端点支持：

```http
Authorization: Bearer <token>
X-API-Token: <token>
```

| 接口 | Method | URL | 关键参数 | 返回格式 |
|---|---|---|---|---|
| 健康检查 | GET | `/health` | `format=json|csv|arrow` | JSON/CSV/Arrow |
| 获取行情 | GET | `/price` | `symbols,start_date,end_date,frequency,adjust,fields,format` | JSON/CSV/Arrow |
| 获取交易约束 | GET | `/constraints` | `symbols,start_date,end_date,fields,format` | JSON/CSV/Arrow |
| 获取可交易股票池 | GET | `/tradable-universe` | `symbols,universe,asof_date,min_list_days,format` | JSON/CSV/Arrow |
| 获取价格矩阵 | GET | `/matrix` | `symbols,start_date,end_date,field,format` | JSON/CSV/Arrow |

示例：

```bash
./scripts/run_api_server.py --backend sql --port 18080 --tokens devtoken

curl \
  -H "Authorization: Bearer devtoken" \
  "http://127.0.0.1:18080/price?symbols=600519.SH,000001.SZ&start_date=2024-01-02&end_date=2024-01-02"
```

JSON 返回沿用统一结构：`request_id`、`status`、`data`、`meta`、`errors`。CSV 返回只包含 `data` 行；Arrow 为可选依赖，需安装 `qdata[export]`。

### 4.2 Zeta 运维治理入口

Zeta 阶段当前以 CLI/SQL 报表形式提供运维治理能力，后续可映射为 `/ops/*` REST 端点。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 运维总看板 | `scripts/report_ops_dashboard.py` | 汇总 pipeline、质量、多源、API 和告警 |
| SLA 检查 | `scripts/check_sla_alerts.py` | 创建/读取 SLA policy，生成 `alert_event` |
| API 审计报表 | `scripts/report_api_audit.py` | 汇总请求量、失败率和慢接口 |

核心表：

- `qmeta.sla_policy`
- `qmeta.alert_event`
- `qmeta.ops_dashboard_snapshot`

### 4.3 Eta 供应商接入和评分入口

Eta 阶段当前以 CLI/SQL 形式提供供应商接入、benchmark 和评分能力，后续可映射为 `/vendors/*` REST 端点。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 注册供应商 profile | `scripts/register_vendor_profile.py` | 记录 provider、auth、endpoint、限频、授权和合同引用 |
| 供应商 benchmark | `scripts/benchmark_vendor_sources.py` | 主备源按日期窗口做字段级对账、延迟统计和质量评分 |
| 供应商评分榜 | `scripts/report_vendor_scores.py` | 按 dataset 输出最新供应商评分 |

核心表：

- `qmeta.vendor_integration_profile`
- `qmeta.provider_error_event`
- `qmeta.provider_benchmark_run`
- `qmeta.vendor_quality_score_daily`

示例：

```bash
./scripts/register_vendor_profile.py \
  --source-code vendor_http \
  --source-name "Commercial HTTP Vendor" \
  --provider-name vendor_http \
  --auth-mode bearer \
  --enabled-datasets daily_bar,adjustment_factor,limit_price_daily

./scripts/benchmark_vendor_sources.py \
  --primary-provider csv \
  --secondary-provider vendor_http \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ \
  --write-db
```

`vendor_http` HTTP 模式支持 Bearer/Header/Query/Basic auth；token 建议通过环境变量或密钥管理注入，不进入数据库明文字段。

### 4.4 Theta 供应商生产化入口

Theta 阶段当前以 CLI/SQL 形式提供真实供应商生产化、分片压测、Provider SLA 和上线决策能力，后续可映射为 `/vendors/*` REST 端点。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 字段映射注册 | `scripts/register_vendor_field_mapping.py` | 写入外部字段、内部字段、单位和转换规则 |
| Profile 状态切换 | `scripts/activate_vendor_profile.py` | testing/active/paused/retired 状态治理 |
| 全市场分片压测 | `scripts/benchmark_vendor_universe.py` | 支持 shard、max symbols、5/20/60 交易日窗口 |
| Provider SLA | `scripts/check_provider_sla_alerts.py` | 根据评分、冲突率、失败率、延迟和错误数写告警 |
| 上线决策报告 | `scripts/report_vendor_decisions.py` | 输出 primary/backup/research_only/reject 建议 |

核心表：

- `qmeta.vendor_field_mapping`
- `qmeta.provider_benchmark_suite_run`
- `qmeta.vendor_decision_report`
- `qmeta.sla_policy`
- `qmeta.alert_event`

生产环境变量：

```bash
QDATA_VENDOR_BASE_URL=https://vendor.example/api
QDATA_VENDOR_TOKEN=replace-with-secret
QDATA_VENDOR_AUTH_MODE=bearer
QDATA_VENDOR_RATE_LIMIT_PER_MIN=120
QDATA_VENDOR_RETRY_LIMIT=2
QDATA_VENDOR_TIMEOUT_SECONDS=30
QDATA_VENDOR_RESPONSE_ROWS_KEY=data
```

示例：

```bash
./scripts/register_vendor_field_mapping.py --source-code vendor_http --dataset-code daily_bar
./scripts/benchmark_vendor_universe.py \
  --primary-provider csv \
  --secondary-provider vendor_http \
  --start-date 2024-01-04 \
  --end-date 2024-01-04 \
  --symbols 600519.SH,000001.SZ \
  --shard-size 1 \
  --write-db
./scripts/report_vendor_decisions.py --dataset-code daily_bar --write-db
```

### 4.5 Iota 生产运营入口

Iota 阶段当前以 CLI/SQL 形式提供租户权限、通知投递、API 用量计量和供应商压测调度能力，后续可映射为 `/admin/*`、`/usage/*` 和 `/vendors/schedules/*` REST 端点。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 租户权限初始化 | `scripts/bootstrap_iota_security.py` | 创建 tenant/project/principal/token/dataset ACL |
| 告警通道注册 | `scripts/register_notification_channel.py` | 注册 stdout/webhook/email/feishu 通道 |
| 告警通知投递 | `scripts/send_alert_notifications.py` | 读取 open `alert_event` 并写入投递记录 |
| API 用量日报 | `scripts/report_api_usage.py` | 汇总 `api_request_audit` 到 `api_usage_daily` |
| 供应商压测调度 | `scripts/manage_vendor_benchmark_schedule.py` | 固化 suite 参数并可立即运行 |

核心表：

- `qmeta.tenant`
- `qmeta.project`
- `qmeta.principal`
- `qmeta.project_member`
- `qmeta.dataset_access_policy`
- `qmeta.api_usage_daily`
- `qmeta.notification_channel`
- `qmeta.alert_notification_delivery`
- `qmeta.vendor_benchmark_schedule`

数据库 token 绑定租户上下文后，当前 REST 服务会对 `/price`、`/matrix`、`/constraints` 和 `/tradable-universe` 做数据集级 ACL 校验；未绑定租户的环境变量 token 仍保持兼容。

### 4.6 Kappa 运营管理 API

Kappa 阶段新增只读管理 API。所有 Kappa 路径都要求 token 具备 `admin` scope；响应沿用统一结构，CSV/JSON 由 `format` 参数控制，`/admin/console` 固定返回 Upsilon HTML 运营台。

| 接口 | Method | URL | 参数 | 说明 |
|---|---|---|---|---|
| 运营概览 | GET | `/admin/overview` | `format=json|csv` | 活跃租户、项目、token、open alert、通知和 7 日用量 |
| 租户列表 | GET | `/admin/tenants` | `tenant_code,status,limit,offset` | 租户及项目/主体/token 数 |
| 项目列表 | GET | `/admin/projects` | `tenant_code,project_code,status,limit,offset` | 项目、成员数、token 数和 ACL 数 |
| 主体列表 | GET | `/admin/principals` | `tenant_code,principal_code,principal_type,status,limit,offset` | 用户/服务账号和关联项目/token 数 |
| Token 列表 | GET | `/admin/tokens` | `tenant_code,project_code,principal_code,is_active,limit,offset` | 只返回 token 后 8 位哈希，不返回明文或完整哈希 |
| 数据集权限 | GET | `/admin/dataset-access` | `dataset_code,tenant_code,project_code,principal_code,status,limit,offset` | 查看 dataset ACL、字段白名单/黑名单 |
| 权限决策审计 | GET | `/admin/access-decisions` | `tenant_code,project_code,principal_code,token_name,dataset_code,api_name,decision,effective_scope,start_date,end_date,limit,offset` | 查看 Chi allow/deny、命中层级和拒绝原因 |
| 项目治理快照 | GET | `/admin/project-governance` | `snapshot_code,tenant_code,project_code,status,recommended_action,as_of_date,limit,offset` | 查看 Chi 项目级权限、用量、预算、账单和风险评分 |
| 治理动作 | GET | `/admin/governance-actions` | `action_code,tenant_code,project_code,principal_code,token_name,dataset_code,action_type,severity,status,owner,start_date,end_date,limit,offset` | 查看 Chi review_budget/review_access_policy 等治理任务 |
| 自动化运行 | GET | `/admin/automation-runs` | `run_code,environment,trigger_mode,execution_mode,status,start_date,end_date,limit,offset` | 查看 Psi dry-run/execute 运行摘要 |
| 自动化动作 | GET | `/admin/automation-actions` | `run_code,action_code,source_type,source_code,action_type,safety_level,execution_mode,status,owner,tenant_code,project_code,principal_code,dataset_code,start_date,end_date,limit,offset` | 查看 Psi 动作、护栏、审批和执行结果 |
| 自动化审批 | GET | `/admin/automation-approvals` | `approval_code,action_code,run_code,status,action_type,requested_by,decided_by,tenant_code,project_code,start_date,end_date,limit,offset` | 查看 Omega 审批队列和审批结果 |
| 自动化执行器 | GET | `/admin/automation-executors` | `executor_code,executor_type,action_type,safety_level,status,limit,offset` | 查看 Omega/Alpha-2 noop/webhook/script executor registry |
| 自动化白名单 | GET | `/admin/automation-allowlists` | `allowlist_code,executor_type,status,limit,offset` | 查看 Alpha-2 webhook/script 目标白名单 |
| 自动化密钥引用 | GET | `/admin/automation-secrets` | `secret_ref,secret_scope,secret_kind,status,owner,limit,offset` | 查看 Alpha-2 secret ref 元数据，不返回密钥明文 |
| 自动化外部通道 | GET | `/admin/automation-channels` | `channel_code,channel_type,environment,status,owner,runbook_code,limit,offset` | 查看 Beta-2 通知/审批联调通道 |
| 自动化外部 dispatch | GET | `/admin/automation-dispatches` | `dispatch_code,action_code,run_code,channel_code,dispatch_type,trigger_mode,status,requested_by,recovered_by,start_date,end_date,limit,offset` | 查看 Beta-2 外部通知、重复抑制、失败和恢复记录 |
| 自动化恢复手册 | GET | `/admin/automation-runbooks` | `runbook_code,failure_class,severity,status,owner,limit,offset` | 查看 Beta-2 dead-letter 恢复 runbook |
| 自动化通道 profile | GET | `/admin/automation-channel-profiles` | `profile_code,channel_code,provider_code,environment,status,readiness_status,owner,secret_ref,next_secret_ref,limit,offset` | 查看 Gamma-2 多环境 provider profile 和 readiness |
| 自动化通道验证 | GET | `/admin/automation-channel-validations` | `validation_code,profile_code,channel_code,provider_code,environment,validation_type,status,requested_by,target_secret_ref,start_date,end_date,limit,offset` | 查看 Gamma-2 联调验证和候选 secret 验证证据 |
| 自动化密钥轮换 | GET | `/admin/automation-secret-rotations` | `rotation_code,environment,secret_ref,next_secret_ref,rotation_type,status,requested_by,approved_by,profile_code,validation_code,start_date,end_date,limit,offset` | 查看 Gamma-2 secret rotation、apply 和 rollback 记录 |
| 自动化 live 回执 | GET | `/admin/automation-live-receipts` | `receipt_code,validation_code,profile_code,channel_code,provider_code,environment,message_type,status,requested_by,endpoint_secret_ref,provider_errcode,start_date,end_date,limit,offset` | 查看 Delta-2 企业微信 live validation 回执 |
| 自动化尝试 | GET | `/admin/automation-attempts` | `attempt_code,action_code,run_code,executor_code,status,trigger_mode,action_type,tenant_code,project_code,start_date,end_date,limit,offset` | 查看 Omega 执行 attempt、重试和错误 |
| 自动化回滚 | GET | `/admin/automation-rollbacks` | `rollback_code,action_code,run_code,status,rollback_type,requested_by,executed_by,tenant_code,project_code,start_date,end_date,limit,offset` | 查看 Omega rollback plan/result |
| 通知投递 | GET | `/admin/notification-deliveries` | `channel_code,status,severity,limit,offset` | 查看 alert 通知投递、状态和重试次数 |
| 供应商调度 | GET | `/admin/vendor-schedules` | `schedule_code,dataset_code,status,cadence,limit,offset` | 查看 benchmark schedule 和最近 suite |
| 供应商 live gate | GET | `/admin/vendor-live-gates` | `gate_code,dataset_code,source_code,primary_source_code,status,run_mode,requested_by,trigger_mode,review_code,recommendation,recommended_role,start_date,end_date,limit,offset` | 查看 Epsilon-3 真实 vendor token 门禁、阻塞原因和 readiness 证据 |
| 供应商 onboarding run | GET | `/admin/vendor-onboarding-runs` | `run_code,onboarding_code,source_code,primary_source_code,status,preflight_status,canary_status,gate_status,recommendation,recommended_role,trigger_mode,requested_by,environment,dataset_code,start_date,end_date,limit,offset` | 查看 Zeta-3 真实供应商接入预检、金丝雀、gate 和推荐角色 |
| 供应商 onboarding result | GET | `/admin/vendor-onboarding-results` | `run_code,onboarding_code,gate_code,dataset_code,source_code,primary_source_code,status,preflight_status,canary_status,gate_status,recommendation,recommended_role,start_date,end_date,limit,offset` | 查看 Zeta-3 每个数据集的接入结果、阻塞原因和 gate 证据 |
| 供应商 live closure | GET | `/admin/vendor-live-closures` | `closure_code,run_code,source_code,primary_source_code,status,config_status,endpoint_status,onboarding_status,promotion_status,recommendation,recommended_role,dataset_code,start_date,end_date,limit,offset` | 查看 Eta-3 endpoint probe、onboarding、promotion 和接入闭环结论 |
| 供应商 live probe | GET | `/admin/vendor-live-probes` | `closure_code,run_code,probe_code,dataset_code,source_code,status,auth_status,schema_status,start_date,end_date,limit,offset` | 查看 Eta-3 每个数据集的 endpoint schema probe 和 missing_fields |
| 供应商 live pilot | GET | `/admin/vendor-live-pilots` | `pilot_code,run_code,closure_code,source_code,primary_source_code,status,closure_status,endpoint_status,onboarding_status,benchmark_status,signoff_status,recommendation,recommended_role,risk_level,pilot_scope,dataset_code,start_date,end_date,limit,offset` | 查看 Theta-3 真实供应商试运行批次、签核状态、风险和推荐角色 |
| 供应商 live pilot result | GET | `/admin/vendor-live-pilot-results` | `pilot_code,run_code,result_code,closure_code,probe_code,gate_code,dataset_code,source_code,status,closure_status,endpoint_status,schema_status,onboarding_status,gate_status,benchmark_status,recommendation,recommended_role,risk_level,start_date,end_date,limit,offset` | 查看 Theta-3 每个数据集的试运行结果、证据关联和阻塞原因 |
| 免费源联盟 run | GET | `/admin/free-source-fabric-runs` | `fabric_code,run_code,source_code,dataset_code,status,fabric_scope,recommendation,recommended_role,risk_level,baseline_source_code,start_date,end_date,limit,offset` | 查看 Iota-3 免费源联盟运行、覆盖率、冲突率、授权风险和推荐角色 |
| 免费源联盟 result | GET | `/admin/free-source-fabric-results` | `fabric_code,run_code,result_code,dataset_code,source_code,status,coverage_status,consistency_status,license_status,freshness_status,recommendation,recommended_role,risk_level,baseline_source_code,start_date,end_date,limit,offset` | 查看 Iota-3 每个数据集的免费源覆盖、一致性、授权状态和阻塞原因 |
| 免费源可靠性 | GET | `/admin/free-source-reliability` | `snapshot_code,source_code,dataset_code,status,recommended_role,commercial_clearance,license_status,as_of_date,start_date,end_date,limit,offset` | 查看 Kappa-5 免费源 source+dataset 可靠性评分、自动降级和恢复动作 |
| 免费源恢复 run | GET | `/admin/free-source-recovery-runs` | `recovery_code,requested_by,trigger_mode,environment,status,as_of_date,start_date,end_date,limit,offset` | 查看 Lambda-5 免费源恢复编排、动作计数、告警数和阻塞原因 |
| 免费源恢复 action | GET | `/admin/free-source-recovery-actions` | `action_code,recovery_code,source_code,dataset_code,action_type,status,severity,reason_code,recommended_role,start_date,end_date,limit,offset` | 查看 Lambda-5 每个 source+dataset 的 retry、alert、manual_review 或 observe 动作 |
| 免费源恢复 execution | GET | `/admin/free-source-recovery-executions` | `execution_code,action_code,recovery_code,source_code,dataset_code,execution_type,status,requested_by,trigger_mode,environment,fabric_code,approval_code,wecom_receipt_code,start_date,end_date,limit,offset` | 查看 Mu-5 每个恢复动作的 canary 执行、审批、企业微信回执和结果回写 |
| 免费源恢复 health | GET | `/admin/free-source-recovery-health` | `snapshot_code,status,requested_by,trigger_mode,environment,schedule_code,start_date,end_date,limit,offset` | 查看 Nu-5 恢复执行健康、审批 SLA、backlog、失败率、调度陈旧度和 runbook |
| 免费源准入 profile | GET | `/admin/free-source-admission-profiles` | `profile_code,source_code,license_type,license_status,commercial_clearance,redistribution_allowed,contract_status,terms_review_status,max_allowed_role,status,limit,offset` | 查看 Xi-5 免费源授权、合同、转授权、条款复核、限频和最大准入角色档案 |
| 免费源准入矩阵 | GET | `/admin/free-source-admission` | `snapshot_code,source_code,dataset_code,status,admission_role,license_type,license_status,commercial_clearance,redistribution_allowed,contract_status,terms_review_status,as_of_date,start_date,end_date,limit,offset` | 查看 Xi-5 source+dataset 准入结论、可靠性证据、阻断原因和下一步动作 |
| 主供应商合同 profile | GET | `/admin/vendor-contract-profiles` | `contract_code,source_code,provider_name,procurement_status,contract_status,commercial_clearance,redistribution_allowed,status,limit,offset` | 查看 Omicron-5 真实主供应商合同、采购、商用、再分发、SLA、配额和负责人元数据 |
| 主供应商 dataset 授权 | GET | `/admin/vendor-contract-entitlements` | `entitlement_code,contract_code,source_code,dataset_code,entitlement_status,allowed_role,schema_status,field_mapping_status,status,limit,offset` | 查看 Omicron-5 每个 dataset 的授权角色、商用/再分发/生产使用、schema、字段映射和限频 |
| 主供应商采购 readiness | GET | `/admin/vendor-procurement-readiness` | `snapshot_code,contract_code,entitlement_code,source_code,dataset_code,status,procurement_role,contract_status,commercial_clearance,redistribution_allowed,entitlement_status,environment,as_of_date,start_date,end_date,limit,offset` | 查看 Omicron-5 source+dataset 主供应商采购准入结论、阻断原因、required_actions 和 live 证据 |
| 主供应商切主 run | GET | `/admin/vendor-primary-promotions` | `promotion_code,source_code,primary_source_code,status,promotion_scope,apply_mode,requested_by,trigger_mode,environment,as_of_date,start_date,end_date,limit,offset` | 查看 Pi-5 授权主供应商生产切主闸门、dataset 计数、routing 允许/应用状态和阻断原因 |
| 主供应商切主 result | GET | `/admin/vendor-primary-promotion-results` | `promotion_code,result_code,source_code,primary_source_code,dataset_code,status,promotion_role,procurement_status,procurement_role,readiness_status,canary_status,full_market_status,promotion_scope,apply_mode,start_date,end_date,limit,offset` | 查看 Pi-5 每个 dataset 的 Omicron-5/Pi/Theta-3 证据、当前主源和切主结论 |
| 主源切换后 monitor | GET | `/admin/vendor-post-promotion-monitors` | `monitor_code,promotion_code,source_code,primary_source_code,status,monitor_scope,rollback_mode,requested_by,trigger_mode,environment,as_of_date,start_date,end_date,limit,offset` | 查看 Rho-5 切主后监控、影子对账、回滚建议、dataset 计数和阻断原因 |
| 主源切换后 result | GET | `/admin/vendor-post-promotion-results` | `monitor_code,result_code,promotion_code,source_code,primary_source_code,dataset_code,status,monitor_scope,rollback_mode,promotion_status,promotion_role,shadow_status,start_date,end_date,limit,offset` | 查看 Rho-5 每个 dataset 的当前主源、前一主源、影子指标、回滚允许/应用状态和 required_actions |
| 主供应商生产稳定性 | GET | `/admin/vendor-primary-stability` | `snapshot_code,source_code,primary_source_code,status,stability_role,monitor_scope,requested_by,trigger_mode,environment,as_of_date,start_date,end_date,limit,offset` | 查看 Sigma-5 主供应商 SLA、容量、成本、调度滞后、Rho-5 风险和整体稳定性评分 |
| 主供应商 dataset 稳定性 | GET | `/admin/vendor-primary-stability-datasets` | `snapshot_code,dataset_snapshot_code,source_code,primary_source_code,dataset_code,status,stability_role,monitor_scope,entitlement_status,allowed_role,current_primary_source_code,start_date,end_date,limit,offset` | 查看 Sigma-5 每个 dataset 的授权、当前主源、promotion、API SLA 和成本稳定性结论 |
| 主供应商成本优化 | GET | `/admin/vendor-cost-optimizations` | `optimization_code,source_code,primary_source_code,status,optimization_role,optimization_scope,requested_by,trigger_mode,environment,as_of_date,start_date,end_date,limit,offset` | 查看 Tau-5 主供应商成本优化、预算占用、quota 水位、推荐权重和 required_actions |
| 主供应商路由权重计划 | GET | `/admin/vendor-route-weight-plans` | `optimization_code,plan_code,source_code,primary_source_code,backup_source_code,dataset_code,status,plan_role,current_primary_source_code,start_date,end_date,limit,offset` | 查看 Tau-5 每个 dataset 的 primary/backup/free 权重建议、成本、quota、当前主源和阻断原因 |
| 主供应商预算压测 | GET | `/admin/vendor-budget-stress` | `optimization_code,plan_code,stress_code,source_code,dataset_code,status,recommended_action,stress_multiplier,start_date,end_date,limit,offset` | 查看 Tau-5 每个 dataset 在 1x/5x/10x 等压力倍数下的预算和 quota 风险 |
| 路由权重执行 run | GET | `/admin/vendor-route-executions` | `execution_code,optimization_code,source_code,primary_source_code,status,approval_status,execution_mode,execution_scope,rollout_policy,requested_by,trigger_mode,environment,as_of_date,start_date,end_date,limit,offset` | 查看 Upsilon-5 路由权重执行、人工审批、灰度阶段、目标/实际权重和阻断原因 |
| 路由权重执行 dataset | GET | `/admin/vendor-route-execution-datasets` | `execution_code,execution_dataset_code,optimization_code,plan_code,source_code,primary_source_code,dataset_code,status,approval_status,rollout_policy,current_primary_source_code,start_date,end_date,limit,offset` | 查看 Upsilon-5 每个 dataset 的 Tau-5 plan、当前主源、审批状态、target/applied 权重和 rollback 标记 |
| 路由灰度 stage | GET | `/admin/vendor-route-rollout-stages` | `execution_code,execution_dataset_code,stage_code,source_code,dataset_code,status,approval_status,gate_status,stage_sequence,start_date,end_date,limit,offset` | 查看 Upsilon-5 每个 dataset 的灰度阶段、gate 状态、目标权重和是否已应用 |
| 路由权重 policy | GET | `/admin/source-route-weight-policies` | `policy_code,execution_code,source_code,primary_source_code,backup_source_code,dataset_code,policy_status,execution_mode,created_by,start_date,end_date,limit,offset` | 查看 Upsilon-5 显式 apply 后写入的 active/superseded/rolled_back route weight policy |
| 路由决策审计 | GET | `/admin/source-route-decisions` | `decision_code,policy_code,dataset_code,requested_source_code,selected_source_code,final_source_code,decision_context,route_mode,decision_status,selected_role,start_date,end_date,limit,offset` | 查看 Phi-5 API/sync/worker/smoke 路由决策、fallback 和最终来源 |
| 路由健康快照 | GET | `/admin/source-route-health` | `snapshot_code,dataset_code,source_code,status,circuit_status,circuit_action,requested_by,trigger_mode,environment,start_date,end_date,limit,offset` | 查看 Chi-5 source+dataset 成功率、失败率、fallback、空响应、延迟和熔断动作 |
| 路由熔断器 | GET | `/admin/source-route-circuit-breakers` | `breaker_code,dataset_code,source_code,status,limit,offset` | 查看 Chi-5 当前 open/closed circuit、open_until、最近快照、最近恢复探测和打开原因 |
| 路由恢复探测 | GET | `/admin/source-route-recovery-probes` | `probe_code,breaker_code,snapshot_code,dataset_code,source_code,status,decision_summary,requested_by,trigger_mode,environment,start_date,end_date,limit,offset` | 查看 Chi-5 熔断恢复探测、观测成功率、要求成功率和 recovered/failed 结论 |
| 路由故障处置动作 | GET | `/admin/source-route-incident-actions` | `incident_action_code,run_code,action_code,source_signal_type,dataset_code,source_code,action_type,safety_level,execution_mode,status,owner,start_date,end_date,limit,offset` | 查看 Psi-5 从 Chi-5 route signal 生成的自动化处置动作、审批状态和恢复确认 |
| 路由故障控制闭环 | GET | `/admin/source-route-incident-controls` | `control_code,incident_action_code,run_code,action_code,source_signal_type,dataset_code,source_code,action_type,safety_level,control_stage,approval_status,dispatch_status,receipt_status,attempt_status,rollback_status,requested_by,start_date,end_date,limit,offset` | 查看 Omega-5 把 Psi-5 incident action 串到审批、企业微信回执、dispatch、执行 attempt 和 rollback plan 的控制状态 |
| 路由故障控制健康 | GET | `/admin/source-route-incident-control-health` | `snapshot_code,status,requested_by,trigger_mode,environment,schedule_code,start_date,end_date,limit,offset` | 查看 Alpha-6 对 Omega-5 控制闭环的审批 SLA、企业微信回执、执行失败率、回滚和调度陈旧度健康快照 |
| 路由故障操作批次 | GET | `/admin/source-route-incident-operation-batches` | `batch_code,status,requested_by,trigger_mode,environment,operation_mode,approval_decision,notification_policy,stress_scope,start_date,end_date,limit,offset` | 查看 Beta-6 批量审批、通知降噪和 route incident 压测批次 |
| 路由故障操作明细 | GET | `/admin/source-route-incident-operation-items` | `batch_code,control_code,approval_code,incident_action_code,dataset_code,source_code,source_signal_type,safety_level,operation_decision,operation_status,start_date,end_date,limit,offset` | 查看 Beta-6 每个 control 的审批前后状态、降噪分组和操作结果 |
| 路由故障审批命令 | POST | `/admin/source-route-incident-approval-commands` | JSON body: `decision,control_code|approval_code|batch_code,requested_by,principal_code,required_approvals,idempotency_key,notify_wecom` | Gamma-6 可写审批命令，支持 approve/reject/hold、多审批人 quorum 和幂等重放 |
| 路由故障审批命令查询 | GET | `/admin/source-route-incident-approval-commands` | `command_code,idempotency_key,status,decision,requested_by,principal_code,command_scope,quorum_status,batch_code,control_code,approval_code,start_date,end_date,limit,offset` | 查询 Gamma-6 command 状态、quorum、应用数、失败数和 evidence |
| 路由故障审批明细查询 | GET | `/admin/source-route-incident-approval-command-items` | `command_code,control_code,approval_code,incident_action_code,dataset_code,source_code,source_signal_type,safety_level,decision,item_status,signer_code,start_date,end_date,limit,offset` | 查询 Gamma-6 每个 control 的签批前后状态、quorum 和应用结果 |
| 路由故障审批签名查询 | GET | `/admin/source-route-incident-approval-signatures` | `signature_code,command_code,control_code,approval_code,decision,signer_code,idempotency_key,status,start_date,end_date,limit,offset` | 查询 Gamma-6 每个审批人的签名、幂等键和签批时间 |
| 路由故障企业微信审批回调 | POST | `/webhooks/wecom/source-route-incident-approval-callbacks` | HMAC headers + JSON body: `decision,control_code|approval_code|batch_code,signer_code,requested_by,required_approvals,idempotency_key` | Zeta-6 先尝试 current/next callback secret，再进入 Epsilon-6 包裹后的 Delta-6 签名治理；无 Bearer token，但必须通过 rotation、advisory lock、状态机、HMAC、nonce、RBAC、职责分离和 replay 检查 |
| 路由故障审批回调补录 | POST | `/admin/source-route-incident-approval-wecom-callbacks` | admin Bearer + 同一套 HMAC headers/body | Zeta-6/Epsilon-6 管理补录/联调用入口，仍复用生产密钥轮换、锁、状态守卫、验签和治理规则 |
| 路由故障审批角色查询 | GET | `/admin/source-route-incident-approval-role-bindings` | `binding_code,principal_code,role_code,dataset_code,source_code,safety_level,status,start_date,end_date,limit,offset` | 查询 Delta-6 审批人、风控管理员、请求人和审计查看角色绑定 |
| 路由故障审批策略查询 | GET | `/admin/source-route-incident-approval-policies` | `policy_code,dataset_code,source_code,safety_level,status,created_by,start_date,end_date,limit,offset` | 查询 Delta-6 quorum、职责分离、风控审批、签名、超时、replay 和升级策略 |
| 路由故障审批回调查询 | GET | `/admin/source-route-incident-approval-callbacks` | `callback_code,provider_code,nonce,signature_status,governance_status,decision,signer_code,control_code,approval_code,batch_code,start_date,end_date,limit,offset` | 查询 Delta-6 每次企业微信回调的验签、治理和 Gamma-6 command 结果 |
| 路由故障审批升级查询 | GET | `/admin/source-route-incident-approval-escalations` | `escalation_code,reason_code,status,owner_principal_code,control_code,approval_code,callback_code,start_date,end_date,limit,offset` | 查询 Delta-6 超时、quorum 卡住、策略拒绝、缺角色、无效签名、replay 和撤销升级 |
| 路由故障审批锁事件查询 | GET | `/admin/source-route-incident-approval-lock-events` | `lock_event_code,lock_scope,lock_status,provider_code,nonce,control_code,approval_code,batch_code,callback_code,command_code,start_date,end_date,limit,offset` | 查询 Epsilon-6 advisory lock acquired/busy/released、request hash、held_ms 和并发证据 |
| 路由故障审批状态转移查询 | GET | `/admin/source-route-incident-approval-state-transitions` | `transition_code,transition_status,reason_code,control_code,approval_code,batch_code,requested_decision,signer_code,callback_code,command_code,start_date,end_date,limit,offset` | 查询 Epsilon-6 回调前后 approval/control 状态、终态阻断和 Delta-6 结果 |
| 路由故障审批审计哈希链查询 | GET | `/admin/source-route-incident-approval-audit-chain` | `audit_hash_code,chain_scope,entity_type,entity_code,entry_hash,verification_status,start_date,end_date,limit,offset` | 查询 Epsilon-6 不可变审计链 sequence、previous_hash、payload_hash、entry_hash 和校验状态 |
| 路由故障审批 SLA 动作查询 | GET | `/admin/source-route-incident-approval-sla-actions` | `sla_action_code,escalation_code,command_code,control_code,approval_code,reason_code,action_type,action_status,severity,owner_principal_code,start_date,end_date,limit,offset` | 查询 Epsilon-6 从 Delta-6 open escalation 生成的 planned SLA action |
| 路由故障审批恢复演练查询 | GET | `/admin/source-route-incident-approval-recovery-drills` | `drill_code,drill_type,status,requested_by,trigger_mode,target_control_code,start_date,end_date,limit,offset` | 查询 Epsilon-6 DB reconnect、hash chain、lock contention 和状态机恢复演练证据 |
| 路由故障审批发布 preflight 查询 | GET | `/admin/source-route-incident-approval-release-preflights` | `preflight_code,environment,status,release_version,requested_by,trigger_mode,start_date,end_date,limit,offset` | 查询 Zeta-6 DB reconnect、audit chain、recovery drill、schedule 和 secret 配置发布检查 |
| 路由故障审批密钥轮换查询 | GET | `/admin/source-route-incident-approval-secret-rotations` | `rotation_code,environment,rotation_phase,status,active_secret_label,verified_secret_label,nonce,start_date,end_date,limit,offset` | 查询 Zeta-6 current/next callback secret label 命中、signature digest、nonce 和 request hash 证据；不暴露密钥原文 |
| 路由故障审批并发压测查询 | GET | `/admin/source-route-incident-approval-concurrency-tests` | `test_code,environment,status,target_scope,start_date,end_date,limit,offset` | 查询 Zeta-6 高并发/replay storm 压测摘要、成功/阻断/replay/失败计数 |
| 路由故障审批审计导出查询 | GET | `/admin/source-route-incident-approval-audit-exports` | `export_code,environment,status,export_format,chain_scope,control_code,approval_code,batch_code,package_hash,start_date,end_date,limit,offset` | 查询 Zeta-6 监管审计导出包、included entity count、broken hash count 和 package hash |
| 真实供应商生产主源闭环 run | GET | `/admin/vendor-production-source-runs` | `production_code,source_code,primary_source_code,status,production_role,environment,closure_scope,closure_mode,start_date,end_date,limit,offset` | 查询 Eta-6 授权主供应商从合同、live pilot、promotion、稳定性、成本到路由执行的生产闭环总判定；不暴露 vendor token |
| 真实供应商生产主源 dataset check | GET | `/admin/vendor-production-source-dataset-checks` | `production_code,dataset_check_code,source_code,dataset_code,status,production_role,route_policy_status,start_date,end_date,limit,offset` | 查询 Eta-6 每个 dataset 的合同授权、Theta-3/Pi-5/Sigma-5/Tau-5/Upsilon-5 证据、阻断原因和生产角色 |
| 真实供应商生产主源 decision | GET | `/admin/vendor-production-source-decisions` | `production_code,dataset_check_code,decision_code,source_code,dataset_code,decision_type,status,severity,start_date,end_date,limit,offset` | 查询 Eta-6 每个 gate 的 profile/env、contract、pilot、promotion、stability、cost、route、rollback 和最终决策审计 |
| Worker 运行 | GET | `/admin/worker-runs` | `status,trigger_mode,task_name,limit,offset` | 查看 Lambda worker 总运行和 task 汇总 |
| Worker 调度 | GET | `/admin/worker-schedules` | `schedule_code,task_name,status,limit,offset` | 查看 Mu schedule 配置、下次运行和最近状态 |
| Worker 锁 | GET | `/admin/worker-locks` | `lock_name,owner_id,limit,offset` | 查看 Mu scheduler 防重复锁和过期状态 |
| Scheduler 心跳 | GET | `/admin/worker-heartbeats` | `scheduler_id,status,limit,offset` | 查看 Mu scheduler 实例存活和最近心跳 |
| Scheduler Tick | GET | `/admin/worker-schedule-ticks` | `schedule_code,scheduler_id,task_name,status,limit,offset` | 查看每次调度扫描和触发的 worker_run |
| 部署 Release | GET | `/admin/deployment-releases` | `release_code,environment,status,limit,offset` | 查看 Nu release 状态和最近健康快照 |
| 部署健康快照 | GET | `/admin/deployment-health` | `snapshot_code,release_code,environment,status,limit,offset` | 查看 Nu 健康检查总状态 |
| 部署健康明细 | GET | `/admin/deployment-health-checks` | `snapshot_code,component,check_name,status,limit,offset` | 查看每个组件的健康检查明细 |
| 部署事件 | GET | `/admin/deployment-events` | `release_code,environment,event_type,status,limit,offset` | 查看部署、健康检查和回滚事件 |
| 数据产品 | GET | `/admin/data-products` | `product_code,product_type,status,limit,offset` | 查看 Xi 数据产品目录 |
| 价格计划 | GET | `/admin/pricing-plans` | `plan_code,billing_cycle,status,limit,offset` | 查看价格计划和规则数量 |
| 价格规则 | GET | `/admin/pricing-rules` | `plan_code,product_code,api_name,metric_name,status,limit,offset` | 查看 API/产品计价规则 |
| 产品订阅 | GET | `/admin/product-subscriptions` | `subscription_code,tenant_code,project_code,plan_code,product_code,status,limit,offset` | 查看项目订阅的产品和价格计划 |
| 预算策略 | GET | `/admin/budget-policies` | `budget_code,tenant_code,project_code,cost_center,plan_code,product_code,status,limit,offset` | 查看预算策略和最新用量状态 |
| 预算用量 | GET | `/admin/budget-usage` | `budget_code,tenant_code,project_code,cost_center,status,limit,offset` | 查看预算周期快照 |
| 预算告警 | GET | `/admin/budget-alerts` | `budget_code,tenant_code,project_code,cost_center,alert_type,severity,status,limit,offset` | 查看预算告警和升级/恢复状态 |
| 供应商上线复核 | GET | `/admin/vendor-readiness` | `review_code,dataset_code,source_code,primary_source_code,status,recommendation,recommended_role,limit,offset` | 查看 Pi 供应商 5/20/60 窗口上线复核结论 |
| 供应商复核窗口 | GET | `/admin/vendor-readiness-windows` | `review_code,dataset_code,source_code,primary_source_code,status,window_days,limit,offset` | 查看每个窗口对应 suite 和阈值判断 |
| 账单列表 | GET | `/admin/invoices` | `invoice_code,tenant_code,project_code,subscription_code,plan_code,product_code,status,start_date,end_date,limit,offset` | 查看 Omicron 账单和应收/实收状态 |
| 账单明细 | GET | `/admin/invoice-lines` | `invoice_code,tenant_code,project_code,product_code,api_name,metric_name,start_date,end_date,limit,offset` | 查看账单 API/指标级计费明细 |
| 账单事件 | GET | `/admin/invoice-events` | `invoice_code,tenant_code,project_code,event_type,status,limit,offset` | 查看账单生成、回款、逾期和作废事件 |
| 收入汇总 | GET | `/admin/revenue-summary` | `tenant_code,project_code,product_code,plan_code,subscription_code,status,start_date,end_date,limit,offset` | 查看客户/项目/产品维度应收、实收和未收 |
| 收入对账 | GET | `/admin/revenue-reconciliation` | `reconciliation_code,tenant_code,project_code,product_code,plan_code,subscription_code,invoice_code,status,start_date,end_date,limit,offset` | 查看 Rho 账单重算与已开票金额差异 |
| 收入对账明细 | GET | `/admin/revenue-reconciliation-lines` | `reconciliation_code,tenant_code,project_code,product_code,plan_code,subscription_code,invoice_code,api_name,metric_name,status,limit,offset` | 查看 API/指标级重算和开票差异 |
| 应收账龄 | GET | `/admin/ar-aging` | `aging_code,tenant_code,project_code,product_code,plan_code,status,as_of_date,limit,offset` | 查看 AR aging 当前、逾期和 30/60/90+ 分桶 |
| 客户健康 | GET | `/admin/customer-health` | `health_code,tenant_code,project_code,product_code,plan_code,subscription_code,status,as_of_date,limit,offset` | 查看客户活跃、留存信号和付款风险 |
| 回款批次 | GET | `/admin/payment-batches` | `batch_code,source_type,account_code,currency,status,start_date,end_date,limit,offset` | 查看 Tau 回款导入批次、总额、匹配和未匹配金额 |
| 付款流水 | GET | `/admin/payments` | `batch_code,transaction_code,invoice_code,tenant_code,project_code,status,currency,payment_channel,direction,start_date,end_date,limit,offset` | 查看真实回款流水、渠道、金额、发票和匹配状态 |
| 回款匹配 | GET | `/admin/payment-matches` | `batch_code,match_code,transaction_code,invoice_code,tenant_code,project_code,status,currency,start_date,end_date,limit,offset` | 查看付款和发票的自动/人工匹配结果 |
| 收入 Ledger | GET | `/admin/revenue-ledger` | `ledger_code,invoice_code,transaction_code,match_code,tenant_code,project_code,entry_type,currency,start_date,end_date,limit,offset` | 查看 payment_received/payment_matched 等收入分录 |
| 日汇率 | GET | `/admin/fx-rates` | `rate_code,from_currency,to_currency,provider,start_date,end_date,limit,offset` | 查看 Tau 多币种日汇率 |
| 运行日志 | GET | `/admin/runtime-logs` | `environment,component,service_name,severity,event_type,start_date,end_date,limit,offset` | 查看 Sigma 运行日志和关键事件 |
| 运行指标 | GET | `/admin/runtime-metrics` | `environment,component,service_name,metric_name,status,start_date,end_date,limit,offset` | 查看 Sigma 指标快照、阈值和状态 |
| 运行日报 | GET | `/admin/runtime-daily-reports` | `environment,report_code,report_date,status,start_date,end_date,limit,offset` | 查看每日运行健康和容量汇总 |
| 容量告警 | GET | `/admin/capacity-alerts` | `environment,component,metric_name,severity,status,start_date,end_date,limit,offset` | 查看容量预警、阈值、开放/恢复状态 |
| 策略运行 | GET | `/admin/strategy-runs` | `run_code,environment,status,severity,trigger_mode,limit,offset` | 查看 Phi 策略运行摘要 |
| 策略信号 | GET | `/admin/strategy-signals` | `run_code,policy_code,domain,status,severity,subject_code,signal_type,metric_name,limit,offset` | 查看 Phi 策略信号和来源事实 |
| 策略决策 | GET | `/admin/strategy-decisions` | `run_code,policy_code,domain,status,severity,subject_code,decision_type,action,limit,offset` | 查看 Phi 策略 action/status/reason |
| 策略升级 | GET | `/admin/strategy-escalations` | `run_code,status,severity,escalation_type,owner,limit,offset` | 查看 Phi 高优先级升级事件 |
| 用量日报 | GET | `/usage/daily` | `trade_date,start_date,end_date,tenant_code,project_code,principal_code,api_name,limit,offset` | 查看 API 用量、失败数、行数和成本单位 |
| Upsilon 运营台 | GET | `/admin/console` | 无 | 返回带搜索、状态筛选和分组切换的只读 HTML 运营台 |

示例：

```bash
./scripts/run_api_server.py --backend sql --port 18084

curl \
  -H "Authorization: Bearer iotatoken" \
  "http://127.0.0.1:18084/admin/overview"

curl \
  -H "Authorization: Bearer iotatoken" \
  "http://127.0.0.1:18084/usage/daily?trade_date=2026-07-24&project_code=quant-research"
```

分页规则：

- `limit` 默认 100，最大 500。
- `offset` 默认 0。
- 超出范围返回 400。

### 4.7 Lambda 后台自动化 Worker

Lambda 阶段以 CLI/SQL 形式提供后台自动化执行能力，结果通过 Kappa `/admin/worker-runs` 查询。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| Worker 执行 | `scripts/run_lambda_worker.py` | 支持 `--once`、`--task`、`--dry-run` |
| 用量 rollup | `usage_rollup` task | 聚合 API 审计到 `api_usage_daily` |
| 告警投递 | `alert_dispatch` task | 投递 open alert 到通知通道 |
| 供应商调度 | `vendor_benchmark_schedule` task | 扫描到期或指定 schedule 并运行 benchmark suite |
| 运行观测 | `/admin/worker-runs` | 查看 run/task 状态、处理数、warning 和错误 |

示例：

```bash
./scripts/run_lambda_worker.py \
  --once \
  --trade-date 2026-07-24 \
  --channel-code stdout-high \
  --schedule-code daily_bar_vendor_fixture_schedule
```

### 4.8 Mu 后台调度器

Mu 阶段以 CLI/Docker service 形式提供长期调度能力，调度状态通过 Kappa 只读端点查询。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 调度器执行 | `scripts/run_mu_scheduler.py` | 支持 `--once`、`--schedule-code`、`--task`、`--force-due`、`--dry-run` |
| 调度器 smoke | `scripts/smoke_mu_scheduler.py` | 强制指定 schedule 到期、跑一次 scheduler，并查询 Kappa 状态 |
| Docker profile | `docker compose --profile scheduler run --rm mu-scheduler ...` | 使用容器内 Python 连接 Compose Postgres 执行调度 |
| 防重复锁 | `worker_lock` | 同一 `schedule_code` 同时只允许一个 scheduler 持锁执行 |
| 心跳观测 | `/admin/worker-heartbeats` | 查看 scheduler 实例、last_seen_at 和 stale 状态 |
| Tick 观测 | `/admin/worker-schedule-ticks` | 查看每次调度尝试、锁状态、worker_run_id 和错误摘要 |

示例：

```bash
./scripts/run_mu_scheduler.py \
  --schedule-code mu_usage_rollup_5m \
  --once \
  --force-due \
  --trade-date 2026-07-24

./scripts/report_kappa_admin.py --resource worker-schedule-ticks --limit 5
```

### 4.9 Nu 标准部署和健康巡检

Nu 阶段以脚本、Docker profile 和 Kappa 只读 API 形式提供本地标准部署、健康检查和非破坏性回滚入口。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 本地部署 | `scripts/deploy_nu_local.sh` | 启动 Postgres/ClickHouse，可选启动 API 和 scheduler，应用迁移并写健康快照 |
| 健康巡检 | `scripts/check_nu_health.py` | 检查 Postgres、migration、ClickHouse、API、scheduler、Kappa，可写入 `deployment_health_snapshot` |
| 本地回滚 | `scripts/rollback_nu_local.sh` | 默认停止 API/scheduler；显式 `--drop-nu-metadata` 才删除 0014 元数据表 |
| Docker API | `docker compose --profile app up -d qdata-api` | 用容器运行 REST API |
| Docker Scheduler | `docker compose --profile scheduler up -d mu-scheduler` | 用容器运行 Mu scheduler |
| 部署观测 | `/admin/deployment-health` | 查看最近健康快照和成功/失败计数 |

示例：

```bash
./scripts/check_nu_health.py \
  --environment local \
  --release-code nu-local-smoke-20260726 \
  --api-base-url http://127.0.0.1:18085 \
  --api-token iotatoken \
  --write-db

./scripts/report_kappa_admin.py --resource deployment-health --limit 5
./scripts/report_kappa_admin.py --resource deployment-health-checks --limit 10
```

### 4.10 Xi 数据产品、计费和预算治理

Xi 阶段以 PostgreSQL 元数据、CLI 和 Kappa 只读 API 形式提供数据产品目录、价格计划、项目订阅、预算快照和预算告警能力。预算 hard limit 在 DB token 带 tenant/project/principal 上下文时生效，未配置预算或使用兼容 env token 时不拦截查询。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 商业目录初始化 | `scripts/bootstrap_xi_commercial.py` | 创建默认产品、价格计划、订阅和预算，可立即评估预算 |
| 预算评估 | `scripts/report_xi_billing.py --resource evaluate-budgets` | 从 `api_usage_daily` 计算产品预算用量，可写入 snapshot 和 alert |
| 预算 hard limit | REST API 鉴权后置检查 | hard limit 打开且预计下一次请求越线时返回 402 |
| 产品观测 | `/admin/data-products` | 查看产品、数据集数和 API 数 |
| 价格观测 | `/admin/pricing-plans`、`/admin/pricing-rules` | 查看 plan/rule 和计价单位 |
| 订阅观测 | `/admin/product-subscriptions` | 查看租户/项目订阅 |
| 预算观测 | `/admin/budget-policies`、`/admin/budget-usage`、`/admin/budget-alerts` | 查看预算策略、周期快照和告警 |

示例：

```bash
./scripts/bootstrap_xi_commercial.py --evaluate --write-alerts --as-of-date 2026-07-26
./scripts/report_xi_billing.py --resource budget-usage
./scripts/report_kappa_admin.py --resource budget-alerts --limit 10
```

当前本地验收样例：

```json
{
  "product_code": "a_share_daily_core",
  "plan_code": "quant_starter_monthly",
  "budget_code": "demo_quant-research_monthly_budget",
  "usage_amount": "0.16002800",
  "budget_amount": "0.15000000",
  "usage_pct": "1.06685333",
  "status": "exceeded",
  "open_alert": "budget_exceeded"
}
```

### 4.11 Omicron 月度账单和收入回款

Omicron 阶段以 PostgreSQL 元数据、CLI 和 Kappa 只读 API 形式提供月度账单、账单明细、账单事件和收入汇总能力。账单生成从 Xi 订阅和 Iota 用量日报读取事实，重复生成同账期账单保持幂等。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 账单生成 | `scripts/generate_omicron_invoices.py` | 按 period、tenant/project/subscription 从用量和价格规则生成账单 |
| 账单回款更新 | `scripts/update_omicron_invoice_status.py` | 更新 paid/overdue/void 等状态并写入账单事件 |
| 账单和收入报表 | `scripts/report_omicron_revenue.py` | 查询 invoices、invoice-lines、invoice-events、revenue-summary |
| Kappa 观测 | `/admin/invoices`、`/admin/invoice-lines`、`/admin/invoice-events`、`/admin/revenue-summary` | 查看应收、实收、未收和逾期状态 |

示例：

```bash
./scripts/generate_omicron_invoices.py --period-start 2026-07-01 --period-end 2026-07-31 --tenant-code demo --project-code quant-research
./scripts/report_omicron_revenue.py --resource revenue-summary
./scripts/update_omicron_invoice_status.py --invoice-code inv-demo-quant-research-a_share_daily_core-20260701-20260731 --status paid
```

### 4.12 Pi 供应商上线复核

Pi 阶段以 PostgreSQL 元数据、CLI 和 Kappa 只读 API 形式提供供应商 5/20/60 交易日窗口上线复核。Kappa 只读端点只查询结论，不触发实际 benchmark；实际压测由 Theta CLI 或 Iota/Mu schedule 执行。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 分片窗口压测 | `scripts/benchmark_vendor_universe.py --target-trade-days 5/20/60` | 生成 `provider_benchmark_suite_run` |
| 上线复核 | `scripts/report_pi_vendor_readiness.py` | 汇总最新 5/20/60 suite，输出 recommendation 和 role |
| Kappa 复核观测 | `/admin/vendor-readiness` | 查看 ready/watch/rejected/incomplete 总结 |
| Kappa 窗口观测 | `/admin/vendor-readiness-windows` | 查看每个窗口的 coverage/conflict/failure/latency/throughput |

示例：

```bash
./scripts/report_pi_vendor_readiness.py --dataset-code daily_bar --source-code vendor_http --primary-source-code csv --windows 5,20,60
./scripts/report_kappa_admin.py --resource vendor-readiness --source-code vendor_http
./scripts/report_kappa_admin.py --resource vendor-readiness-windows --source-code vendor_http
```

### 4.13 Rho 收入对账和客户健康

Rho 阶段以 PostgreSQL 快照、CLI 和 Kappa 只读 API 形式提供账单重算差异、AR aging 和客户健康。Rho 只追加复核结果，不覆盖 Omicron 原始账单。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 账单重算 | `scripts/report_rho_revenue.py --resource generate-reconciliation` | 复用 Omicron 计费行生成口径，对比已开票金额 |
| AR aging | `scripts/report_rho_revenue.py --resource generate-ar-aging` | 按 as_of_date 输出 current、1-30、31-60、61-90、90+ 分桶 |
| 客户健康 | `scripts/report_rho_revenue.py --resource generate-customer-health` | 按订阅输出 usage recency、付款风险、留存信号和 health_score |
| Kappa 观测 | `/admin/revenue-reconciliation`、`/admin/revenue-reconciliation-lines`、`/admin/ar-aging`、`/admin/customer-health` | 查看对账、应收账龄和客户健康 |

示例：

```bash
./scripts/report_rho_revenue.py --resource generate-all --period-start 2026-07-01 --period-end 2026-07-31 --as-of-date 2026-07-26 --tenant-code demo --project-code quant-research
./scripts/report_kappa_admin.py --resource revenue-reconciliation --tenant-code demo
./scripts/report_kappa_admin.py --resource ar-aging --as-of-date 2026-07-26
./scripts/report_kappa_admin.py --resource customer-health --as-of-date 2026-07-26
```

### 4.14 Sigma 运行可观测和容量预警

Sigma 阶段以 PostgreSQL 事实表、CLI 和 Kappa 只读 API 形式提供长期运行观测能力。采集任务只追加日志、指标、日报和告警，不改变业务查询链路。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 运行观测采集 | `scripts/report_sigma_runtime.py --resource collect` | 汇总 API 审计、worker、Nu 健康、Pi readiness、Rho 客户健康和商业应收指标 |
| 运行日志 | `scripts/report_sigma_runtime.py --resource log` | 记录组件事件、严重级别、trace/request 信息 |
| 运行指标 | `scripts/report_sigma_runtime.py --resource metric` | 写入单项指标、单位、warning/critical 阈值和状态 |
| 运行日报 | `scripts/report_sigma_runtime.py --resource daily-report` | 生成每日运行健康状态和容量告警汇总 |
| 容量告警 | `capacity_alert` + `alert_event` | 超阈值指标形成容量告警，并同步进入通用告警中心 |
| Kappa 观测 | `/admin/runtime-logs`、`/admin/runtime-metrics`、`/admin/runtime-daily-reports`、`/admin/capacity-alerts` | 查看运行日志、指标、日报和容量告警 |

示例：

```bash
./scripts/report_sigma_runtime.py --resource collect --environment local --report-date 2026-07-26
./scripts/report_kappa_admin.py --resource runtime-metrics --environment local
./scripts/report_kappa_admin.py --resource capacity-alerts --environment local
```

本地验收样例：

```json
{
  "report_code": "sigma-runtime-local-20260726",
  "status": "warning",
  "api_request_count": 213,
  "api_failed_count": 0,
  "open_capacity_alert_count": 1,
  "capacity_alert": "sigma-capacity-local-api-api-request-count-7d"
}
```

### 4.15 Tau 真实回款、自动匹配和收入 Ledger

Tau 阶段以 PostgreSQL 事实表、CLI 和 Kappa 只读 API 形式提供真实回款导入、发票自动匹配、收入 ledger 和多币种汇率口径。Tau 不改变 Omicron 原始开票口径，匹配结果以付款、match、invoice event 和 ledger 分录形式追加或幂等更新。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| Demo 回款链路 | `scripts/report_tau_payments.py --resource bootstrap-demo` | 生成独立 demo invoice、导入回款并自动匹配 |
| CSV 回款导入 | `scripts/report_tau_payments.py --resource import-csv` | 从银行/支付机构 CSV 读取流水，写入 batch 和 payment_transaction |
| 自动匹配 | `scripts/report_tau_payments.py --resource match` | 依据 invoice_code hint、币种和未收金额匹配发票 |
| Kappa 观测 | `/admin/payment-batches`、`/admin/payments`、`/admin/payment-matches`、`/admin/revenue-ledger`、`/admin/fx-rates` | 查看回款、匹配、ledger 和汇率 |
| 幂等保护 | `payment_invoice_match` + `revenue_ledger_entry` | 重复导入/重复匹配不膨胀流水和分录，不反向破坏已 paid 发票 |

示例：

```bash
./scripts/report_tau_payments.py \
  --resource bootstrap-demo \
  --as-of-date 2026-07-27 \
  --tenant-code demo \
  --project-code quant-research \
  --amount 100.00000000

./scripts/report_tau_payments.py --resource payment-matches --batch-code tau-demo-payments-20260727
./scripts/report_tau_payments.py --resource revenue-ledger --transaction-code tau-pay-tau-demo-payment-20260727
```

本地验收样例：

```json
{
  "invoice_code": "inv-demo-quant-research-a_share_daily_core-tau-20260727",
  "batch_code": "tau-demo-payments-20260727",
  "transaction_count": 1,
  "match_type": "auto_exact",
  "invoice_status": "paid",
  "matched_amount": "100.00000000"
}
```

### 4.16 Upsilon 前端运营管理台

Upsilon 阶段把 Kappa/Sigma/Tau/Phi/Chi/Psi/Omega/Alpha-2/Beta-2/Gamma-2/Delta-2 的只读运营能力聚合到 `/admin/console`。页面由服务端渲染首屏数据，不引入额外前端构建链；所有数据仍来自 Kappa 只读查询，访问权限沿用 `admin` scope。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 浏览器入口 | `GET /` | 本地开发模式下重定向到 `QData Upsilon Ops Console` |
| 运营台页面 | `GET /admin/console` | 返回 `QData Upsilon Ops Console` HTML |
| 全局筛选 | 页面内搜索框和状态下拉 | 在已渲染表格内按文本和状态过滤 |
| 分组视图 | 页面内 tabs | all/runtime/payments/revenue/vendor/automation/commercial/governance/strategy |
| 支付复核视图 | Payments tab | 查看 payment batch、payment、match、ledger 和 FX rate |
| 运行风险视图 | Runtime tab | 查看 deployment、runtime metric、daily report 和 capacity alert |
| 策略决策视图 | Strategy tab | 查看 Phi run、signal、decision 和 escalation |
| 治理视图 | Governance tab | 查看 Chi access decision、project governance 和 governance action |
| 自动执行视图 | Automation tab | 查看 Lambda/Mu worker、Psi automation run/action、Omega approval/executor/attempt/rollback、Alpha-2 allowlist/secret ref、Beta-2 channel/dispatch/runbook、Gamma-2 profile/validation/rotation 和 Delta-2 live receipt |
| 验收 smoke | `scripts/smoke_upsilon_console.py` | 检查 HTML content-type、关键控件和关键区块 |

示例：

```bash
./scripts/run_api_server.py --backend sql --port 18091 --tokens iotatoken --token-scopes read,admin
./scripts/smoke_upsilon_console.py --base-url http://127.0.0.1:18091 --token iotatoken
```

页面兼容规则：

- `/admin/console` 仍是 Kappa admin path，普通 read token 不可访问。
- 页面只读，不在浏览器内持有或回传 token。
- 页面中所有动态数据必须 HTML escape。
- 表格横向溢出限制在 `.table-wrap` 内，移动端页面本身不能横向撑破。

### 4.17 Phi 统一策略引擎

Phi 阶段新增统一策略运行、信号、决策和升级事件。策略引擎通过 CLI 生成决策，Kappa 只读 API 负责查询，不在 API 层直接修改源事实。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 运行策略 | `scripts/report_phi_strategy.py --resource run-all` | 聚合质量、供应商、运行、商业和回款事实 |
| 策略运行查询 | `GET /admin/strategy-runs` | 返回 run_code、status、highest_severity 和计数 |
| 策略信号查询 | `GET /admin/strategy-signals` | 返回 source_table、source_ref、metric 和 message |
| 策略决策查询 | `GET /admin/strategy-decisions` | 返回 action、status、severity、priority_score 和 reason |
| 策略升级查询 | `GET /admin/strategy-escalations` | 返回 owner、escalation_type、status 和 message |

示例：

```bash
./scripts/report_phi_strategy.py --resource run-all --as-of-date 2026-07-27 --environment local --trigger-mode smoke
./scripts/report_kappa_admin.py --resource strategy-decisions --run-code phi-local-20260727
```

兼容规则：

- Phi 只追加 `strategy_*` 表，不改写源事实表。
- 同一 `run_code` 重跑时替换该 run 下的 signals/decisions/escalations，避免重复膨胀。
- Strategy API 仍要求 `admin` scope，普通 read token 不可访问。
- 旧 Kappa/Upsilon 客户端可忽略新增字段和新增 Strategy 分组。

### 4.18 Chi 多租户治理

Chi 阶段新增权限决策审计、项目治理快照和治理动作。权限校验仍发生在数据 API 请求前，治理数据以追加审计和幂等快照方式落库，Kappa/Upsilon 只读展示。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 权限边界评估 | `scripts/report_chi_governance.py --resource evaluate-access` | 按 tenant/project/principal/dataset/api/fields 判断 allow/deny |
| 权限决策审计 | `GET /admin/access-decisions` | 查看 request_id、decision、effective_scope、access_level、reason 和 denied_fields |
| 项目治理快照 | `GET /admin/project-governance` | 查看项目级请求、失败、拒绝访问、预算、账单、开放动作和风险评分 |
| 治理动作 | `GET /admin/governance-actions` | 查看 review_budget、review_access_policy、rotate_token 等动作 |
| 运营台视图 | `GET /admin/console` Governance tab | 查看 Access Decisions、Project Governance 和 Governance Actions |

示例：

```bash
./scripts/report_chi_governance.py --resource evaluate-access --tenant-code demo --project-code quant-research --principal-code research-bot --dataset-code daily_bar --api-name price --fields close,volume --write-audit
./scripts/report_chi_governance.py --resource collect-snapshots --snapshot-date 2026-07-27 --tenant-code demo --project-code quant-research --write-db --write-actions
./scripts/report_kappa_admin.py --resource project-governance --project-code quant-research
```

兼容规则：

- ACL 匹配严格按 principal > project > tenant，主体级策略不能被其他主体通过同租户 fallback 使用。
- REST 数据接口只在可获得数据库 token 上下文时写 Chi 审计；旧环境 token 查询保持兼容。
- Chi 只追加 `access_decision_audit`、`project_governance_snapshot` 和 `governance_action`，不改变源业务事实。
- `/admin/overview` 新增治理计数字段，旧客户端可忽略。

### 4.19 Psi 自动化执行层

Psi 阶段新增统一自动化 run/action。它从 Phi 策略决策和 Chi 治理动作生成执行计划，默认 dry-run；execute 模式下按 safety_level 和 action_type 应用审批护栏。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 生成执行计划 | `scripts/report_psi_automation.py --resource run --execution-mode dry_run` | 从 Phi/Chi 读取可行动项并写入 automation run/action 审计 |
| 受控执行 | `scripts/report_psi_automation.py --resource run --execution-mode execute` | 中低风险动作可记录执行，高风险动作停在 approval_required |
| 运行查询 | `GET /admin/automation-runs` | 查看 run_code、execution_mode、status、action_count 和审批/失败计数 |
| 动作查询 | `GET /admin/automation-actions` | 查看 source、action_type、safety_level、status、planned/effected effect 和 rollback_hint |
| 运营台视图 | `GET /admin/console` Automation tab | 查看 Automation Runs 和 Automation Actions |

示例：

```bash
./scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode dry_run
./scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode execute --no-chi --source-run-code phi-local-20260727 --run-code psi-local-20260727-execute-phi-safe
./scripts/report_kappa_admin.py --resource automation-actions --limit 10
```

兼容规则：

- Psi 只追加 `automation_run` 和 `automation_action`，不改变数据 API 入参。
- dry-run 不改写源事实，只记录 would_execute 和 approval_required。
- execute 模式下高风险动作必须审批；未审批动作状态为 `approval_required`。
- 已成功执行的同 idempotency_key 动作再次执行会标记 `skipped`，避免重复暂停、重复降级或重复通知。
- 旧 Kappa/Upsilon 客户端可忽略新增 overview 字段和 Automation 表格。

### 4.20 Omega 自动化控制层

Omega 阶段新增生产级自动化控制面。Psi 继续负责从 Phi/Chi 生成动作；Omega 负责审批、executor registry、执行尝试、失败重试、回滚演练和敏感字段脱敏。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 请求审批 | `scripts/report_omega_control.py --resource request-approval` | 为 approval_required action 创建 pending approval |
| 审批决策 | `scripts/report_omega_control.py --resource decide-approval` | 支持 approved/rejected，rejected 动作不会被 execute 自动重开 |
| 执行控制 | `scripts/report_omega_control.py --resource execute` | 按 approval/executor/retry 护栏执行动作并写 attempt |
| 回滚请求 | `scripts/report_omega_control.py --resource request-rollback` | 从 action rollback_hint 生成 rollback_plan |
| 回滚执行 | `scripts/report_omega_control.py --resource run-rollback` | 写入 rollback_result 并更新 action 控制状态 |
| 只读查询 | `GET /admin/automation-approvals` 等 | 查询 approval/executor/attempt/rollback |

示例：

```bash
./scripts/report_omega_control.py --resource execute --run-code psi-local-20260727-execute-phi-safe --trigger-mode smoke --requested-by omega-smoke
./scripts/report_omega_control.py --resource decide-approval --approval-code <approval_code> --decision approved --decided-by platform-lead
./scripts/report_omega_control.py --resource execute --action-code <action_code> --trigger-mode smoke --requested-by omega-smoke
./scripts/report_omega_control.py --resource request-rollback --action-code <action_code> --requested-by omega-smoke --reason "smoke rollback drill"
./scripts/report_omega_control.py --resource run-rollback --rollback-code <rollback_code> --executed-by platform-lead
./scripts/report_kappa_admin.py --resource automation-attempts --limit 10
```

兼容规则：

- Omega 只追加控制元数据和 `automation_action` 控制字段，不改变数据 API 入参。
- 默认 executor 为 `noop`，不会触发外部副作用；webhook/script 需要显式配置和显式允许。
- 高风险动作必须有 approved approval 才能执行；pending/rejected/expired 均会被 attempt 审计拦截。
- retry_scheduled 只记录下一次可重试时间和次数，不无限重试。
- Kappa 查询会递归脱敏 token/secret/password/authorization 等敏感字段。

### 4.21 Alpha-2 白名单外部执行沙箱

Alpha-2 阶段把 Omega 的 webhook/script executor 从“只登记、不实际调用”推进到沙箱内真实 dispatch。它只允许显式 `--allow-external` 的执行，并要求 executor 绑定 active allowlist；secret 表只保存环境变量引用等元数据，不保存密钥明文。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 脚本沙箱执行 | `scripts/report_omega_control.py --resource execute --executor-code alpha2-script-notify-owner --allow-external` | 只允许运行仓库内白名单 Python 脚本，记录 stdout/stderr/returncode |
| Webhook 沙箱执行 | `scripts/report_omega_control.py --resource execute --executor-code alpha2-webhook-notify-owner --allow-external` | 只允许 allowlist URL，支持 HMAC-SHA256 请求签名 |
| 白名单查询 | `GET /admin/automation-allowlists` | 查看 allowlist_code、executor_type、target_pattern、sandbox_only 和 timeout |
| 密钥引用查询 | `GET /admin/automation-secrets` | 查看 secret_ref、secret_scope、secret_kind、owner 和 env_var 元数据 |
| 控制台展示 | `GET /admin/console` | Automation tab 展示 Alpha-2 executor/allowlist/secret ref |

兼容规则：

- Alpha-2 只追加 `automation_executor_allowlist`、`automation_secret_ref` 和 executor 安全字段，不改变数据 API 入参。
- script target 必须是项目内相对路径、不得包含 `..`、文件必须存在且后缀为 `.py`。
- webhook/script 即使执行成功，response_payload 也标记 `external_side_effect=false` 和 `sandbox_dispatch=true`。
- HMAC secret value 只能来自 `metadata.env_var` 指向的运行环境变量，Kappa/API 不返回密钥明文。

### 4.22 Beta-2 通知/审批联调闭环

Beta-2 阶段把 Alpha-2 沙箱执行能力包装成真实通知/审批联调闭环。它记录外部 channel、每次 dispatch、重复抑制、失败 retry/dead-letter 和人工恢复 runbook；所有外部调用仍要求显式 `--allow-external`。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 外部 dispatch | `scripts/report_beta2_external.py --resource dispatch` | 对指定 action/channel 发起通知或审批请求 |
| 人工恢复 | `scripts/report_beta2_external.py --resource recover` | 将 failed/retry_scheduled/dead_letter dispatch 标记 recovered |
| 通道查询 | `GET /admin/automation-channels` | 查看 channel endpoint、allowlist、secret ref、重试和重复窗口 |
| Dispatch 查询 | `GET /admin/automation-dispatches` | 查看 acknowledged/suppressed/retry_scheduled/dead_letter/recovered 状态 |
| Runbook 查询 | `GET /admin/automation-runbooks` | 查看 failure_class、severity、owner 和恢复步骤 |

兼容规则：

- Beta-2 只追加外部联调审计元数据，不改变数据 API 入参。
- 同一 action/channel/dispatch_type 在 duplicate_window 内已有成功 dispatch 时，新触发只写 `suppressed`，不重复调用外部系统。
- 外部调用失败时按 channel retry budget 进入 `retry_scheduled` 或 `dead_letter`；人工恢复只更新 dispatch，不删除失败证据。
- channel 的 secret_ref 仍只引用 env var，Kappa/API 不返回密钥明文。

### 4.23 Gamma-2 多环境通道与密钥轮换

Gamma-2 阶段在 Beta-2 dispatch 之上新增 provider profile、联调验证和 secret rotation 记录。它用于把本地可运行的 webhook dry-run，平滑升级到飞书/企业微信/邮件测试通道，并保留候选密钥验证、应用和回滚证据；真实外部调用仍要求显式 `--allow-external`。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| Profile 查询 | `GET /admin/automation-channel-profiles` | 查看 provider_code、environment、dry_run_only、secret_ref、next_secret_ref 和 readiness_status |
| 联调验证查询 | `GET /admin/automation-channel-validations` | 查看 dry_run/live/secret_rotation/rollback_drill 的 validation 结果和 dispatch 证据 |
| 密钥轮换查询 | `GET /admin/automation-secret-rotations` | 查看 secret_ref -> next_secret_ref 的 validated/applied/rolled_back/failed/blocked 记录 |
| 本地联调 CLI | `scripts/report_gamma2_external.py --resource validate` | 对指定 profile/action 触发 Beta-2 dispatch，并更新 readiness |
| 密钥轮换 CLI | `scripts/report_gamma2_external.py --resource rotate` | 先用 target_secret_ref 做签名验证，再可选 `--apply-rotation` 更新通道 secret_ref |
| 轮换回滚 CLI | `scripts/report_gamma2_external.py --resource rollback` | 将已 applied rotation 的 channel/profile secret_ref 回退到原值 |

兼容规则：

- Gamma-2 只追加 profile、validation 和 rotation 审计元数据，不改变数据 API 入参。
- secret value 仍只来自 `automation_secret_ref.metadata.env_var`，数据库和 Kappa/API 只保存引用、env 名和短 fingerprint，不保存明文。
- `--apply-rotation` 必须绑定 profile/action 并通过候选 secret 验证；失败只写审计记录，不更新通道。
- seeded provider profile 默认 `dry_run_only=true`，真实飞书/企业微信/邮件 live endpoint 需要人工改为非 dry-run 并完成 live validation。

### 4.24 Delta-2 企业微信 live validation

Delta-2 阶段把 Gamma-2 的企业微信 dry-run profile 升级为可选 live validation：支持企业微信群机器人 webhook 的 markdown 消息发送、企业微信返回 `errcode/errmsg` 回执审计，以及 Kappa/Upsilon 展示。真实 webhook URL 只从 `QDATA_DELTA2_WECOM_WEBHOOK_URL` 环境变量读取，不落库。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 企业微信 live validation | `scripts/report_delta2_wecom.py --resource validate --allow-external` | 向企业微信群机器人发送 markdown 测试消息，并写入 validation/receipt |
| 企业微信 smoke | `scripts/smoke_delta2_wecom.py --allow-external --require-live` | 要求配置真实 webhook env，发送测试消息并检查 `errcode=0` |
| 安全阻断 smoke | `scripts/smoke_delta2_wecom.py` | 未配置或未显式 allow 时不发送消息，只写 blocked receipt |
| live 回执查询 | `GET /admin/automation-live-receipts` | 查看 receipt_code、provider_errcode、provider_errmsg、status 和 error_message |
| 控制台展示 | `GET /admin/console` | Automation tab 展示 Automation Live Receipts |

兼容规则：

- Delta-2 只追加 `automation_live_provider_receipt` 和企业微信 live profile，不改变数据 API 入参。
- 真实企业微信 webhook URL 只来自 `automation_secret_ref.metadata.env_var=QDATA_DELTA2_WECOM_WEBHOOK_URL`，数据库、Kappa/API 和 CLI 均不输出 URL 明文。
- 未显式 `--allow-external` 时 status=`blocked`，error_message=`external_live_dispatch_disabled`，不会向企业微信发送消息。
- 配置了 `--require-live` 但没有 webhook env 时 smoke 必须失败，避免误以为真实联调成功。
- 企业微信 HTTP 200 且 body `errcode=0` 才算 success；非 0 errcode 或网络异常都记录 failed/blocked 证据。

### 4.25 Epsilon-3 真实供应商 live token gate

Epsilon-3 阶段把 Pi readiness 和 Theta benchmark 串成真实供应商上线门禁：默认只写 blocked gate，只有显式 `--allow-live` 且真实 `QDATA_VENDOR_*` 环境齐备时，才允许触发 live benchmark。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 安全阻断 smoke | `scripts/smoke_epsilon3_vendor_live_gate.py` | 未显式 allow 时不调用外部供应商，只写 blocked gate |
| 强制 live smoke | `scripts/smoke_epsilon3_vendor_live_gate.py --allow-live --require-live` | 缺少 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时必须失败 |
| live benchmark gate | `scripts/run_epsilon3_vendor_live_gate.py --resource run --allow-live --run-benchmarks` | 按 5/20/60 窗口执行 vendor_http 与主源 benchmark，并生成 readiness review |
| gate 查询 | `GET /admin/vendor-live-gates` | 查看 gate_code、run_mode、status、required_windows、executed_windows、env present flag 和阻塞原因 |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Live Gates |

兼容规则：

- Epsilon-3 只追加 `vendor_live_gate_run` 审计表，不改变数据 API 入参。
- 真实供应商 token 只来自 `QDATA_VENDOR_TOKEN`，数据库、Kappa/API、CLI 和 Upsilon 不输出明文。
- 未显式 `--allow-live` 时 status=`blocked`，不会产生外部供应商请求。
- `--require-live` 在缺少真实 env 时必须失败，防止把 fixture 或 blocked smoke 当作生产联调成功。
- 如果未显式设置 `QDATA_VENDOR_AUTH_MODE`，门禁继承 DB vendor profile 的 `auth_mode`；当前 seeded `vendor_http` profile 为 bearer。

### 4.26 Zeta-3 真实供应商接入运营化

Zeta-3 阶段把真实供应商接入从单次 live gate 升级为可审计 onboarding 流程：先做 env/profile/contract/rate limit/dataset preflight，再按数据集执行 canary 和 Epsilon-3 gate，最后生成 run 级推荐角色。默认仍是 blocked 安全模式，不会调用外部供应商。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 安全阻断 smoke | `scripts/smoke_zeta3_vendor_onboarding.py` | 未显式 allow 时只写 onboarding/gate 审计，不调用外部供应商 |
| 强制 live smoke | `scripts/smoke_zeta3_vendor_onboarding.py --allow-live --require-live` | 缺少 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时必须失败 |
| onboarding 执行 | `scripts/run_zeta3_vendor_onboarding.py --resource run` | 默认覆盖 daily_bar、security_master、adjustment_factor、limit_price_daily 和 5/20/60 窗口 |
| run 查询 | `GET /admin/vendor-onboarding-runs` | 查看预检、金丝雀、gate、orchestration 状态和推荐角色 |
| result 查询 | `GET /admin/vendor-onboarding-results` | 查看每个数据集的阻塞原因、next action 和关联 gate |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Onboarding Runs/Results 和 Live Gates |

兼容规则：

- Zeta-3 只追加 `vendor_onboarding_run` 和 `vendor_onboarding_dataset_result` 审计表，不改变数据 API 入参。
- 真实供应商 token 仍只来自 `QDATA_VENDOR_TOKEN`，数据库、Kappa/API、CLI 和 Upsilon 不输出明文。
- 未显式 `--allow-live --run-benchmarks` 时不会产生真实外部供应商请求。
- `--require-live` 在缺少真实 env 时必须失败，避免把本地 blocked smoke 当作生产联调成功。
- 非 daily_bar 数据集在真实 provider endpoint 未补齐前只记录 `live_benchmark_not_implemented:<dataset>` 或 dataset/profile 阻塞原因，不得给出 primary_candidate。

### 4.27 Eta-3 真实供应商 Live 接入闭环

Eta-3 阶段把 Zeta-3 onboarding 继续推进为真实供应商 live 接入闭环：先校验 profile/合同/再分发/限频，再对每个 dataset 做 endpoint schema probe，随后联动 Zeta-3 onboarding/gate 证据，并产出是否可进入 research_only/backup/primary_candidate 的审计结论。默认仍为安全 blocked 模式，不会调用外部供应商。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 安全阻断 smoke | `scripts/smoke_eta3_vendor_live_closure.py` | 未显式 allow 时只写 closure/probe/onboarding 审计，不调用外部供应商 |
| 强制 live smoke | `scripts/smoke_eta3_vendor_live_closure.py --allow-live --require-live` | 缺少 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时必须失败 |
| live closure 执行 | `scripts/run_eta3_vendor_live_closure.py --resource run --allow-live --run-endpoint-probes` | 对 daily_bar、security_master、adjustment_factor、limit_price_daily 做 endpoint probe 和 onboarding 编排 |
| profile 安全写入 | `scripts/run_eta3_vendor_live_closure.py --resource run --allow-profile-write --activate-profile --enable-profile-datasets` | 显式允许后才更新 profile endpoint/dataset/status/合同/授权/限频元数据 |
| closure 查询 | `GET /admin/vendor-live-closures` | 查看 closure_code、预检、endpoint、onboarding、promotion 状态和推荐角色 |
| probe 查询 | `GET /admin/vendor-live-probes` | 查看每个 dataset 的 endpoint_path、auth/schema 状态、missing_fields 和阻塞原因 |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Live Closures 和 Vendor Live Probes |

兼容规则：

- Eta-3 只追加 `vendor_live_closure_run` 和 `vendor_live_endpoint_probe` 审计表，不改变数据 API 入参。
- 真实供应商 token 只来自 `QDATA_VENDOR_TOKEN`，数据库、Kappa/API、CLI 和 Upsilon 不输出明文 token。
- 未显式 `--allow-live` 或 endpoint probes 被 `--no-endpoint-probes` 关闭时，不会产生真实外部供应商请求；`--run-endpoint-probes` 可用于在命令中明确 live probe 意图。
- profile 写入必须显式 `--allow-profile-write`；未授权时只记录 blocked/next action，不修改供应商 profile。
- `--require-live` 在缺少真实 env、合同、再分发授权、rate limit 或必要 dataset/profile 条件时必须失败，避免把 blocked smoke 当作真实供应商联调成功。
- endpoint probe 只保存字段名、状态、计数、耗时和脱敏 evidence；不保存供应商原始响应正文或 token。

### 4.28 Theta-3 真实供应商 Live Pilot 试运行

Theta-3 阶段把 Eta-3 closure 变成可审计的真实供应商试运行：默认先复用 blocked closure/probe/onboarding/gate 证据生成 pilot run/result，不触发外部供应商；只有显式 `--allow-live --require-live` 且真实 env、profile、合同、授权、限频、schema 和 onboarding 全部具备时，才进入真实 live pilot。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 安全阻断 smoke | `scripts/smoke_theta3_vendor_live_pilot.py` | 默认写入 pilot run/result 和 Eta-3 closure 证据，不调用外部供应商 |
| 强制 live smoke | `scripts/smoke_theta3_vendor_live_pilot.py --allow-live --require-live` | 缺少真实供应商 env 时必须失败为 `missing_vendor_live_env` |
| live pilot 执行 | `scripts/run_theta3_vendor_live_pilot.py --resource run --allow-live --require-live` | 对 canary/full_market scope 生成试运行批次、dataset result、签核状态和风险等级 |
| pilot 查询 | `GET /admin/vendor-live-pilots` | 查看 pilot_code、closure_status、endpoint/onboarding/benchmark、signoff、recommendation 和 risk_level |
| result 查询 | `GET /admin/vendor-live-pilot-results` | 查看 dataset 级 closure/probe/gate/schema/benchmark 结果、missing_fields 和阻塞原因 |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Live Pilots 和 Vendor Live Pilot Results |

兼容规则：

- Theta-3 只追加 `vendor_live_pilot_run` 和 `vendor_live_pilot_dataset_result` 审计表，不改写 Eta-3、Zeta-3、Epsilon-3 或原始行情事实。
- 真实供应商 token 只来自环境变量，数据库、Kappa/API、CLI 和 Upsilon 不输出明文 token、Authorization header 或原始响应正文。
- 默认 smoke 不触发外部请求；真实试运行必须显式 `--allow-live --require-live`，并满足 active profile、合同引用、再分发授权、rate limit、完整 dataset、endpoint schema 和 onboarding/gate 条件。
- `signoff_status` 只有在 backup/primary_candidate 证据齐备后才进入 `pending_review`；blocked/failed 必须为 `not_ready`。
- `risk_level` 聚合 dataset 结果：failed 为 critical，blocked 为 high，warning 为 medium，全部成功才为 low。

### 4.29 Iota-3 免费源联盟 Free Source Fabric

Iota-3 阶段把免费源做成可审计的研发/备份/校验层：默认只跑本地 `csv/csv_mirror` fixture，不触发外部免费网站；显式 `--allow-external` 后才允许试运行 AKShare、BaoStock、TuShare 免费档、巨潮、交易所、国家统计局等候选源。免费源的结论默认只能作为 `research_only` 或 `backup` 证据，不能替代商业授权主供应商。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| 免费源目录 | `scripts/run_iota3_free_source_fabric.py --resource catalog` | 查看候选源、provider、是否外部、授权状态和覆盖数据集 |
| 本地联盟 smoke | `scripts/smoke_iota3_free_source_fabric.py` | 用 `csv/csv_mirror` 验证覆盖率、冲突率、run/result 落库和无外部副作用 |
| 外部免费源试运行 | `scripts/run_iota3_free_source_fabric.py --resource run --allow-external --source-codes csv,csv_mirror,akshare` | 显式允许后才调用外部免费源，并把结果按数据集审计 |
| run 查询 | `GET /admin/free-source-fabric-runs` | 查看 fabric_code、coverage_rate、conflict_rate_bps、license_review_required_count 和 recommendation |
| result 查询 | `GET /admin/free-source-fabric-results` | 查看 dataset 级 coverage/consistency/license/freshness 状态和 source evidence |
| 控制台展示 | `GET /admin/console` | Free Sources tab 展示 Free Source Fabric Runs 和 Results |

兼容规则：

- Iota-3 只追加 `free_source_fabric_run` 和 `free_source_fabric_dataset_result` 审计表，不改写原始行情、供应商 pilot、账单或权限数据。
- 默认 smoke 不调用外部网站；外部免费源必须显式 `--allow-external`，强制真实外部成功可用 `--require-external`。
- 免费源原始行不写入审计表，只保存计数、状态、阈值、冲突摘要和脱敏 evidence。
- `--require-commercial-clearance` 打开时，research_only/review_required/free quota 未清晰授权的数据集必须 blocked，避免误把免费源当生产商业主源。

### 4.30 Iota-4 外部免费源真实 Canary

Iota-4 复用 Iota-3 fabric 表和 Kappa/Upsilon 查询面，把 AKShare 外部免费源 canary 固化为可重复 smoke。`iota4_external_free_source_canary=ok` 只代表外部链路、字段解析、覆盖率和审计落库通过，不代表免费源已具备商业生产授权。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| AKShare live-only canary | `scripts/smoke_iota4_external_free_source_canary.py` | 默认跑 `akshare`、daily_bar/security_master/trading_calendar，要求外部源真实执行 |
| AKShare compare-local canary | `scripts/smoke_iota4_external_free_source_canary.py --mode compare-local` | 跑 `csv/csv_mirror/akshare`，验证 AKShare 进入多源 fabric 审计 |
| run 查询 | `GET /admin/free-source-fabric-runs?requested_by=iota4` | 查看 Iota-4 canary run、coverage_rate、license warning 和 recommendation |
| result 查询 | `GET /admin/free-source-fabric-results?source_code=akshare` | 查看 AKShare dataset 级 coverage/consistency/license/freshness 状态 |
| 控制台展示 | `GET /admin/console` | Free Sources tab 展示 Iota-4 最新 run/result |

兼容规则：

- Iota-4 不新增表，继续写入 `free_source_fabric_run` 和 `free_source_fabric_dataset_result`。
- `fabric_status=warning` 可以是通过的 canary 结果，只要外部源已执行且覆盖率达标；warning 代表授权或免费源边界仍需保留。
- `commercial_clearance=blocked` 时不得把免费源晋级为 primary_candidate 或商业生产主源。
- compare-local 模式只证明多源比对链路可用，不把本地 fixture 当成真实行情基准。

### 4.31 Iota-5 多免费源 Adapter Pool

Iota-5 继续复用 Iota-3 fabric 表，把 AKShare、BaoStock、TuShare free 和官方公开源 scaffold 统一纳入 adapter pool。当前阶段重点是 provider 可解释性、超时控制、token guard 和 Kappa/Upsilon 可审计，不把免费源误判为商业生产主源。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| adapter pool smoke | `scripts/smoke_iota5_free_source_adapter_pool.py` | 默认评估 akshare/baostock/tushare_free/sse_public/szse_public/cninfo_public |
| strict ok gate | `scripts/smoke_iota5_free_source_adapter_pool.py --require-ok --tushare-token <token>` | 至少两个外部免费源真实成功才返回 ok |
| run 查询 | `GET /admin/free-source-fabric-runs?requested_by=iota5` | 查看 Iota-5 pool run、baseline、coverage、risk 和 recommendation |
| source result 查询 | `GET /admin/free-source-fabric-results?source_code=baostock` | 查看 source 级失败、覆盖和授权状态 |
| 控制台展示 | `GET /admin/console` | Free Sources tab 展示 Iota-5 run/result |

兼容规则：

- Iota-5 不新增表，继续写入 `free_source_fabric_run` 和 `free_source_fabric_dataset_result`。
- BaoStock 必须设置 socket timeout；网络不可达时返回 degraded/failed evidence，不能挂住 smoke。
- TuShare free 没有 token 时必须 blocked；token 不得写入数据库、Kappa API、CLI 或 Upsilon。
- 官方公开源在 endpoint/授权/字段口径确认前只能 scaffold-only，不能抓取原始网页正文进入生产表。
- degraded 不是 primary_candidate；免费源没有商业授权前只能 research_only、validator 或 backup 候选。

### 4.32 Kappa-5 免费源可靠性评分和自动降级

Kappa-5 新增 `free_source_reliability_snapshot`，把 Iota-3/Iota-5 fabric result 转成 source+dataset 级的可靠性评分。评分只服务免费源研发、校验、备份和降级决策；在没有商业清晰授权前，不会把免费源推荐为商业生产主源。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| reliability score | `scripts/run_kappa5_free_source_reliability.py --resource score --lookback-hours 72` | 从最近 fabric result 生成 source+dataset reliability snapshot |
| reliability smoke | `scripts/smoke_kappa5_free_source_reliability.py --lookback-hours 72` | 输出 snapshot_count、ready/watch/degraded/rejected/no_data 和分数范围 |
| reliability 查询 | `GET /admin/free-source-reliability` | 查询可靠性评分、推荐角色、授权状态、商业清晰度、连续失败和恢复动作 |
| overview | `GET /admin/overview` | 展示 free_source_24h_reliability_count、ready/degraded/rejected 和 latest status |
| 控制台展示 | `GET /admin/console` | Free Sources tab 展示 Free Source Reliability |

兼容规则：

- Kappa-5 只追加 `free_source_reliability_snapshot`，不改写 fabric run/result、行情、供应商、账单、权限或生产事实。
- score 低、连续失败、token 缺失、socket 超时、official scaffold 或冲突率过高必须进入 watch/degraded/rejected。
- local_smoke/research_only/review_required/blocked 免费源不得被推荐为商业 production primary。
- evidence 只保存脱敏观察样本、阈值和原因，不保存 token、Authorization header 或未确认授权的原始网页正文。

### 4.33 Lambda-5 免费源恢复编排、重试、告警和人工复核

Lambda-5 新增 `free_source_recovery_run` 和 `free_source_recovery_action`，把 Kappa-5 reliability snapshot 转成可审计的恢复动作。恢复动作只服务研发、校验、备份和人工复核，不会把免费源提升为商业生产主源。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| recovery run | `scripts/run_lambda5_free_source_recovery.py --resource recover --lookback-hours 72` | 从最近 Kappa-5 snapshot 生成恢复 run/action，并按策略写入告警 |
| recovery smoke | `scripts/smoke_lambda5_free_source_recovery.py --lookback-hours 72` | 输出 snapshot_count、action_count、retry、alerts 和 manual_review |
| worker task | `scripts/run_lambda_worker.py --task free_source_recovery` | 作为 Lambda worker task 运行，Mu 可通过 `mu_free_source_recovery_30m` 定时触发 |
| recovery 查询 | `GET /admin/free-source-recovery-runs` | 查询恢复批次、状态、动作数、告警数和阻塞原因 |
| action 查询 | `GET /admin/free-source-recovery-actions` | 查询每条 source+dataset 的 retry/manual_review/observe 动作 |
| overview | `GET /admin/overview` | 展示 free_source_24h_recovery_count、action_count、alert_count 和 latest status |
| 控制台展示 | `GET /admin/console` | Free Sources tab 展示 Free Source Recovery Runs/Actions |

兼容规则：

- Lambda-5 只追加恢复审计表并扩展 worker task/alert_type 枚举，不改写 Kappa-5 snapshot、fabric、行情、供应商、账单、权限或生产事实。
- dry-run 只预览动作，不写 recovery run/action 或 alert。
- `free_source_recovery_required` 告警不得包含 token、Authorization header、真实 webhook URL 或未确认授权的原始网页正文。
- rejected/blocked 免费源必须进入 manual_review/alert，不得进入自动生产 fallback。

### 4.34 Mu-5 免费源恢复执行闭环

Mu-5 新增 `free_source_recovery_execution`，把 Lambda-5 生成的恢复动作推进到执行层：`retry_canary` 接入 Iota-5 canary，`manual_review` 接入 Omega 审批和 Delta-2 企业微信通知，执行结果回写为 recovered/failed/suppressed/review_requested。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| recovery execute | `scripts/run_mu5_free_source_recovery_executor.py --resource execute --max-actions 20` | 执行待处理 retry/manual_review 动作并写入 execution 审计 |
| recovery smoke | `scripts/smoke_mu5_free_source_recovery_executor.py` | 默认处理 1 条 manual_review，企业微信外发关闭，只验证审批和回执阻断链路 |
| worker task | `scripts/run_lambda_worker.py --task free_source_recovery_execute` | 作为 Lambda worker task 运行，Mu 可通过 `mu_free_source_recovery_execute_30m` 定时触发 |
| execution 查询 | `GET /admin/free-source-recovery-executions` | 查询执行状态、Iota-5 fabric、approval 和 WeCom receipt |
| overview | `GET /admin/overview` | 展示 free_source_24h_recovery_execution_count、recovered、failed 和 latest execution status |
| 控制台展示 | `GET /admin/console` | Free Sources tab 展示 Free Source Recovery Executions |

兼容规则：

- Mu-5 只追加 execution 审计并扩展 worker/action 状态枚举，不改写 Kappa-5 snapshot、fabric、行情、供应商、账单、权限或生产事实。
- `retry_canary` 只有 Iota-5 pool status 为 ok 才回写 recovered；degraded/failed 一律回写 failed。
- `manual_review` 只生成审批和可选企业微信通知，未显式 `--allow-wecom-external` 不外发消息。
- token、Authorization header、企业微信 webhook URL 和未确认授权的原始网页正文不得写入 DB、CLI、Kappa API 或 Upsilon HTML。

### 4.35 Nu-5 免费源恢复健康、审批 SLA 和 runbook

Nu-5 新增 `free_source_recovery_health_snapshot`，读取 Mu-5 action/execution、Omega approval 和 worker schedule/run 证据，输出恢复闭环的长期健康状态、审批 SLA、backlog、失败率、调度陈旧度和处置建议。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| health check | `scripts/run_nu5_free_source_recovery_health.py --resource check` | 写入一次 health snapshot，输出 status、backlog、approval overdue、failure 和 stale schedule |
| health smoke | `scripts/smoke_nu5_free_source_recovery_health.py` | 验证 snapshot 可写可查，critical/warning 视为健康检查发现风险而不是 smoke 失败 |
| worker task | `scripts/run_lambda_worker.py --task free_source_recovery_health` | 作为 Lambda worker task 运行，Mu 可通过 `nu_free_source_recovery_health_15m` 定时触发 |
| health 查询 | `GET /admin/free-source-recovery-health` | 查询健康快照、SLA、backlog、失败率、latest worker/schedule/execution 和 runbook |
| overview | `GET /admin/overview` | 展示 latest health status、24h health count、overdue approvals 和 recovery backlog |
| 控制台展示 | `GET /admin/console` | Free Sources tab 展示 Free Source Recovery Health |

兼容规则：

- Nu-5 只追加 health snapshot 并扩展 worker task 枚举，不改写恢复 action、审批、行情、供应商、账单、权限或生产事实。
- critical health 必须映射为 worker task failed，warning 必须映射为 worker task warning。
- `health_issues` 和 `runbook_actions` 必须能解释审批超时、backlog、失败率、调度陈旧或 worker failed。
- evidence 只保存阈值、schedule/run 状态和策略说明，不保存 token、Authorization header、真实 webhook URL 或未确认授权的原始网页正文。

### 4.36 Xi-5 免费源授权准入、合同和转授权矩阵

Xi-5 新增 `free_source_admission_profile` 和 `free_source_admission_snapshot`，把免费源/低价平替源的授权、商用许可、再分发、合同、条款复核、限频配额和 Kappa-5 可靠性证据汇总成 source+dataset 准入结论。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| admission review | `scripts/run_xi5_free_source_admission.py --resource review` | 写入 source+dataset 准入快照，输出 approved、conditional、review_required、blocked、no_data 和 primary_candidate 计数 |
| admission smoke | `scripts/smoke_xi5_free_source_admission.py` | 验证 profile 和 snapshot 可写可查 |
| worker task | `scripts/run_lambda_worker.py --task free_source_admission_review` | 作为 Lambda worker task 运行，Mu 可通过 `xi_free_source_admission_review_6h` 定时触发 |
| profile 查询 | `GET /admin/free-source-admission-profiles` | 查询源级法律/合同/配额档案 |
| admission 查询 | `GET /admin/free-source-admission` | 查询 source+dataset 准入矩阵、阻断原因、required_actions 和可靠性证据 |
| overview | `GET /admin/overview` | 展示 24h admission、approved/conditional/review_required/blocked/no_data 和 primary_candidate 计数 |
| 控制台展示 | `GET /admin/console` | Free Sources tab 展示 Free Source Admission 和 Free Source Admission Profiles |

兼容规则：

- `primary_candidate` 只允许在合同 active、商用许可 clear、再分发 yes、条款 approved、限频/日配额齐全且可靠性达标时出现。
- 免费、research_only、review_required、local_smoke 或未确认转授权的源，不得被推荐为商业生产主源。
- Xi-5 只追加准入档案和快照，不改写行情、供应商、账单、权限或生产事实。

### 4.37 Omicron-5 真实主供应商采购、合同和授权闭环

Omicron-5 新增 `vendor_contract_profile`、`vendor_contract_dataset_entitlement` 和 `vendor_procurement_readiness_snapshot`，把真实主供应商的采购状态、合同附件引用、商用许可、再分发/缓存权、生产使用权、dataset 授权、SLA、配额和 Pi/Epsilon-3/Zeta-3/Eta-3/Theta-3 live 证据汇总成 source+dataset 采购 readiness 结论。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| procurement review | `scripts/run_omicron5_vendor_contract.py --resource review` | 写入 source+dataset 采购 readiness 快照，输出 ready、conditional、review_required、blocked、no_contract 和 primary_candidate 计数 |
| procurement smoke | `scripts/smoke_omicron5_vendor_contract.py` | 验证合同 profile、dataset entitlement 和 readiness snapshot 可写可查 |
| worker task | `scripts/run_lambda_worker.py --task vendor_contract_readiness_review` | 作为 Lambda worker task 运行，Mu 可通过 `omicron5_vendor_contract_readiness_6h` 定时触发 |
| contract profile 查询 | `GET /admin/vendor-contract-profiles` | 查询主供应商合同、采购、商用、再分发、生产使用、SLA、配额和负责人元数据 |
| entitlement 查询 | `GET /admin/vendor-contract-entitlements` | 查询每个 dataset 的授权角色、schema、字段映射、限频、quota 和阻断原因 |
| procurement readiness 查询 | `GET /admin/vendor-procurement-readiness` | 查询 source+dataset 采购结论、主源角色、blocking_issues、required_actions 和 live 证据 |
| overview | `GET /admin/overview` | 展示 24h procurement readiness、ready/review_required/blocked 和 primary_candidate 计数 |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Contract Profiles、Vendor Contract Entitlements 和 Vendor Procurement Readiness |

兼容规则：

- `primary_candidate` 只允许在采购 active、合同 active、商用许可 clear、再分发 yes、生产使用允许、合同引用存在、dataset entitlement active、schema/field mapping validated、限频/日配额/SLA 齐全且未被 live 证据阻断时出现。
- seeded `vendor_http` 只是合同模板和研发验收源，默认 `review_required/blocked`，不会被误推为生产主源。
- Omicron-5 只追加合同、授权和采购 readiness 元数据，不改写行情、免费源、账单、权限或生产事实。
- token、Authorization header、供应商原始响应正文不得写入 DB、CLI、Kappa API 或 Upsilon HTML。

### 4.38 Pi-5 授权主供应商生产切主闭环

Pi-5 新增 `vendor_primary_promotion_run` 和 `vendor_primary_promotion_dataset_result`，把 Omicron-5 采购 readiness、Pi 5/20/60 readiness、Theta-3 canary/full-market pilot、签批状态和当前 `source_priority` 合成可审计的生产切主结论。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| promotion review | `scripts/run_pi5_vendor_primary_promotion.py --resource run` | 生成一条 promotion run 和每个 dataset 的切主结论；默认 review-only，不改写 routing |
| promotion smoke | `scripts/smoke_pi5_vendor_primary_promotion.py` | 验证 run/result 可写可查，并输出 approved/pending/blocked/applied 计数 |
| worker task | `scripts/run_lambda_worker.py --task vendor_primary_promotion_review` | 作为 Lambda worker task 运行，Mu 可通过 `pi5_vendor_primary_promotion_6h` 定时触发 |
| promotion run 查询 | `GET /admin/vendor-primary-promotions` | 查询 promotion_scope、apply_mode、routing_change_allowed/applied、dataset 计数、blocking_issues 和 required_actions |
| promotion result 查询 | `GET /admin/vendor-primary-promotion-results` | 查询每个 dataset 的 procurement、readiness、canary/full-market、签批、当前主源和目标 priority |
| overview | `GET /admin/overview` | 展示 24h promotion run、approved/blocked/applied dataset、最近 promotion status 和 routing_allowed 计数 |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Primary Promotions 和 Vendor Primary Promotion Results |

兼容规则：

- 默认 `apply_mode=review_only`，`pi5_apply_routing=false`；定时任务不会自动修改 `source_priority`。
- 只有所有 dataset 已为 `approved_for_primary` 或 `applied`，且显式启用 `--apply-routing` / `QDATA_PI5_APPLY_ROUTING=true` 时，才允许幂等更新 `source_priority`。
- 任何缺失 Omicron-5 `ready/primary_candidate`、Pi `approve_primary`、Theta-3 canary/full-market 或签批证据的 dataset，都必须进入 blocked、canary_required、full_market_required 或 pending_signoff。
- Pi-5 不改写行情、免费源、账单、权限或供应商原始事实；只追加 promotion 审计，必要时受控更新路由表。

### 4.39 Rho-5 主源切换后监控和回滚闭环

Rho-5 新增 `vendor_post_promotion_monitor_run` 和 `vendor_post_promotion_dataset_monitor`，把 Pi-5 applied promotion、当前 `source_priority`、前一主源和影子对账指标合成切主后的健康、回滚建议和回滚演练审计。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| monitor run | `scripts/run_rho5_post_promotion_monitor.py --resource run` | 生成一条 post-promotion monitor run 和每个 dataset 的监控结论；默认 review-only |
| monitor smoke | `scripts/smoke_rho5_post_promotion_monitor.py` | 验证 run/result 可写可查；没有 applied Pi-5 时输出 `no_applied_promotion` |
| worker task | `scripts/run_lambda_worker.py --task vendor_post_promotion_monitor` | 作为 Lambda worker task 运行，Mu 可通过 `rho5_post_promotion_monitor_1h` 定时触发 |
| monitor 查询 | `GET /admin/vendor-post-promotion-monitors` | 查询 monitor_scope、rollback_mode、rollback_allowed/applied、dataset 计数、blocking_issues 和 required_actions |
| result 查询 | `GET /admin/vendor-post-promotion-results` | 查询每个 dataset 的 promotion result、当前/前一主源、shadow_status、冲突率、失败率、陈旧分钟数和回滚状态 |
| overview | `GET /admin/overview` | 展示 24h post-promotion monitor、healthy、rollback_recommended、rolled_back、no_applied 和 rollback_allowed 计数 |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Post Promotion Monitors 和 Vendor Post Promotion Results |

兼容规则：

- 默认 `rollback_mode=review_only`，`rho5_apply_rollback=false`；定时任务不会自动修改 `source_priority`。
- 若没有 applied Pi-5 promotion，Rho-5 必须输出 `no_applied_promotion`，作为清晰的生产前提阻断，而不是静默空结果。
- 只有当前主源确认为 promoted source、shadow 指标超过阈值、前一主源存在且显式启用 `--apply-rollback` / `QDATA_RHO5_APPLY_ROLLBACK=true` 时，才允许幂等回滚 `source_priority`。
- Rho-5 不改写行情、免费源、账单、权限或供应商原始事实；只追加 post-promotion 审计，必要时受控更新路由表。

### 4.40 Sigma-5 主供应商长期生产稳定性

Sigma-5 新增 `vendor_primary_stability_snapshot` 和 `vendor_primary_stability_dataset_snapshot`，把 Omicron-5 授权、Pi-5 切主、Rho-5 事后监控、API audit、worker/scheduler 和 capacity alert 聚合成长期生产 SLA、容量、成本和调度稳定性结论。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| stability run | `scripts/run_sigma5_vendor_primary_stability.py --resource run` | 生成一条主供应商稳定性 snapshot 和 dataset 明细；默认只读，不修改路由 |
| stability smoke | `scripts/smoke_sigma5_vendor_primary_stability.py` | 验证 snapshot/dataset 可写可查；没有 applied Pi-5 时输出 `no_primary_promotion` |
| worker task | `scripts/run_lambda_worker.py --task vendor_primary_stability_monitor` | 作为 Lambda worker task 运行，Mu 可通过 `sigma5_vendor_primary_stability_1h` 定时触发 |
| snapshot 查询 | `GET /admin/vendor-primary-stability` | 查询 SLA、容量、成本、调度滞后、post-promotion 风险、稳定性角色和评分 |
| dataset 查询 | `GET /admin/vendor-primary-stability-datasets` | 查询每个 dataset 的授权状态、当前主源、promotion 状态、API 指标和阻断原因 |
| overview | `GET /admin/overview` | 展示 24h primary stability、healthy/warning/critical/no_primary、最新状态、成本和调度滞后 |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Primary Stability 和 Vendor Primary Stability Datasets |

兼容规则：

- Sigma-5 默认只读；不修改 `source_priority`、合同、授权、promotion 或 post-promotion 事实。
- 若没有 applied Pi-5 promotion 或当前 `source_priority` 未切到供应商主源，必须输出 `no_primary_promotion`，不能返回空白或 healthy。
- SLA 监控以 `api_request_audit` 为窗口事实，dataset 级缺少归因时仍保留平台级 SLA 和 dataset 级路由/授权结论。
- Worker/Mu 必须把 `critical` 映射成 failed，把 `no_primary_promotion/blocked/warning` 映射成 warning，避免生产稳定性风险被静默吞掉。

### 4.41 Tau-5 主供应商组合成本优化

Tau-5 新增 `vendor_cost_optimization_snapshot`、`vendor_route_weight_plan` 和 `vendor_budget_stress_dataset_snapshot`，把 Sigma-5 稳定性、Omicron-5 合同授权、API 用量、采购成本、预算和 quota 聚合成可审计的路由权重建议。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| optimization run | `scripts/run_tau5_vendor_cost_optimization.py --resource run` | 生成一条成本优化 snapshot、dataset route weight plan 和 budget stress 明细；默认只读，不修改路由 |
| optimization smoke | `scripts/smoke_tau5_vendor_cost_optimization.py` | 验证 optimization/plan/stress 可写可查；没有 applied Pi-5 时输出 `no_primary_promotion` |
| worker task | `scripts/run_lambda_worker.py --task vendor_cost_optimizer` | 作为 Lambda worker task 运行，Mu 可通过 `tau5_vendor_cost_optimizer_6h` 定时触发 |
| optimization 查询 | `GET /admin/vendor-cost-optimizations` | 查询成本优化状态、预算占用、quota 水位、推荐权重、整体评分和 required_actions |
| route plan 查询 | `GET /admin/vendor-route-weight-plans` | 查询每个 dataset 的 primary/backup/free 权重建议、当前主源、成本、quota、阻断原因和是否允许路由变更 |
| stress 查询 | `GET /admin/vendor-budget-stress` | 查询每个 dataset 在压力倍数下的预算、quota、recommended_action 和 required_actions |
| overview | `GET /admin/overview` | 展示 24h cost optimization、optimized/over_budget/quota_risk/no_primary、最新状态、primary weight、budget usage 和 quota usage |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Cost Optimizations、Vendor Route Weight Plans 和 Vendor Budget Stress |

兼容规则：

- Tau-5 默认只读；不修改 `source_priority`、合同、授权、promotion、post-promotion 或实际路由。
- 若没有 applied Pi-5 promotion 或当前 `source_priority` 未切到供应商主源，必须输出 `no_primary_promotion`，推荐供应商 primary weight 必须为 0。
- budget stress 只使用结构化 cost/quota/usage 事实和配置阈值，不读取或输出供应商 token、Authorization header 或原始供应商响应正文。
- Worker/Mu 必须把 `blocked/over_budget` 映射成 failed，把 `no_primary_promotion/quota_risk/watch` 映射成 warning，避免成本和 quota 风险被静默吞掉。

### 4.42 Upsilon-5 路由权重执行护栏

Upsilon-5 新增 `vendor_route_weight_execution_run`、`vendor_route_weight_execution_dataset`、`vendor_route_weight_rollout_stage` 和 `source_route_weight_policy`，把 Tau-5 权重建议变成可审批、可灰度、可回滚的控制面记录。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| execution run | `scripts/run_upsilon5_route_weight_execution.py --resource run` | 生成执行 run、dataset 执行明细和 rollout stage；默认 `review_only` 且审批 pending |
| execution smoke | `scripts/smoke_upsilon5_route_weight_execution.py` | 验证 Upsilon-5 执行审计可写可查；没有 applied Pi-5 时输出 `no_primary_promotion` 且 policy 为 0 |
| worker task | `scripts/run_lambda_worker.py --task vendor_route_weight_executor` | 作为 Lambda worker task 运行，Mu 可通过 `upsilon5_vendor_route_weight_executor_1h` 定时触发 |
| execution 查询 | `GET /admin/vendor-route-executions` | 查询执行状态、审批状态、灰度策略、目标/实际权重、阻断原因和 required_actions |
| dataset 查询 | `GET /admin/vendor-route-execution-datasets` | 查询每个 dataset 的 Tau-5 plan、当前主源、审批、target/applied 权重和 rollback 标记 |
| stage 查询 | `GET /admin/vendor-route-rollout-stages` | 查询每个 dataset 的灰度阶段、gate 状态、目标权重和是否已应用 |
| policy 查询 | `GET /admin/source-route-weight-policies` | 查询显式 apply 后写入的 active/superseded/rolled_back route weight policy |
| overview | `GET /admin/overview` | 展示 24h route execution、pending/staged/applied/blocked、最新执行/审批状态、applied weight 和 active policy 数 |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Vendor Route Executions、Vendor Route Execution Datasets、Vendor Route Rollout Stages 和 Source Route Weight Policies |

兼容规则：

- Upsilon-5 默认 `review_only`；不修改 `source_priority`、合同、授权、promotion、post-promotion、Tau-5 plan 或真实 API 读取路由。
- 只有 `execution_mode=apply` 且 `approval_status in ('approved','not_required')`，并且 Tau-5 plan 可执行时，才允许写入 `source_route_weight_policy`。
- 若没有 applied Pi-5 promotion、当前主源未切到供应商，或 Tau-5 primary weight 为 0，必须输出 `no_primary_promotion`，applied primary weight 必须为 0。
- rollback 请求必须保留 run/dataset/stage/policy 证据；未经审批只能 `rollback_recommended`，不能静默写入 active policy。
- Worker/Mu 必须把 `blocked/rollback_recommended` 映射成 failed，把 `pending_approval/review_required/no_primary_promotion/staged` 映射成 warning，避免路由执行风险被静默吞掉。

### 4.43 Phi-5 路由策略生产运行时

Phi-5 新增 `source_route_decision_audit`，把 active `source_route_weight_policy` 接入 API 和采集运行时。该阶段只读取 policy 并写入决策审计，不直接改写 `source_priority`、合同、授权或 policy 状态。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| route resolver | `qdata.phi5_route_policy.resolve_source_route` | 按 dataset、requested source、as_of_date 和 request key 读取 active policy，并用 deterministic bucket 选择候选源 |
| sync 接入 | `scripts/sync_daily_market.py --use-route-policy` | 采集路径按 selected source 拉数，失败或无数据时尝试 fallback，并返回 `route_decision` |
| API metadata | `GET /price`、`GET /matrix`、`GET /constraints` | 在 `meta.route_policy` 返回 requested/selected/final source、route mode、decision status 和 fallback 标记 |
| 决策审计 | `qmeta.source_route_decision_audit` | 记录 request context、candidate/attempt source、row_count、duration、fallback 和 error 摘要 |
| 决策查询 | `GET /admin/source-route-decisions` | 查询 API/sync/worker/smoke 路由决策，支持 source、context、mode、status、role 等过滤 |
| overview | `GET /admin/overview` | 展示 24h route decision、fallback 和 latest final source 指标 |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Source Route Decisions 表 |

兼容规则：

- 没有 PostgreSQL DSN 或没有 active policy 时，必须保持 requested source 默认路径，不改变现有 API/ingest 行为。
- active policy 只影响本次运行时 selected source；不得在 resolver、API 或 sync 中修改 policy、`source_priority`、合同或授权状态。
- selected provider 失败或无数据时允许尝试 fallback；必须记录 final source、`fallback_applied` 和 `decision_status`。
- 决策审计不得写入真实供应商 token、Authorization header、企业微信 webhook URL 或原始供应商响应正文。
- API 路由审计为 best-effort，审计失败不得破坏原有数据查询响应。

### 4.44 Chi-5 路由策略反馈闭环

Chi-5 新增 `source_route_health_snapshot`、`source_route_circuit_breaker` 和 `source_route_recovery_probe`，把 Phi-5 的真实路由决策审计接成健康反馈闭环。该阶段只读决策事实并维护独立熔断状态，不改写 `source_priority`、合同、授权或 route policy。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| feedback monitor | `scripts/run_chi5_route_feedback.py --resource check` | 聚合 `source_route_decision_audit`，生成 source+dataset 健康快照、熔断动作和恢复探测 |
| feedback smoke | `scripts/smoke_chi5_route_feedback.py` | 模拟失败开闸和健康恢复闭闸，验证 snapshot、breaker、probe 可写可查 |
| worker task | `scripts/run_lambda_worker.py --task source_route_feedback_monitor` | 作为 Lambda worker task 运行，Mu 可通过 `chi5_source_route_feedback_15m` 定时触发 |
| 路由保护 | `qdata.phi5_route_policy.resolve_source_route` | 读取 open circuit，跳过仍在 `open_until` 窗口内的候选源；所有候选都 open 时 fail-open 并记录 meta |
| 健康查询 | `GET /admin/source-route-health` | 查询成功率、失败率、fallback、空响应、延迟、熔断动作和 runbook |
| 熔断查询 | `GET /admin/source-route-circuit-breakers` | 查询 source+dataset 当前 circuit 状态、open_until、最近快照和打开原因 |
| 恢复探测查询 | `GET /admin/source-route-recovery-probes` | 查询 recovered/failed probe、观测成功率和决策摘要 |
| overview | `GET /admin/overview` | 展示 24h route health、unhealthy、latest health、open circuits、recovery probes 和 recovered probes |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Source Route Health、Source Route Circuit Breakers 和 Source Route Recovery Probes |

兼容规则：

- Chi-5 只维护独立 circuit breaker 状态；不得改写 active policy、`source_priority`、合同、授权或供应商 profile。
- 没有 Chi-5 表或查询 circuit 失败时，Phi-5 resolver 必须保持兼容路径，不能破坏原有 API/ingest 查询。
- 当 source+dataset 在 `open_until` 之前处于 open circuit 时，resolver 必须跳过该候选；若所有候选都被跳过，必须 fail-open 并在 `route_policy` meta 里记录 `circuit_fail_open=true`。
- recovery probe 只有在 open/half_open 恢复窗口里写入；恢复失败必须保持或重开 circuit，不能静默恢复。

### 4.45 Psi-5 路由故障自动处置闭环

Psi-5 新增 `source_route_incident_action`，把 Chi-5 的 route health、circuit breaker 和 recovery probe 信号接入自动化动作。该阶段只生成审计化处置动作和低风险跟进；高风险降权类动作必须进入审批状态，不直接改写 `source_priority`、合同、授权或 route policy。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| route incident automation | `scripts/run_psi5_route_incident_automation.py --resource run` | 从 Chi-5 route 信号生成 Psi automation action 和 source route incident action |
| route incident smoke | `scripts/smoke_psi5_route_incident_automation.py` | 模拟失败开闸、审批动作、恢复探测和恢复动作 |
| worker task | `scripts/run_lambda_worker.py --task route_incident_automation` | 作为 Lambda worker task 运行，Mu 可通过 `psi5_route_incident_automation_15m` 定时触发 |
| 处置动作查询 | `GET /admin/source-route-incident-actions` | 查询 incident action、source signal、automation action、审批状态、owner、路由状态和健康指标 |
| overview | `GET /admin/overview` | 展示 24h route incident action 数、pending action 数和 latest incident action status |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Source Route Incident Actions |

兼容规则：

- `circuit_open` 只能生成 approval-required 高风险动作；未经审批不得自动改写实际权重、`source_priority` 或供应商角色。
- `recovered` 默认只生成低风险监控动作；重复恢复信号必须通过 idempotency 避免重复执行。
- route incident action 必须保留 dataset/source、breaker/snapshot/probe、health_issues、planned_effect、executed_effect 和 rollback_hint，便于人工复核和回滚。
- dry-run 不得写入 automation action 或 route incident action。

### 4.46 Omega-5 路由故障真实审批与通知闭环

Omega-5 新增 `source_route_incident_control`，把 Psi-5 route incident action 接入 Omega approval、Delta-2 企业微信回执、dispatch 审计、Omega execution attempt 和 rollback plan。默认不向外部企业微信发送消息，只有显式允许外发时才会调用真实 webhook。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| route incident control | `scripts/run_omega5_route_incident_control.py --resource run` | 从 Psi-5 route incident action 生成审批、通知、执行和回滚控制记录 |
| route incident control smoke | `scripts/smoke_omega5_route_incident_control.py` | 模拟 route 故障动作，验证 pending approval、企业微信 receipt、rollback、auto approval 和 execution attempt |
| worker task | `scripts/run_lambda_worker.py --task route_incident_control` | 作为 Lambda worker task 运行，Mu 可通过 `omega5_route_incident_control_15m` 定时触发 |
| 控制闭环查询 | `GET /admin/source-route-incident-controls` | 查询 control、incident action、approval、dispatch、receipt、attempt、rollback 和阶段状态 |
| overview | `GET /admin/overview` | 展示 24h route incident control 数、pending control 数和 latest control stage |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Source Route Incident Controls |

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `control_code` | string | 空 | 精确过滤控制记录 |
| `incident_action_code` | string | 空 | 精确过滤 Psi-5 incident action |
| `action_code` | string | 空 | 精确过滤 automation action |
| `dataset_code` | string | 空 | 精确过滤数据集 |
| `source_code` | string | 空 | 精确过滤数据源 |
| `source_signal_type` | enum | 空 | `circuit_open/recovery_failed/recovered/health_degraded` |
| `control_stage` | enum | 空 | `planned/approval_requested/notification_recorded/approved/executed/rollback_planned/closed/blocked/failed/skipped` |
| `approval_status` | enum | 空 | `pending/approved/rejected/expired/cancelled` |
| `dispatch_status` | enum | 空 | `planned/sent/acknowledged/failed/retry_scheduled/dead_letter/recovered/suppressed` |
| `receipt_status` | enum | 空 | `planned/success/failed/blocked/skipped` |
| `attempt_status` | enum | 空 | `queued/running/success/failed/skipped/approval_required/retry_scheduled` |
| `rollback_status` | enum | 空 | `planned/success/failed/skipped` |
| `limit/offset` | integer | `100/0` | 分页 |

响应字段兼容规则：

- 新增字段只追加，不删除 Psi-5、Omega、Delta-2 既有字段。
- `receipt_status=blocked` 表示外发被显式禁用或缺少真实 webhook，不代表控制闭环失败。
- `dispatch_status=acknowledged` 在默认本机模式下表示通知审计已记录，不代表真实企业微信已送达。
- `execution_mode=review_only` 不执行外部动作；`execute` 也默认只使用 Omega noop executor，真实外部执行仍需 Omega allow_external 护栏。

错误/失败条件：

- 缺少 `source_route_incident_control` 或 `/admin/source-route-incident-controls` 不可查，Omega-5 不通过。
- 高风险 action 未进入 approval，或 pending/rejected 时仍能执行，Omega-5 不通过。
- 未显式 `--allow-wecom-external` 却向企业微信外发，Omega-5 不通过。
- 控制记录缺少 approval/dispatch/receipt/attempt/rollback 任一可追溯引用时，不能声明完整闭环。

### 4.47 Alpha-6 路由故障控制健康运维层

Alpha-6 新增 `source_route_incident_control_health_snapshot`，把 Omega-5 route incident control 的审批 SLA、控制积压、企业微信回执、执行失败率、回滚计划和 Mu 调度陈旧度沉淀为健康快照与 runbook。它不直接审批、执行、通知或回滚，只写健康证据。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| route control health check | `scripts/run_alpha6_route_incident_control_health.py --resource check` | 读取 Omega-5 控制闭环证据并写入健康快照 |
| route control health smoke | `scripts/smoke_alpha6_route_incident_control_health.py` | 复用 Omega-5 smoke 造控制证据，验证 Alpha-6 snapshot、status 和 runbook |
| worker task | `scripts/run_lambda_worker.py --task route_incident_control_health` | 作为 Lambda worker task 运行，Mu 可通过 `alpha6_route_incident_control_health_15m` 定时触发 |
| 健康快照查询 | `GET /admin/source-route-incident-control-health` | 查询 Alpha-6 control health snapshot、issues、runbook 和证据 |
| overview | `GET /admin/overview` | 展示 latest control health status、issue_count、overdue approval 和 blocked receipt |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Source Route Incident Control Health |

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `snapshot_code` | string | 空 | 精确过滤健康快照 |
| `status` | enum | 空 | `healthy/warning/critical/failed/skipped` |
| `requested_by` | string | 空 | 精确过滤发起人 |
| `trigger_mode` | enum | 空 | `manual/scheduled/once/smoke/api` |
| `environment` | string | 空 | 精确过滤环境 |
| `schedule_code` | string | 空 | 默认 `omega5_route_incident_control_15m` |
| `start_date/end_date` | date | 空 | 按 `as_of_at` 日期过滤 |
| `limit/offset` | integer | `100/0` | 分页 |

响应字段兼容规则：

- `receipt_status=blocked` 在本机缺少真实 webhook 时只升级为 warning，不直接判为 critical。
- `approval_overdue_count>0`、`execution_failure_rate` 超阈值、`missing_rollback_count>0` 或 schedule stale 才进入 critical。
- health snapshot 只追加字段，不删除 Omega-5 control、Psi-5 action、Delta-2 receipt 或 Mu worker/schedule 字段。

错误/失败条件：

- 缺少 `source_route_incident_control_health_snapshot` 或 `/admin/source-route-incident-control-health` 不可查，Alpha-6 不通过。
- Alpha-6 health 未能识别 overdue approval、执行失败率过高、缺回滚或 stale schedule，Alpha-6 不通过。
- Alpha-6 health check 产生真实企业微信外发、审批、执行或回滚副作用，Alpha-6 不通过。

### 4.48 Beta-6 路由故障控制操作队列

Beta-6 新增 `source_route_incident_operation_batch` 和 `source_route_incident_operation_item`，把 Alpha-6 发现的控制健康问题推进到可运营队列：批量 approve/reject/hold、通知降噪摘要、全市场 route incident 压测计划和 Kappa/Upsilon 操作台可观测。默认不外发通知、不执行真实路由变更；只有显式 `apply_decisions=true` 才会通过 Omega approval 控制面改写审批状态。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| operation queue run | `scripts/run_beta6_route_incident_operations.py --resource run` | 读取 Omega-5 pending controls，生成 Beta-6 batch/item、降噪摘要和压测证据 |
| operation smoke | `scripts/smoke_beta6_route_incident_operations.py` | 造 pending route control，再用 Beta-6 批量 approve 并校验 batch/item |
| worker task | `scripts/run_lambda_worker.py --task route_incident_operations` | 作为 Lambda worker task 运行，Mu 可通过 `beta6_route_incident_operations_30m` 定时触发 |
| 操作批次查询 | `GET /admin/source-route-incident-operation-batches` | 查询 batch 状态、候选数、审批数、降噪数和压测场景数 |
| 操作明细查询 | `GET /admin/source-route-incident-operation-items` | 查询每个 control 的 approval 前后状态、操作结果和 notification group |
| 控制台展示 | `GET /admin/console` | Vendor tab 展示 Source Route Incident Operation Batches/Items |

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `batch_code` | string | 空 | 精确过滤操作批次或明细 |
| `status` | enum | 空 | batch 状态：`planned/success/warning/failed/skipped` |
| `operation_mode` | enum | 空 | `approval_queue/batch_approval/pressure_test/smoke` |
| `approval_decision` | enum | 空 | batch 决策：`approve/reject/hold` |
| `operation_decision` | enum | 空 | item 决策：`approve/reject/hold/skip` |
| `operation_status` | enum | 空 | item 状态：`preview/applied/skipped/failed` |
| `notification_policy` | enum | 空 | `dedupe_digest/critical_only/none` |
| `stress_scope` | enum | 空 | `full_market/active_sources/smoke` |
| `control_code/approval_code` | string | 空 | 精确过滤明细 |
| `dataset_code/source_code/source_signal_type/safety_level` | string | 空 | 精确过滤明细 |
| `requested_by/trigger_mode/environment` | string | 空 | 精确过滤批次 |
| `start_date/end_date` | date | 空 | 按 batch `started_at` 或 item `created_at` 日期过滤 |
| `limit/offset` | integer | `100/0` | 分页 |

响应字段兼容规则：

- `dry_run=true` 或 `apply_decisions=false` 时只生成预览/队列证据，不改写 Omega approval。
- `notification_policy=dedupe_digest` 只记录分组和 suppressed 证据，不向企业微信外发；真实外发仍需独立 Delta-2 webhook 配置和显式允许。
- `stress_scope=full_market` 输出压测场景计数和 capped 证据，不直接制造全市场故障或改写 route policy。
- Beta-6 batch/item 只追加字段，不删除 Omega-5 control、Alpha-6 health 或 Kappa 既有字段。

错误/失败条件：

- 缺少 `source_route_incident_operation_batch`、`source_route_incident_operation_item` 或两个 Kappa endpoint 不可查，Beta-6 不通过。
- 批量 approve/reject 绕过 Omega approval 控制面直接改 action 状态，Beta-6 不通过。
- dry-run、hold 或未显式 apply 时改变审批状态、外发企业微信或执行真实路由变更，Beta-6 不通过。
- Upsilon 未展示 Operation Batches/Items，或 smoke 无法复现 pending control 到 approved item，Beta-6 不通过。

### 4.49 Gamma-6 路由故障可写审批 API

Gamma-6 新增可写审批 API 和 Upsilon 操作按钮，把 Beta-6 的 pending queue 转成可签批控制面。所有 approve/reject 最终仍通过 Omega approval 控制面，Gamma-6 只负责 command/item/signature 审计、quorum 判断、幂等重放和操作台交互。默认不执行真实路由变更，不外发企业微信；`notify_wecom=true` 只记录交互式确认 preview。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| writable approval command | `POST /admin/source-route-incident-approval-commands` | 提交 approve/reject/hold，目标为 control/approval/batch 三选一 |
| command query | `GET /admin/source-route-incident-approval-commands` | 查询 command status、quorum_status、target/applied/held/rejected/skipped/failed 计数 |
| item query | `GET /admin/source-route-incident-approval-command-items` | 查询每个 control 的审批前后状态、签名数和错误 |
| signature query | `GET /admin/source-route-incident-approval-signatures` | 查询 signer、decision、idempotency_key 和 signed_at |
| 控制台按钮 | `GET /admin/console` | Source Route Incident Operation Items 行内提供 Approve/Reject/Hold 按钮 |
| smoke | `scripts/smoke_gamma6_route_incident_approval_api.py` | 通过真实 HTTP POST 验证 pending quorum、第二审批人 applied 和幂等重放 |

POST JSON body：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `decision` | enum | 是 | `approve/reject/hold` |
| `control_code/approval_code/batch_code` | string | 三选一 | 精确控制单个 control、单个 approval 或 Beta-6 batch |
| `requested_by` | string | 否 | 操作发起人；默认取 token owner/name |
| `principal_code` | string | 否 | 签批人；默认取 `requested_by` |
| `required_approvals` | integer | 否 | `1..5`，大于已签名人数时返回 `pending_quorum` |
| `idempotency_key` | string | 否 | 重试幂等键；过长会稳定 hash，不影响重放识别 |
| `notify_wecom` | boolean | 否 | 只记录 WeCom interactive preview，不外发 |
| `allow_wecom_external` | boolean | 否 | 预留字段；当前 smoke/默认不产生外部副作用 |

失败条件：

- POST 未要求 admin scope，或无 bearer token 也能写入，Gamma-6 不通过。
- 同一个 `idempotency_key` 重放产生新 command/signature，Gamma-6 不通过。
- `required_approvals=2` 时第一签就改写 Omega approval，Gamma-6 不通过。
- approve/reject 未通过 `decide_automation_approval`，或直接改写 action/route policy，Gamma-6 不通过。
- Upsilon 无法展示 Approval Commands/Items/Signatures 或行级 Approve/Reject/Hold 按钮，Gamma-6 不通过。

### 4.50 Delta-6 路由故障审批治理层

Delta-6 在 Gamma-6 之前增加生产级治理闸门。企业微信回调不走 Bearer token，而是通过 HMAC 签名、nonce 防重放、时间戳偏移、RBAC、职责分离和策略 quorum 判断；治理通过后才调用 Gamma-6 `submit_route_incident_approval_command`，最终仍由 Omega approval 控制面落地。Epsilon-6 接入后，同一个回调入口会先执行 advisory lock 和状态机守卫，再进入 Delta-6。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| signed WeCom callback | `POST /webhooks/wecom/source-route-incident-approval-callbacks` | 生产回调入口，无 Bearer token；必须验签、校验 nonce 和治理策略 |
| admin callback | `POST /admin/source-route-incident-approval-wecom-callbacks` | 管理补录/联调用入口，要求 admin Bearer，并复用同一套 HMAC 和治理规则 |
| role binding query | `GET /admin/source-route-incident-approval-role-bindings` | 查询 route approver、risk admin、requester、audit viewer 角色绑定 |
| policy query | `GET /admin/source-route-incident-approval-policies` | 查询 min approvals、职责分离、高风险风控审批、签名、超时、replay 策略 |
| callback query | `GET /admin/source-route-incident-approval-callbacks` | 查询签名状态、治理状态、Gamma command、脱敏 payload 和 response evidence |
| escalation query | `GET /admin/source-route-incident-approval-escalations` | 查询 timeout、quorum stalled、policy denied、missing binding、invalid signature、replay、cancel 升级 |
| smoke | `scripts/smoke_delta6_route_incident_approval_governance.py` | 真实 HTTP callback 验证 denied、pending quorum、timeout escalation、replay rejected 和 applied |

签名请求头：

| Header | 必填 | 说明 |
|---|---|---|
| `X-QData-Timestamp` | 是 | Unix 秒级时间戳；默认允许 300 秒时钟偏移 |
| `X-QData-Nonce` | 是 | provider 内唯一 nonce；重复 nonce 必须返回 `replay_rejected` |
| `X-QData-Signature` | 是 | `sha256=<hex_hmac>` |

签名串固定为 `timestamp + "\n" + nonce + "\n" + raw_body`，HMAC-SHA256 密钥只从 `QDATA_DELTA6_WECOM_CALLBACK_SECRET` 读取，不写入数据库、Kappa API、CLI 或 Upsilon HTML。

POST JSON body：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `provider_code` | string | 否 | 默认 `wecom` |
| `decision` | enum | 是 | `approve/reject/hold` |
| `control_code/approval_code/batch_code` | string | 三选一 | 精确控制单个 control、approval 或批次 |
| `signer_code` / `principal_code` | string | 是 | 实际签批人；必须匹配有效角色绑定 |
| `requested_by` | string | 否 | 原请求人；策略开启职责分离时不得与 signer 相同 |
| `required_approvals` | integer | 否 | 可覆盖默认策略，但不得低于策略的 `min_approvals` |
| `idempotency_key` | string | 否 | 传给 Gamma-6 的幂等键 |
| `trigger_mode` | enum | 否 | `api/manual/smoke`；默认 `api` |

失败条件：

- 回调未验签、签名错误、时间戳偏移过大或 nonce 重放仍能进入 Gamma-6，Delta-6 不通过。
- 签批人没有 scoped `route_approver`/`route_risk_admin` 角色，或高风险策略要求风控管理员却普通审批人可通过，Delta-6 不通过。
- 开启职责分离时 requester 可以自批，Delta-6 不通过。
- 超时、quorum 卡住、策略拒绝、缺角色、无效签名、replay 或撤销未写入 escalation 审计，Delta-6 不通过。
- Kappa/Upsilon 无法查询或展示 role bindings、policies、callbacks、escalations，Delta-6 不通过。

### 4.51 Epsilon-6 路由故障审批韧性层

Epsilon-6 在 Delta-6 外层增加高并发一致性、状态机守卫、不可变审计哈希链、SLA planned action 和恢复演练。它不保存密钥、不外发消息、不绕过 Delta-6/Gamma-6/Omega；它只负责在审批写入前后留下可验证证据，并阻止终态审批被 stale callback 改写。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| resilient signed callback | `POST /webhooks/wecom/source-route-incident-approval-callbacks` | 生产回调入口先拿 advisory lock、校验目标状态，再进入 Delta-6 HMAC/RBAC/quorum |
| resilient admin callback | `POST /admin/source-route-incident-approval-wecom-callbacks` | 管理补录入口要求 admin Bearer，同样经过 Epsilon-6 lock/state/audit |
| lock event query | `GET /admin/source-route-incident-approval-lock-events` | 查询 acquired/busy/released、lock_scope、nonce、request_hash、held_ms |
| state transition query | `GET /admin/source-route-incident-approval-state-transitions` | 查询 approval/control 前后状态、terminal guard、Delta-6 outcome |
| audit chain query | `GET /admin/source-route-incident-approval-audit-chain` | 查询 chain_scope、sequence_no、previous_hash、payload_hash、entry_hash |
| SLA action query | `GET /admin/source-route-incident-approval-sla-actions` | 查询从 open escalation 生成的 planned action，默认不外发 |
| recovery drill query | `GET /admin/source-route-incident-approval-recovery-drills` | 查询 DB reconnect、hash chain verify、lock key 和状态机恢复演练 |
| worker task | `scripts/run_lambda_worker.py --task route_incident_approval_resilience` | 作为 Lambda worker task 运行，Mu 可通过 `epsilon6_route_incident_approval_resilience_15m` 定时触发 |
| smoke | `scripts/smoke_epsilon6_route_incident_approval_resilience.py` | 真实 HTTP callback 验证 pending quorum、SLA action、recovery drill、applied、terminal block 和 audit chain |

失败条件：

- 同一 approval target 的并发回调没有 advisory lock 证据，或 lock busy 时仍进入 Delta-6/Gamma-6，Epsilon-6 不通过。
- 已 approved/rejected/cancelled/expired 的终态 target 仍能被后续 callback 改写，Epsilon-6 不通过。
- callback、state transition、SLA action 或 recovery drill 缺少 audit hash，或 hash chain 校验不出篡改，Epsilon-6 不通过。
- 超时 open escalation 没有生成 SLA planned action，或 SLA 自动处置产生真实外部副作用，Epsilon-6 不通过。
- recovery drill 不能验证 DB reconnect、hash chain、lock key 和状态机终态守卫，Epsilon-6 不通过。
- Kappa/Upsilon 无法查询或展示 lock events、state transitions、audit chain、SLA actions、recovery drills，Epsilon-6 不通过。
- `epsilon6_route_incident_approval_resilience_15m` 已初始化但 Lambda worker 无法执行 `route_incident_approval_resilience`，Epsilon-6 不通过。

### 4.52 Zeta-6 路由故障审批发布闸门

Zeta-6 在 Epsilon-6 外层增加跨环境发布 preflight、current/next callback secret 轮换、并发压测摘要和监管审计导出包。它不保存密钥原文；回调响应、Kappa API、Upsilon HTML 和 CLI 只能暴露 secret label、digest tail、request hash 等可审计摘要。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| rotating signed callback | `POST /webhooks/wecom/source-route-incident-approval-callbacks` | 先尝试 current，再尝试 `QDATA_ZETA6_WECOM_CALLBACK_SECRET_NEXT`；命中 next 时用 next secret 交给 Epsilon-6/Delta-6 复验 |
| release preflight query | `GET /admin/source-route-incident-approval-release-preflights` | 查询 DB/audit/recovery/schedule/secret 发布检查 |
| secret rotation query | `GET /admin/source-route-incident-approval-secret-rotations` | 查询 current/next label 命中、nonce、request_hash、signature_digest |
| concurrency test query | `GET /admin/source-route-incident-approval-concurrency-tests` | 查询高并发或 replay storm 压测摘要 |
| audit export query | `GET /admin/source-route-incident-approval-audit-exports` | 查询监管审计导出包、package hash 和 broken hash count |
| worker task | `scripts/run_lambda_worker.py --task route_incident_approval_release` | 作为 Lambda worker task 运行，Mu 可通过 `zeta6_route_incident_approval_release_30m` 定时触发 |
| smoke | `scripts/smoke_zeta6_route_incident_approval_release.py` | 验证 preflight、secret rotation evidence、concurrency summary 和 audit export |

失败条件：

- current/next 密钥轮换把密钥原文写入数据库、CLI、Kappa API、Upsilon HTML 或回调响应，Zeta-6 不通过。
- 用 next secret 签名的回调不能被识别并交给 Epsilon-6/Delta-6 复验，Zeta-6 不通过。
- 发布前没有 DB reconnect、audit chain、recovery drill、worker schedule 和 secret 配置检查，Zeta-6 不通过。
- audit export 缺少 package hash、broken hash count 或无法追溯 Epsilon-6 audit hash，Zeta-6 不通过。
- `zeta6_route_incident_approval_release_30m` 已初始化但 Lambda worker/Mu 无法执行 `route_incident_approval_release`，Zeta-6 不通过。

### 4.53 Eta-6 真实供应商生产主源闭环

Eta-6 把 Omicron-5 合同/entitlement、Theta-3 live pilot、Pi-5 promotion、Sigma-5 稳定性、Tau-5 成本和 Upsilon-5 路由执行串成生产主源闭环。默认是 review-only，缺少真实 `QDATA_VENDOR_BASE_URL` 或 `QDATA_VENDOR_TOKEN` 时必须 blocked；数据库、CLI、Kappa API 和 Upsilon 只允许展示 token digest/tail 或脱敏配置。

| 能力 | 当前入口 | 说明 |
|---|---|---|
| production closure run | `scripts/run_eta6_vendor_production_source.py --resource run` | 生成 run、dataset check 和 decision 审计；默认要求真实 vendor env，但不调用外部供应商 |
| production run query | `GET /admin/vendor-production-source-runs` | 查询生产闭环总状态、角色、dataset 计数、ready/blocked 数、live env 是否存在和生产评分 |
| dataset check query | `GET /admin/vendor-production-source-dataset-checks` | 查询每个 dataset 的合同、entitlement、pilot、promotion、稳定性、成本和路由执行证据 |
| decision query | `GET /admin/vendor-production-source-decisions` | 查询每个 gate 的 passed/warning/blocked、severity、required_actions 和审计摘要 |
| worker task | `scripts/run_lambda_worker.py --task vendor_production_source_closure` | 作为 Lambda worker task 运行，Mu 可通过 `eta6_vendor_production_source_closure_30m` 定时触发 |
| smoke | `scripts/smoke_eta6_vendor_production_source.py` | 在无真实供应商 env 的本机环境必须输出 blocked，并证明 token 明文没有落入输出 |

失败条件：

- 缺少真实 vendor env 时 Eta-6 返回 production_ready/monitoring，Eta-6 不通过。
- 数据库、CLI、Kappa API 或 Upsilon 输出 `QDATA_VENDOR_TOKEN` 原文、Authorization header 或原始供应商响应正文，Eta-6 不通过。
- 缺少 Omicron-5 合同/entitlement、Theta-3 full-market pilot、Pi-5 promotion、Sigma-5 稳定性、Tau-5 成本或 Upsilon-5 路由执行任一必要证据却给出 primary/production_ready，Eta-6 不通过。
- `eta6_vendor_production_source_closure_30m` 已初始化但 Lambda worker/Mu 无法执行 `vendor_production_source_closure`，Eta-6 不通过。
- Kappa/Upsilon 无法查询或展示 production source runs、dataset checks、decisions 三张表，Eta-6 不通过。

### 4.54 目标 v1 接口清单

| 接口 | Method | URL | 权限 | 说明 |
|---|---|---|---|---|
| 获取证券主数据 | POST | `/securities/query` | `data:master:read` | 查询证券基础信息 |
| 获取交易日历 | GET | `/calendar` | `data:calendar:read` | 查询交易日历 |
| 获取行情 | POST | `/market/price` | `data:market:read` | 日线和分钟线 |
| 获取复权因子 | POST | `/market/adjustment-factor` | `data:market:read` | 复权因子 |
| 获取交易约束 | POST | `/market/trading-constraints` | `data:market:read` | 停牌、涨跌停、ST |
| 获取 PIT 基本面 | POST | `/fundamentals/asof` | `data:fundamental:read` | 财务和指标 |
| 获取指数成分 | POST | `/index/members/asof` | `data:index:read` | 历史指数成分 |
| 获取行业分类 | POST | `/industry/asof` | `data:industry:read` | 历史行业归属 |
| 获取股票池 | POST | `/universe/query` | `data:universe:read` | 指数或规则股票池 |
| 获取因子值 | POST | `/factors/values` | `data:factor:read` | 因子数据 |
| 获取数据版本 | GET | `/datasets/versions` | `data:meta:read` | 查询数据版本 |
| 获取数据健康状态 | GET | `/datasets/{dataset_code}/health` | `data:quality:read` | 数据质量 |

## 5. 接口详情

### 5.1 获取证券主数据

```http
POST /v1/securities/query
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `symbols` | array[string] | 否 | `null` | 标准证券代码列表 |
| `security_ids` | array[integer] | 否 | `null` | 内部证券 ID 列表 |
| `asset_types` | array[string] | 否 | `["stock"]` | 资产类型 |
| `exchanges` | array[string] | 否 | `["SH", "SZ", "BJ"]` | 交易所 |
| `asof_date` | string | 否 | 当前日期 | 历史时点 |
| `include_delisted` | boolean | 否 | `false` | 是否包含退市证券 |
| `fields` | array[string] | 否 | 默认字段 | 返回字段 |

请求示例：

```json
{
  "symbols": ["600519.SH", "000001.SZ"],
  "asof_date": "2024-12-31",
  "fields": ["security_id", "symbol", "name", "list_date", "status"]
}
```

响应示例：

```json
{
  "request_id": "req_001",
  "status": "success",
  "data": {
    "columns": ["security_id", "symbol", "name", "list_date", "status"],
    "rows": [
      [1000001, "600519.SH", "贵州茅台", "2001-08-27", "active"],
      [1000002, "000001.SZ", "平安银行", "1991-04-03", "active"]
    ]
  },
  "meta": {
    "query_mode": "asof",
    "row_count": 2,
    "data_versions": ["security_master:202607230001"]
  },
  "errors": []
}
```

### 5.2 获取交易日历

```http
GET /v1/calendar
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `exchange` | string | 是 | 无 | 交易所 |
| `start_date` | string | 是 | 无 | 开始日期 |
| `end_date` | string | 是 | 无 | 结束日期 |
| `open_only` | boolean | 否 | `true` | 是否只返回开市日 |

请求示例：

```text
GET /v1/calendar?exchange=SH&start_date=2026-07-01&end_date=2026-07-31&open_only=true
```

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `exchange` | string | 交易所 |
| `trade_date` | string | 日期 |
| `is_open` | boolean | 是否开市 |
| `pretrade_date` | string | 前一交易日 |
| `next_trade_date` | string | 后一交易日 |

### 5.3 获取行情

```http
POST /v1/market/price
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `symbols` | array[string] | 条件必填 | 无 | 证券代码 |
| `security_ids` | array[integer] | 条件必填 | 无 | 内部证券 ID |
| `universe` | string | 否 | `null` | 股票池代码 |
| `start_date` | string | 是 | 无 | 开始日期 |
| `end_date` | string | 是 | 无 | 结束日期 |
| `frequency` | string | 否 | `1d` | `1d` 或 `1m` |
| `adjust` | string | 否 | `none` | `none`、`forward`、`backward` |
| `fields` | array[string] | 否 | 默认字段 | 行情字段 |
| `query_mode` | string | 否 | `latest` | `latest`、`asof`、`vintage` |
| `asof_time` | string | 否 | `null` | asof 模式使用 |
| `data_version` | string | 否 | `null` | vintage 模式使用 |
| `limit` | integer | 否 | `100000` | 返回行数限制 |
| `cursor` | string | 否 | `null` | 分页游标 |

请求示例：

```json
{
  "symbols": ["600519.SH", "000001.SZ"],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "frequency": "1d",
  "adjust": "forward",
  "fields": ["open", "high", "low", "close", "volume", "amount"]
}
```

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | string | 标准代码 |
| `security_id` | integer | 内部 ID |
| `trade_date` | string | 交易日 |
| `bar_time` | string | 分钟线时间，日线为空 |
| `open` | number | 开盘价 |
| `high` | number | 最高价 |
| `low` | number | 最低价 |
| `close` | number | 收盘价 |
| `volume` | number | 成交量 |
| `amount` | number | 成交额 |

兼容说明：

- 默认返回长表。
- 后续可增加 `format=wide`，但不改变默认响应。
- `adjust=forward/backward` 只调整价格字段，不调整成交量和成交额。
- 范围查询先解析覆盖日期内的稳定 `security_id`，再按每个 `trade_date` 的历史
  identifier 返回 `symbol`，不会用区间结束日的 current symbol 回填全段。
- 同一请求 ticker 在范围内被回收给多个 `security_id` 时会 fail closed；调用者须
  使用 `security_ids` 消除歧义。某日缺失或重复历史 identifier 也不会回退到 current。

### 5.4 获取复权因子

```http
POST /v1/market/adjustment-factor
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `symbols` | array[string] | 条件必填 | 无 | 证券代码 |
| `security_ids` | array[integer] | 条件必填 | 无 | 内部证券 ID |
| `start_date` | string | 是 | 无 | 开始日期 |
| `end_date` | string | 是 | 无 | 结束日期 |
| `factor_type` | string | 否 | `both` | `forward`、`backward`、`both` |
| `query_mode` | string | 否 | `latest` | 查询模式 |

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | string | 标准代码 |
| `trade_date` | string | 交易日 |
| `factor_forward` | number | 前复权因子 |
| `factor_backward` | number | 后复权因子 |
| `ex_right_type` | string | 除权除息类型 |

公开复权因子接口当前只支持 `latest`。SQL selector 仅接纳与
`adjustment_factor` dataset 精确绑定、批次 `success` 且已完成、版本状态为
`active`/`superseded` 的行；orphan、running、failed 或 `recalled` 版本不可见。
范围结果与行情一致，按每个交易日标注历史 ticker；`asof`/`vintage` 因当前签名
不能完整表达 cutoff/version 而 fail closed。

### 5.5 获取交易约束

```http
POST /v1/market/trading-constraints
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `symbols` | array[string] | 条件必填 | 无 | 证券代码 |
| `universe` | string | 否 | `null` | 股票池 |
| `start_date` | string | 是 | 无 | 开始日期 |
| `end_date` | string | 是 | 无 | 结束日期 |
| `fields` | array[string] | 否 | 默认字段 | 约束字段 |

默认字段：

- `is_suspended`
- `is_st`
- `limit_up`
- `limit_down`
- `can_buy`
- `can_sell`
- `list_days`
- `is_delisting_period`

选择规则：涨跌停与停牌 episode 分别按 natural key 先应用成功、已完成批次和
逐日上海时区 knowledge cutoff，再选择确定性最新 revision；二者的日期并集构成
返回 spine，因此 suspension-only 记录不会因缺少涨跌停行而消失。`is_st`
来自当日 PIT security status（含 `star_st`），不会把缺少 limit-price 行误写为
`false`。`is_new_listing`、`list_days`、退市整理期等没有证据时保持 unknown；依赖
这些字段的股票池过滤和 `can_buy`/`can_sell` 会 fail closed。

响应示例：

```json
{
  "request_id": "req_002",
  "status": "success",
  "data": {
    "columns": ["symbol", "trade_date", "is_suspended", "is_st", "limit_up", "limit_down", "can_buy", "can_sell"],
    "rows": [
      ["600519.SH", "2026-07-23", false, false, 1856.93, 1519.31, true, true]
    ]
  },
  "meta": {
    "row_count": 1,
    "data_versions": ["limit_price_daily:202607230001"]
  },
  "errors": []
}
```

### 5.6 获取 PIT 基本面

```http
POST /v1/fundamentals/asof
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `symbols` | array[string] | 条件必填 | 无 | 证券代码 |
| `security_ids` | array[integer] | 条件必填 | 无 | 内部证券 ID |
| `fields` | array[string] | 是 | 无 | 财务字段或指标 |
| `asof_date` | string | 是 | 无 | 历史可见日期 |
| `report_period` | string | 否 | `latest_available` | 指定报告期 |
| `period_type` | string | 否 | `ttm` | `single_quarter`、`ytd`、`ttm`、`annual` |
| `statement_type` | string | 否 | `auto` | 报表类型 |
| `include_revision_info` | boolean | 否 | `true` | 是否返回版本信息 |

请求示例：

```json
{
  "symbols": ["600519.SH"],
  "fields": ["revenue", "net_profit_parent", "roe_ttm"],
  "asof_date": "2021-06-30",
  "period_type": "ttm"
}
```

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | string | 标准代码 |
| `asof_date` | string | 查询时点 |
| `report_period` | string | 返回数据对应报告期 |
| `field_name` | string | 字段名 |
| `field_value` | number | 字段值 |
| `announce_time` | string | 披露时间 |
| `ingest_time` | string | 入库时间 |
| `revision_id` | integer | 修订版本 |
| `is_restated` | boolean | 是否重述 |

PIT 规则：

- `announce_time`、`ingest_time` 必须早于 `asof_date` 次日
  `00:00 Asia/Shanghai`，且只读取成功、已完成批次。
- revision winner 按 natural key 在可见记录中确定性选择；不读取 current master
  来替代历史身份或状态。
- 严格盘中回测应使用 `asof_time`，后续版本支持。

### 5.7 获取指数成分

```http
POST /v1/index/members/asof
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `index_code` | string | 是 | 无 | 指数代码 |
| `asof_date` | string | 是 | 无 | 查询日期 |
| `fields` | array[string] | 否 | 默认字段 | 返回字段 |
| `include_weight` | boolean | 否 | `true` | 是否返回权重 |

请求示例：

```json
{
  "index_code": "000300.SH",
  "asof_date": "2024-06-28",
  "include_weight": true
}
```

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `index_code` | string | 指数代码 |
| `symbol` | string | 成分股代码 |
| `effective_date` | string | 生效日期 |
| `end_date` | string | 结束日期 |
| `weight` | number | 权重 |

指数选择器先按 natural key 在成功、已完成批次和上海时区 knowledge cutoff 内选择
确定性 revision，再按成分实体保留截至 `asof_date` 的最新 effective episode，避免
重叠 episode 返回同一证券多行。

### 5.8 获取行业分类

```http
POST /v1/industry/asof
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `symbols` | array[string] | 条件必填 | 无 | 证券代码 |
| `universe` | string | 否 | `null` | 股票池 |
| `industry_system` | string | 是 | 无 | `sw` 或 `citic` |
| `level` | integer | 否 | `1` | 行业级别 |
| `asof_date` | string | 是 | 无 | 查询日期 |

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | string | 证券代码 |
| `industry_system` | string | 行业体系 |
| `level` | integer | 行业级别 |
| `industry_code` | string | 行业代码 |
| `industry_name` | string | 行业名称 |
| `effective_date` | string | 生效日期 |

行业归属和代码/名称均来自带 `batch_id`、`announce_time`、`ingest_time` 与
`revision_id` 的历史行；选择器先限制成功、已完成批次和上海时区 knowledge
cutoff，按 natural key 选 revision，再按证券保留最新 effective episode，不读取
current category label。

### 5.9 获取股票池

```http
POST /v1/universe/query
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `universe` | string | 是 | 无 | 股票池代码 |
| `asof_date` | string | 是 | 无 | 查询日期 |
| `filters` | object | 否 | `{}` | 过滤条件 |
| `include_weight` | boolean | 否 | `false` | 是否返回权重 |

过滤条件：

| 字段 | 类型 | 说明 |
|---|---|---|
| `exclude_st` | boolean | 是否排除 ST |
| `exclude_suspended` | boolean | 是否排除停牌 |
| `min_list_days` | integer | 最短上市天数 |
| `exclude_delisting_period` | boolean | 是否排除退市整理 |

请求示例：

```json
{
  "universe": "zz800",
  "asof_date": "2024-12-31",
  "filters": {
    "exclude_st": true,
    "exclude_suspended": true,
    "min_list_days": 120
  }
}
```

非规则股票池使用同样的成功批次、knowledge cutoff、revision 与最新 effective
episode 规则。snapshot 型 producer 每次写入完整当日集合，因此空快照能清空旧
集合；同日重跑追加单调 revision，不覆盖旧行。`universe_type` 一经创建不可原地
修改，避免历史查询被重新解释。

### 5.10 获取因子值

```http
POST /v1/factors/values
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `factors` | array[string] | 是 | 无 | 因子代码 |
| `symbols` | array[string] | 否 | `null` | 证券代码 |
| `universe` | string | 否 | `null` | 股票池 |
| `start_date` | string | 是 | 无 | 开始日期 |
| `end_date` | string | 是 | 无 | 结束日期 |
| `factor_version` | string | 否 | `published` | 因子版本 |
| `query_mode` | string | 否 | `latest` | 当前只支持 `latest`；`asof`/`vintage` fail closed |
| `format` | string | 否 | `long` | `long` 或 `wide` |

请求示例：

```json
{
  "factors": ["momentum_20d", "roe_ttm"],
  "universe": "zz800",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "query_mode": "latest",
  "format": "long"
}
```

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | string | 证券代码 |
| `trade_date` | string | 交易日 |
| `factor_code` | string | 因子代码 |
| `factor_value` | number | 因子值 |
| `factor_version` | string | 因子版本 |
| `quality_flag` | string | 质量标记 |

`latest` 先从 PostgreSQL 解析与 `factor_value_daily` dataset 精确绑定、批次
`success` 且已完成、状态为 `active`/`superseded` 的 dataset versions，再用该集合
限制 ClickHouse；orphan、running、failed、`recalled` 版本不可见。相同
identity/data-version/calc-time 的完全相同重试可确定性折叠，不同
`factor_value`/`quality_flag`/`universe_id` 则 fail closed。范围结果按每个
`trade_date` 标注历史 ticker；ticker recycling 歧义不会用 current symbol 掩盖。

### 5.11 获取数据版本

```http
GET /v1/datasets/versions
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `dataset_code` | string | 否 | `null` | 数据集代码 |
| `asof_time` | string | 否 | 当前时间 | 查询时点 |
| `status` | string | 否 | `active` | 版本状态 |

### 5.12 获取数据健康状态

```http
GET /v1/datasets/{dataset_code}/health
```

请求参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `start_date` | string | 是 | 无 | 开始日期 |
| `end_date` | string | 是 | 无 | 结束日期 |
| `severity` | string | 否 | `null` | 严重级别 |

响应字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `dataset_code` | string | 数据集 |
| `check_date` | string | 检查日期 |
| `check_name` | string | 检查名称 |
| `status` | string | 检查状态 |
| `severity` | string | 严重级别 |
| `metric_value` | number | 指标值 |
| `threshold_value` | number | 阈值 |
| `affected_rows` | integer | 影响行数 |

## 6. Python SDK 契约

### 6.1 初始化

```python
from qdata import Client

client = Client(
    token="your-token",
    base_url="https://api.example.com/v1",
    timeout=30,
    default_format="dataframe"
)
```

参数：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `token` | string | 必填 | API Token |
| `base_url` | string | 环境默认 | 服务地址 |
| `timeout` | integer | `30` | 请求超时秒数 |
| `default_format` | string | `dataframe` | `dataframe`、`json`、`arrow` |

### 6.2 `get_security_master`

```python
df = client.get_security_master(
    symbols=["600519.SH", "000001.SZ"],
    asof_date="2024-12-31",
    include_delisted=False,
    fields=["symbol", "name", "list_date", "status"]
)
```

返回：pandas DataFrame。

### 6.3 `get_trading_calendar`

```python
calendar = client.get_trading_calendar(
    exchange="SH",
    start_date="2026-07-01",
    end_date="2026-07-31",
    open_only=True
)
```

返回：pandas DataFrame。

### 6.4 `get_price`

```python
prices = client.get_price(
    symbols=["600519.SH", "000001.SZ"],
    start_date="2024-01-01",
    end_date="2024-12-31",
    frequency="1d",
    adjust="forward",
    fields=["open", "high", "low", "close", "volume", "amount"],
    query_mode="latest"
)
```

参数补充：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `frequency` | string | `1d` | `1d` 或 `1m` |
| `adjust` | string | `none` | `none`、`forward`、`backward` |
| `format` | string | `long` | `long` 或 `wide` |

### 6.5 `get_trading_constraints`

```python
constraints = client.get_trading_constraints(
    universe="zz800",
    start_date="2024-01-01",
    end_date="2024-12-31",
    fields=["is_suspended", "is_st", "limit_up", "limit_down", "can_buy", "can_sell"]
)
```

### 6.6 `get_fundamental_asof`

```python
fundamentals = client.get_fundamental_asof(
    symbols=["600519.SH"],
    fields=["revenue", "net_profit_parent", "roe_ttm"],
    asof_date="2021-06-30",
    period_type="ttm"
)
```

返回语义：

- 返回截至 `asof_date` 当时可见的最新报告期数据。
- 若指定 `report_period`，只返回该报告期在 `asof_date` 可见的版本。

### 6.7 `get_index_members_asof`

```python
members = client.get_index_members_asof(
    index_code="000300.SH",
    asof_date="2024-06-28",
    include_weight=True
)
```

### 6.8 `get_industry_asof`

```python
industry = client.get_industry_asof(
    symbols=["600519.SH", "000001.SZ"],
    industry_system="sw",
    level=1,
    asof_date="2024-12-31"
)
```

### 6.9 `get_universe`

```python
universe = client.get_universe(
    universe="zz800",
    asof_date="2024-12-31",
    filters={
        "exclude_st": True,
        "exclude_suspended": True,
        "min_list_days": 120
    }
)
```

### 6.10 `get_factor`

```python
factors = client.get_factor(
    factors=["momentum_20d", "roe_ttm"],
    universe="zz800",
    start_date="2024-01-01",
    end_date="2024-12-31",
    query_mode="latest",
    format="long"
)
```

当前公开 `get_factor` 与 `get_adjustment_factor` 签名不能完整表达 knowledge
cutoff 或固定数据版本，因此只支持 `query_mode="latest"`；传入 `asof` 或
`vintage` 会 fail closed。`start_date`/`end_date` 只过滤经济日期，不是 PIT
可见性边界。SQL latest 只接纳成功、已完成、精确 batch-bound 且未 recalled 的
dataset version；因子 payload 冲突会 fail closed。价格接口仍可按其完整参数使用
下表三种模式。

### 6.11 `get_dataset_health`

```python
health = client.get_dataset_health(
    dataset_code="daily_bar",
    start_date="2024-01-01",
    end_date="2024-12-31"
)
```

## 7. 枚举定义

### 7.1 `query_mode`

| 值 | 说明 |
|---|---|
| `latest` | 当前最新数据 |
| `asof` | 历史时点可见数据 |
| `vintage` | 指定版本数据 |

### 7.2 `frequency`

| 值 | 说明 |
|---|---|
| `1d` | 日频 |
| `1m` | 1 分钟 |

### 7.3 `adjust`

| 值 | 说明 |
|---|---|
| `none` | 不复权 |
| `forward` | 前复权 |
| `backward` | 后复权 |

### 7.4 `asset_type`

| 值 | 说明 |
|---|---|
| `stock` | 股票 |
| `etf` | ETF |
| `convertible_bond` | 可转债 |
| `index` | 指数 |

MVP 优先支持 `stock` 和 `index`。

## 8. 错误码

| 错误码 | HTTP 状态 | 说明 | 示例 |
|---|---:|---|---|
| `AUTH_001` | 401 | 未提供 Token | Authorization header missing |
| `AUTH_002` | 401 | Token 无效或过期 | token expired |
| `PERM_001` | 403 | 无数据集权限 | no permission for minute_bar |
| `PARAM_001` | 400 | 参数格式错误 | invalid date format |
| `PARAM_002` | 400 | 参数组合错误 | symbols and universe cannot both be empty |
| `PARAM_003` | 400 | 不支持的枚举值 | unsupported frequency |
| `QUERY_001` | 413 | 查询规模超过限制 | row limit exceeded |
| `DATA_001` | 404 | 数据不存在 | no data for date range |
| `DATA_002` | 409 | 数据版本不可用 | data version recalled |
| `PIT_001` | 422 | PIT 查询无法确定有效版本 | ambiguous revision |
| `RATE_001` | 429 | 调用频率超限 | rate limit exceeded |
| `SERVER_001` | 500 | 服务内部错误 | internal error |
| `SERVER_002` | 503 | 依赖服务不可用 | clickhouse unavailable |

## 9. 权限说明

| 权限 | 说明 |
|---|---|
| `data:master:read` | 读取证券主数据 |
| `data:calendar:read` | 读取交易日历 |
| `data:market:read` | 读取行情和交易约束 |
| `data:fundamental:read` | 读取财务和基本面 |
| `data:index:read` | 读取指数数据 |
| `data:industry:read` | 读取行业数据 |
| `data:factor:read` | 读取因子数据 |
| `data:quality:read` | 读取数据质量 |
| `data:meta:read` | 读取数据版本和元数据 |

## 10. 兼容性规则

### 10.1 字段兼容

- 可以新增响应字段。
- 不得在同一主版本中删除字段。
- 字段含义变化必须新增字段名或新增版本。
- 枚举新增必须兼容旧客户端。

### 10.2 接口版本

MVP 使用 `/v1`。

破坏性变更必须进入 `/v2`。

### 10.3 SDK 兼容

- SDK 小版本升级不得破坏已有方法签名。
- 废弃参数需要至少保留一个小版本周期。
- SDK 必须暴露服务端 `request_id`，方便排查。

## 11. 联调注意事项

### 11.1 数据量控制

前端、SDK 和回测引擎联调时，必须先使用小股票池和短日期区间。

### 11.2 时间语义测试

所有涉及财务、指数、行业和因子的接口，必须包含 as-of 测试用例。

### 11.3 空值处理

SDK 不应擅自将 NULL 填充为 0。

缺失值、停牌、权限不可见和数据不存在必须能区分。

### 11.4 审计

服务端必须记录：

- 用户。
- API 名称。
- 参数摘要。
- 数据版本。
- 返回行数。
- 错误码。

## 12. MVP 后续扩展

MVP 后建议扩展：

- 异步大查询导出。
- Arrow Flight。
- gRPC。
- Tick 和 Level-2。
- 实时行情订阅。
- 因子注册和发布 API。
- 回测引擎适配器。
- 多租户管理 API。
