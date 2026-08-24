# A 股数据产品 Rho-5 验收标准

## 前置条件

- Docker PostgreSQL 和 ClickHouse 可用。
- PostgreSQL 已执行 `0003` 到 `0041` migration。
- Python 3.12 虚拟环境 `.venv312` 可用于 AkShare。
- 本地样例 CSV 位于 `raw/samples/`。

## 验收标准

1. 全市场任务可解析 provider 股票池。
   - CSV provider 返回样例 3 只证券。
   - AkShare provider 可通过 `stock_info_a_code_name` 返回全市场代码简称。

2. 日频 pipeline 支持分批拉取和合并入库。
   - 设置 `--batch-size 1` 时，3 只样例证券记录 `batches=3`。
   - 所有 batch 合并成一次标准 CSV 快照和一次质量检查。

3. 完整性可观察。
   - `pipeline_run.expected_row_count` 记录预期证券数。
   - `pipeline_run.missing_symbols` 记录缺失证券。
   - `pipeline_run.completeness_rate` 记录实际覆盖率。
   - `pipeline_run.expected_by_exchange`、`actual_by_exchange`、`missing_by_exchange` 记录交易所拆分。
   - `pipeline_run.missing_explanations` 记录缺失或排除原因。

4. 非交易日自动跳过。
   - CSV provider 对 `2024-01-05` 返回 `skipped`。
   - skipped run 不写入行情数据。

5. 生产 smoke 可判断数据是否可用。
   - smoke 输出 pipeline 状态、ClickHouse 行数、SDK 样例价格和当前 job/source 的 health 结果。
   - AkShare 小样本 smoke 能查回 `000001.SZ`、`000002.SZ`。

6. 生产运行支持增量、回补和重跑。
   - `run_daily_production.sh` 可从 watermark 续跑。
   - backfill 模式可按日期窗口补跑。
   - rerun/force 可覆盖指定问题日期。

7. 修复队列可闭环。
   - `partial_success` 或 `failed` 写入 `qmeta.pipeline_repair_queue`。
   - 问题日期重跑成功后 repair item 自动 `resolved`。
   - `run_repair_queue.py` 可读取 open repair items 并触发重跑。

8. 生产日报和查询压测可执行。
   - `report_daily_production.py` 可输出指定窗口 status、missing、completeness 和 repair 摘要。
   - `benchmark_daily_query.py` 可输出 SDK 查询耗时和 rows/s。

9. 复权和交易约束可独立同步。
   - `sync_market_constraints.py` 可写入 `adjustment_factor`、`limit_price_daily` 和 `suspension_history`。
   - 同步结果可被 `get_adjustment_factor`、`get_trading_constraints` 查询。

10. 可交易股票池可直接生成。
   - `Client.get_tradable_universe` 可排除 ST、停牌、新股特殊期、退市期和上市天数不足标的。
   - `build_tradable_universe.py` 可把结果写入 `qpit.universe_member_pit`。

11. 矩阵出口和分钟线 Alpha 可执行。
   - `export_price_matrix.py` 可输出 `trade_date x symbol` CSV/Parquet 宽表，并写入 `matrix_export_audit`。
   - `sync_minute_market.py` 可写入 `qts.minute_bar` 并被 SDK `frequency="1m"` 查询。

12. 多源融合可执行。
   - `csv` 和 `csv_mirror` 可对同一交易日做字段级比较。
   - `compare_daily_sources.py --dry-run` 可输出 coverage/conflict rate。
   - 非 dry-run 可写入 `qmeta.data_conflict_daily` 和 `qmeta.multi_source_quality_daily`。

13. 主源失败可 fallback。
   - 主源抛错时，`select_daily_bundle_with_fallback` 会记录失败尝试并使用下一优先级可用源。
   - 全部源失败或返回空日线时返回清晰校验错误。

14. REST API 可查询核心量化数据。
   - `/price`、`/constraints`、`/tradable-universe`、`/matrix` 可通过真实 HTTP 请求访问。
   - SQL backend 下可查回 PostgreSQL/ClickHouse 样例数据。

15. API 鉴权、配额和审计可用。
   - 缺少 token 时受保护接口返回 401。
   - Bearer token 或 `X-API-Token` 可通过鉴权。
   - 成功请求写入 `qmeta.api_request_audit`。

16. 批量返回格式可用。
   - REST JSON/CSV 返回可用。
   - Arrow 路径在未安装 `pyarrow` 时返回明确依赖提示，安装 `qdata[export]` 后可启用。

17. 运维看板可用。
   - `report_ops_dashboard.py` 可汇总 pipeline、quality、多源冲突、API 审计和 alert。
   - 看板可按日期窗口、job 和 dataset 过滤。
   - `--write-snapshot` 可写入 `qmeta.ops_dashboard_snapshot`。

18. SLA 策略和告警可用。
   - `check_sla_alerts.py --ensure-policy` 可创建或更新 `qmeta.sla_policy`。
   - 完整率、冲突率、API 错误率、耗时和完成时间均可触发告警。
   - 告警按 `alert_key` 幂等写入 `qmeta.alert_event`。

19. API 审计报表可用。
   - `report_api_audit.py` 可输出请求量、失败量、错误率和慢接口。
   - 成功、失败、不同 format 请求均能聚合。

20. 商业供应商 profile 可注册。
   - `register_vendor_profile.py` 可创建或更新 `qmeta.vendor_integration_profile`。
   - profile 记录 auth、endpoint、限频、重试、授权范围、合同引用和再分发边界。
   - 不保存 token 明文。

21. `vendor_http` adapter 可接真实 HTTP JSON，也可用 fixture smoke。
   - HTTP 模式支持 Bearer/Header/Query/Basic auth。
   - adapter 支持限频、重试、timeout 和错误归因。
   - fixture 模式使用同一 provider 名称写入 benchmark 和评分链路。

22. 多日 provider benchmark 可落库。
   - `benchmark_vendor_sources.py` 可对主备源按日期窗口做字段级比较。
   - 结果写入 `provider_benchmark_run`、`vendor_quality_score_daily` 和 `provider_error_event`。
   - benchmark 同步写入 Epsilon 的 `data_conflict_daily` 和 `multi_source_quality_daily`，避免质量看板断层。

23. 供应商评分榜可读。
   - `report_vendor_scores.py` 可按 dataset 输出供应商最新评分。
   - 评分包含 coverage、conflict、stability、latency、cost、license 六类维度。
   - AkShare 可作为真实开源第二源小样本 benchmark；商业 vendor 没有账号时使用 `vendor_http` fixture 验收生产 adapter 路径。

24. 真实 vendor 生产配置可用。
   - `vendor_http` 可从 `QDATA_VENDOR_*` 环境变量读取 endpoint、token、auth、限频、重试和响应 rows key。
   - token 不写入 `vendor_integration_profile` 明文字段。
   - `activate_vendor_profile.py` 可将 profile 切换为 testing/active/paused/retired。

25. 供应商字段映射层可用。
   - `register_vendor_field_mapping.py` 可写入 `qmeta.vendor_field_mapping` 默认日线映射。
   - `vendor_http` HTTP 模式可按 mapping 转换字段名和单位。
   - 0 值不能被 fallback 逻辑误判为缺失。

26. 全市场分片 benchmark 可用。
   - `benchmark_vendor_universe.py` 支持 symbols/all-market、`shard_size`、`max_symbols`、`target_trade_days`。
   - suite 聚合覆盖率、冲突率、失败率、P95 延迟和 rows/s。
   - suite 聚合评分写回 `vendor_quality_score_daily`，不只保留最后一个分片得分。

27. Provider SLA 告警可用。
   - `sla_policy` 支持供应商评分、冲突率、失败率、延迟和错误数阈值。
   - `check_provider_sla_alerts.py` 可写入 vendor/provider 类型告警。
   - 告警继续复用 `qmeta.alert_event` 幂等写入。

28. 上线决策报告可用。
   - `report_vendor_decisions.py` 可读取最新供应商评分并生成 primary/backup/research_only/reject 建议。
   - 决策报告可写入 `qmeta.vendor_decision_report`。
   - 高分但冲突率未达 primary 阈值的 vendor 只能建议为 backup。

29. 告警通知可闭环。
   - `register_notification_channel.py` 可注册 stdout/webhook/email/feishu 通道。
   - `send_alert_notifications.py` 可读取 open alert，按 severity 过滤并写入 `alert_notification_delivery`。
   - 重复投递使用稳定 delivery key 更新尝试次数，不重复制造不可追踪明细。

30. 租户、项目、主体和数据集 ACL 可用。
   - `bootstrap_iota_security.py` 可创建 tenant/project/principal/project_member/api_token。
   - 数据库 token 可绑定 tenant/project/principal/cost_center。
   - REST `/price`、`/matrix`、`/constraints`、`/tradable-universe` 会按 dataset 做 ACL 校验。

31. API 用量计量可用。
   - `api_request_audit` 记录租户上下文和 `cost_units`。
   - `report_api_usage.py --rollup` 可汇总到 `api_usage_daily`。
   - 重复 rollup 不因 NULL 租户字段或同一 token 产生重复日报。

32. 供应商压测调度可用。
   - `manage_vendor_benchmark_schedule.py` 可创建或更新 schedule。
   - `--run-now` 可复用 Theta suite 跑 fixture benchmark，并回写 `last_suite_id/last_run_at/next_run_at`。
   - manual/daily/weekly/monthly cadence 均有明确下一次运行口径。

33. 多数据集字段映射可用。
   - 默认映射覆盖 `daily_bar`、`adjustment_factor`、`limit_price_daily` 和 `security_master`。
   - 每个 dataset 可独立注册和读取 active mapping。
   - 单位转换和日期转换规则继续复用 Theta 字段映射层。

34. Kappa 管理 API 可用。
   - `/admin/overview`、`/admin/tenants`、`/admin/projects`、`/admin/principals`、`/admin/tokens` 可返回统一 JSON 结构。
   - `/admin/dataset-access`、`/admin/notification-deliveries`、`/admin/vendor-schedules` 可查询 Iota/Theta/Zeta 运营状态。
   - `/usage/daily` 可按日期、租户、项目、主体和 API 名称过滤用量日报。

35. Kappa 鉴权和脱敏可用。
   - Kappa 路径需要 `admin` scope。
   - 普通 `read` token 访问 `/admin/*` 返回 403。
   - token 列表只返回 `token_hash_tail`，不返回明文 token 或完整 hash。

36. Kappa 内部运营台可用。
   - `/admin/console` 返回只读 HTML 页面。
   - 页面展示 overview、API 用量、通知投递和供应商 schedule。
   - 页面复用 API 鉴权，不绕过 token scope。

37. Kappa CLI 和 smoke 可用。
   - `report_kappa_admin.py` 可查询 overview、usage、delivery、schedule 等资源。
   - `smoke_kappa_admin_api.py` 可验证运行中 API 服务的 Kappa 端点和 HTML 页面。
   - Kappa smoke 不影响原有 `/price`、`/constraints`、`/tradable-universe` 和 `/matrix` 查询。

38. Lambda worker 运行记录可用。
   - `worker_run` 记录 run_code、trigger_mode、status、dry_run、处理数、成功数、warning 数和失败数。
   - `worker_task_run` 记录每个 task 的状态、耗时、处理数、明细和错误摘要。
   - 失败 task 不会阻断后续审计落库，worker 总状态可区分 success/warning/failed/skipped。

39. Lambda usage rollup 可用。
   - `usage_rollup` task 可把 `api_request_audit` 聚合到 `api_usage_daily`。
   - dry-run 只预览聚合分组并写 worker 记录。
   - 重复真实 rollup 保持日报幂等更新。

40. Lambda alert dispatch 可用。
   - `alert_dispatch` task 可按 channel 和 severity 投递 open alert。
   - dry-run 只预览可投递 alert/channel 组合。
   - 真实投递复用 Iota `alert_notification_delivery` 幂等键。

41. Lambda vendor schedule 可用。
   - `vendor_benchmark_schedule` task 可扫描到期 schedule 或按 `--schedule-code` 指定运行。
   - 运行结果复用 Theta suite，并回写 `last_suite_id`。
   - suite 本身为 warning 时 worker 总状态为 warning，但 failed_count 保持 0。

42. Lambda 接入 Kappa 可用。
   - `/admin/worker-runs` 可查看最近 worker 运行。
   - `/admin/console` 展示 Worker Runs 区块。
   - `smoke_kappa_admin_api.py` 覆盖 worker-runs 端点。

43. Mu worker schedule 可用。
   - `worker_schedule` 初始化 3 个默认 active schedule。
   - `run_mu_scheduler.py --force-due --once` 可强制指定 schedule 到期并触发一次 Lambda worker。
   - 成功执行后回写 `last_status/last_worker_run_id/next_run_at/run_count`。

44. Mu 防重复和心跳可观测。
   - `worker_lock` 按 `worker_schedule:{schedule_code}` 抢锁，同一 schedule 同时只允许一个 scheduler 执行。
   - 未抢到锁的 tick 记录为 `skipped_locked`，不触发重复 worker。
   - `worker_heartbeat` 记录 scheduler_id、host、pid、last_seen_at、stopped_at、tick_count 和 run_count。

45. Mu scheduler tick 可审计。
   - `worker_schedule_tick` 记录 tick_code、scheduler_id、schedule_code、task_name、status、lock_acquired 和 worker_run_id。
   - task 成功、warning、失败、跳过和锁冲突都有可查询状态。
   - Docker profile 方式可在容器内连接 Compose Postgres 执行 scheduler。

46. Mu 接入 Kappa 可用。
   - `/admin/worker-schedules`、`/admin/worker-locks`、`/admin/worker-heartbeats`、`/admin/worker-schedule-ticks` 可查询调度状态。
   - `/admin/overview` 展示 active schedule、live scheduler、expired lock 和最新 tick 状态。
   - `/admin/console` 展示 Worker Schedules、Scheduler Heartbeats 和 Scheduler Ticks。

47. Nu 部署健康元数据可用。
   - `deployment_release` 记录 release_code、environment、status 和最新健康快照。
   - `deployment_health_snapshot` 记录总状态、检查数、成功数、warning 数和失败数。
   - `deployment_health_check` 记录每个组件的 status、duration_ms、details 和 error_message。
   - `deployment_event` 记录 health_check、rollback 等事件。

48. Nu 健康检查可执行。
   - `check_nu_health.py` 可检查 Postgres、migration、ClickHouse、API、scheduler 和 Kappa。
   - `--write-db` 可写入 snapshot/check/event，并把 release 标记为 healthy/degraded/failed。
   - API 未提供时可标记 skipped；提供 API base URL 时必须真实请求 `/health`。

49. Nu 本地部署/回滚入口可用。
   - `deploy_nu_local.sh` 可启动 Postgres/ClickHouse，应用迁移，并可启动 API/scheduler profiles。
   - `rollback_nu_local.sh` 默认只停止 API/scheduler，不删除业务数据。
   - 只有显式 `--drop-nu-metadata` 才删除 0014 Nu 元数据表。

50. Nu 接入 Kappa 可用。
   - `/admin/deployment-releases`、`/admin/deployment-health`、`/admin/deployment-health-checks`、`/admin/deployment-events` 可查询。
   - `/admin/overview` 展示 latest_deployment_health_status、latest_deployment_release_status 和 deployment_24h_failed_count。
   - `/admin/console` 展示 Deployment Health 和 Deployment Releases 区块。

51. Xi 数据产品目录可用。
   - `data_product` 可记录产品编码、产品类型、计费单位、SLA 和授权边界。
   - `data_product_dataset` 可把产品绑定到多个 dataset。
   - `data_product_api` 可把产品绑定到多个 billable API。

52. Xi 计费价格表可用。
   - `pricing_plan` 可记录计费周期、币种、基础费用和包含用量。
   - `pricing_rule` 可按 cost_unit/request/row/export/monthly_fee 设置单价。
   - `product_subscription` 可把 tenant/project 绑定到产品和价格计划。

53. Xi 预算评估和告警可用。
   - `budget_policy` 可按 tenant/project/principal/cost_center 设置日/月预算。
   - `budget_usage_snapshot` 可从 `api_usage_daily` 和价格规则计算周期使用金额。
   - `budget_alert` 可生成 warning/exceeded/blocked 告警，并在状态升级时关闭旧等级告警。
   - 预算告警同步写入 `alert_event`，复用 Iota 通知链路。

54. Xi API hard limit 可用。
   - DB token 携带 tenant/project/principal/cost_center 时，API 查询前会检查 hard limit。
   - hard limit 关闭时只告警不阻断查询。
   - hard limit 打开且预计下一次请求越线时返回 budget blocked 决策。
   - 未配置预算或兼容 env token 不受影响。

55. Xi 接入 Kappa 可用。
   - `/admin/data-products`、`/admin/pricing-plans`、`/admin/pricing-rules`、`/admin/product-subscriptions` 可查询商业目录。
   - `/admin/budget-policies`、`/admin/budget-usage`、`/admin/budget-alerts` 可查询预算治理状态。
   - `/admin/overview` 展示 active_product_count、active_budget_policy_count、budget_open_alert_count、budget_month_usage_amount。
   - `/admin/console` 展示 Data Products、Budget Policies、Budget Usage 和 Budget Alerts 区块。

56. Omicron 账单主表可用。
   - `invoice` 可记录 tenant/project/subscription/product/plan、账期、开票日、到期日、币种、应收、实收、未收和状态。
   - 状态覆盖 draft/issued/partially_paid/paid/overdue/void。
   - 重复生成同一订阅同一账期账单保持幂等，不重复制造主账单。

57. Omicron 账单明细和金额口径可用。
   - `invoice_line` 可按 API 和 metric 拆分 request/row/cost_unit/export/monthly_fee/base_fee。
   - 明细金额按 `pricing_rule` 的 quantity、free_quantity 和 unit_price 计算。
   - 无专属 API 规则时可使用产品/计划通用规则；无规则时保留 fallback cost_unit 明细用于审计。

58. Omicron 回款和事件可审计。
   - `update_omicron_invoice_status.py` 可更新 paid/overdue/void 等状态。
   - 回款后 `paid_amount`、`outstanding_amount` 和 `paid_at` 同步更新。
   - `invoice_event` 记录生成、回款、逾期和作废事件。

59. Omicron 接入 Kappa 可用。
   - `/admin/invoices`、`/admin/invoice-lines`、`/admin/invoice-events`、`/admin/revenue-summary` 可查询账单和收入状态。
   - `/admin/overview` 展示 invoice_month_count、invoice_month_total_amount、invoice_month_paid_amount、invoice_month_outstanding_amount 和 overdue_invoice_count。
   - `/admin/console` 展示 Invoices 和 Revenue Summary 区块。

60. Pi 供应商上线复核表可用。
   - `vendor_readiness_review` 可记录 source/dataset、必要窗口、suite 数、状态、上线建议、推荐角色和阻塞原因。
   - `vendor_readiness_window` 可记录 5/20/60 每个窗口对应 suite 和 coverage/conflict/failure/latency/throughput。
   - 重复生成同一天同 source/dataset/windows 复核保持 review 幂等更新。

61. Pi 复核口径可用。
   - 缺少必要窗口时 status=incomplete、recommendation=watch。
   - 覆盖率/失败率硬阈值不达标时 status=rejected 或窗口 failed。
   - 冲突率/延迟/吞吐未达主源阈值但未硬失败时 recommendation=approve_backup、role=backup。

62. Pi 接入 Kappa 可用。
   - `/admin/vendor-readiness` 可查询复核总结。
   - `/admin/vendor-readiness-windows` 可查询窗口明细。
   - `/admin/overview` 展示 vendor_readiness_ready_count、vendor_readiness_watch_count、vendor_readiness_rejected_count 和 latest_vendor_readiness_status。
   - `/admin/console` 展示 Vendor Readiness 区块。

63. Rho 收入对账可用。
   - `revenue_reconciliation_run` 可记录账期、客户、产品、订阅、账单、重算金额、开票金额和差异状态。
   - `revenue_reconciliation_line` 可保留 API/metric 级 invoice vs recomputed 金额、数量和差异。
   - 重复生成同一账期、同一客户项目、同一复核日期保持对账结果幂等更新。

64. Rho AR aging 可用。
   - `ar_aging_snapshot` 可按 as_of_date 输出 current、1-30、31-60、61-90、90+ 账龄分桶。
   - 已结清账单仍能形成 current 快照，避免无未收时看不到客户。
   - 逾期金额可区分 overdue 和 critical。

65. Rho 客户健康可用。
   - `customer_health_snapshot` 可按订阅输出 active/at_risk/dormant/churned。
   - 客户健康结合最近使用日期、30 日请求量、未收金额和逾期账单数。
   - retention_signal 可区分 healthy、payment_risk、usage_declining、inactive 和 no_usage。

66. Rho 接入 Kappa 可用。
   - `/admin/revenue-reconciliation` 和 `/admin/revenue-reconciliation-lines` 可查询重算差异。
   - `/admin/ar-aging` 可查询应收账龄。
   - `/admin/customer-health` 可查询客户健康。
   - `/admin/overview` 展示 latest_reconciliation_status、latest_ar_outstanding_amount 和 customer_health_* 指标。
   - `/admin/console` 展示 Revenue Reconciliation、AR Aging 和 Customer Health 区块。

67. Sigma 运行日志和指标快照可用。
   - `runtime_log` 可记录 environment、component、service_name、severity、event_type、message 和 trace/request 信息。
   - `runtime_metric_snapshot` 可记录 metric_value、unit、warning_threshold、critical_threshold 和 normal/warning/critical 状态。
   - `report_sigma_runtime.py --resource collect` 可一次写入运行日志和多组件指标。

68. Sigma 容量告警可用。
   - 超过 warning/critical 阈值的指标可生成 `capacity_alert`。
   - 容量告警同步写入 `alert_event`，alert_type 使用 `runtime_capacity_warning` 或 `runtime_capacity_critical`。
   - 同一 environment/component/metric 的容量告警保持幂等更新，指标恢复正常时可转 resolved。

69. Sigma 运行日报可用。
   - `runtime_daily_report` 可汇总当日 API 请求、失败率、最慢请求、worker 失败、部署健康、供应商 watch、应收金额、客户风险和容量告警。
   - 日报状态区分 success/warning/critical。
   - 重复生成同一 environment/report_date 日报保持幂等更新。

70. Sigma 接入 Kappa 可用。
   - `/admin/runtime-logs`、`/admin/runtime-metrics`、`/admin/runtime-daily-reports` 和 `/admin/capacity-alerts` 可查询 Sigma 资源。
   - `/admin/overview` 展示 runtime_24h_error_log_count、runtime_metric_warning_count、runtime_metric_critical_count、open_capacity_alert_count 和 latest_runtime_report_status。
   - `/admin/console` 展示 Runtime Logs、Runtime Metrics、Runtime Daily Reports 和 Capacity Alerts 区块。

71. Tau 真实回款导入可用。
   - `payment_import_batch` 记录批次来源、账期、币种、总金额、匹配金额和未匹配金额。
   - `payment_transaction` 记录真实流水、外部交易号、渠道、对手方、value_date、原币金额、base 金额和发票提示。
   - CSV/API/demo 导入支持幂等 transaction_code，重复导入不膨胀流水。

72. Tau 自动发票匹配可用。
   - 可从 reference_text 提取 `inv-*` 发票号，并按币种、未收金额和容忍金额自动匹配。
   - exact/partial/overpaid/unmatched 均有明确状态和金额口径。
   - 已存在 active match 时重复执行保持幂等，不把 paid 发票对应流水误改为 unmatched。

73. Tau 收入 ledger 和汇率表可用。
   - `revenue_ledger_entry` 记录 payment_received、payment_matched、payment_unmatched、refund 和 adjustment 分录。
   - 原币和 base_currency 金额同时保留，支持未来多币种。
   - `fx_rate_daily` 可按 date/from/to/provider 维护日汇率。

74. Tau 接入 Kappa 可用。
   - `/admin/payment-batches`、`/admin/payments`、`/admin/payment-matches`、`/admin/revenue-ledger` 和 `/admin/fx-rates` 可查询 Tau 资源。
   - `/admin/overview` 展示 payment_month_received_amount、payment_month_matched_amount、unmatched_payment_count、latest_payment_batch_status 和 revenue_ledger_month_credit_amount。
   - `/admin/console` 展示 Payment Batches、Payments、Payment Matches、Revenue Ledger 和 FX Rates 区块。

75. Upsilon 交互式运营台可用。
   - `/admin/console` 返回 `QData Upsilon Ops Console` HTML 页面，并保留 `QData Kappa Ops Console` 兼容标识。
   - 页面包含全局搜索、状态筛选和 Runtime/Payments/Revenue/Vendor/Automation/Commercial/Governance 分组切换。
   - 指标卡和表格按分组显隐，表格行支持前端过滤，动态值必须 HTML escape。

76. Upsilon 支付和收入复核视图可用。
   - Payments 分组可同时查看 Payment Batches、Payments、Payment Matches、Revenue Ledger 和 FX Rates。
   - Revenue 分组可查看 Invoices、Revenue Summary、Revenue Reconciliation、AR Aging 和 Customer Health。
   - Runtime 分组可查看 Deployment、Runtime Metrics、Runtime Daily Reports 和 Capacity Alerts。

77. Upsilon 真实页面验收可用。
   - `smoke_upsilon_console.py` 可对运行中的 API 服务检查 HTML、关键控件和关键区块。
   - Playwright 可在桌面和移动视口截取 `/admin/console` 页面，页面非空且控件、指标卡和表格正常渲染。
   - Upsilon 接入后，原有 Kappa JSON/CSV API 和量化数据 API 行为保持兼容。

78. Phi 策略元数据可用。
   - `strategy_policy`、`strategy_run`、`strategy_signal`、`strategy_decision` 和 `strategy_escalation_event` 可创建、重跑和回滚。
   - 默认策略覆盖 data_quality、vendor、runtime、commercial 和 payment 五个策略域。
   - 策略运行不改写原始质量、供应商、运行、商业、回款和收入事实表。

79. Phi 统一策略评估可用。
   - `report_phi_strategy.py --resource run-all` 能按 as_of_date/environment 聚合既有事实并生成策略 run。
   - 每条策略信号保留 domain、subject、signal_type、severity、metric、source_table、source_ref 和 message。
   - 每条策略决策保留 action、status、severity、priority_score、recommended_owner 和 reason。

80. Phi 升级事件可用。
   - high/critical 或 block/escalate 决策会生成 `strategy_escalation_event`。
   - 升级事件能区分 source_owner、runtime_owner、commercial_owner 和 finance_owner。
   - 重跑同一 run_code 时信号、决策和升级事件保持幂等替换，不膨胀。

81. Phi 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/strategy-runs`、`/admin/strategy-signals`、`/admin/strategy-decisions` 和 `/admin/strategy-escalations`。
   - `/admin/overview` 展示 latest_strategy_status、latest_strategy_severity、strategy_24h_action_decision_count 和 open_strategy_escalation_count。
   - Upsilon Strategy 分组可展示策略运行、信号、决策和升级事件。

82. Phi 真实链路验收可用。
   - Docker PostgreSQL 应用 `0021_postgresql_strategy_phi.sql` 成功。
   - Docker `qdata-api` 下 Kappa Admin API smoke 覆盖 Strategy 端点，原数据 API smoke 仍通过。
   - Playwright 桌面和移动截图显示 Strategy 区块，页面非空且表格正常渲染。

83. Chi 权限边界和访问审计可用。
   - Iota ACL 严格按 principal > project > tenant 匹配，主体级权限不会因同租户或同项目字段被其他主体继承。
   - REST 数据接口在数据库 token 路径下写入 `access_decision_audit`，记录 allow/deny、effective_scope、access_level、api_name、request_id 和字段拒绝原因。
   - 兼容环境变量 token 和未绑定租户的旧 token，不改变原数据 API 入参。

84. Chi 项目治理快照可用。
   - `report_chi_governance.py --resource collect-snapshots` 能汇总项目主体、token、ACL、7 日请求、失败、拒绝访问、预算、账单和开放治理动作。
   - 同一 `snapshot_date/project_id` 重跑保持幂等更新，不制造重复快照。
   - 风险评分能兼容预算用量比例和百分数两种输入口径。

85. Chi 治理动作可用。
   - warning/critical 项目可生成 `governance_action`。
   - 同一项目、日期和 action_type 重跑保持幂等更新，不膨胀。
   - action 保留 severity、owner、reason、due_at 和 snapshot 关联。

86. Chi 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/access-decisions`、`/admin/project-governance` 和 `/admin/governance-actions`。
   - `/admin/overview` 展示 access_denied_24h_count、project_governance_warning_count、project_governance_critical_count 和 open_governance_action_count。
   - Upsilon Governance 分组可展示 Access Decisions、Project Governance 和 Governance Actions。

87. Chi 真实链路验收可用。
   - Docker PostgreSQL 应用 `0022_postgresql_governance_chi.sql` 成功。
   - Chi CLI 可真实写入 allow/deny 访问审计、项目治理快照和治理动作。
   - Docker `qdata-api` 下 Kappa Admin API smoke 覆盖 Chi 端点，原数据 API smoke 仍通过。

88. Psi 自动化执行元数据可用。
   - `automation_run` 可记录 run_code、run_date、environment、trigger_mode、execution_mode、status 和动作计数。
   - `automation_action` 可记录 source_type、source_code、action_type、safety_level、approval_required、planned_effect、executed_effect 和 rollback_hint。
   - 0023 回滚脚本只删除 Psi 自动化审计表，不回滚源业务事实。

89. Psi dry-run 执行计划可用。
   - `report_psi_automation.py --resource run --execution-mode dry_run` 可从 Phi strategy decision 和 Chi governance action 生成统一动作。
   - dry-run 不改写源事实，动作状态为 skipped，并保留 would_execute、requires_approval 和 planned_effect。
   - 同一 run_code 重跑保持幂等更新，不制造重复 action_code。

90. Psi execute 护栏可用。
   - execute 模式下中低风险动作可成功记录执行结果。
   - repair_data_quality、degrade_vendor、freeze_budget、pause_product、rotate_token 等高风险动作未审批时必须停在 approval_required。
   - 同一 idempotency_key 已成功执行后再次执行会 skipped，避免重复暂停、重复降级或重复通知。

91. Psi 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/automation-runs` 和 `/admin/automation-actions`。
   - `/admin/overview` 展示 automation_24h_run_count、automation_24h_action_count、automation_approval_required_count、automation_24h_failed_count 和 latest_automation_status。
   - Upsilon Automation 分组可展示 Automation Runs 和 Automation Actions。

92. Psi 真实链路验收可用。
   - Docker PostgreSQL 应用 `0023_postgresql_automation_psi.sql` 成功。
   - Psi dry-run 可真实生成至少 3 类 action_type。
   - Psi execute 可真实成功 1 类低/中风险动作，并拦截 1 类高风险动作进入 approval_required。
   - Docker `qdata-api` 下 Kappa Admin API smoke 覆盖 Psi 端点，原数据 API smoke 仍通过。

93. Omega 自动化控制元数据可用。
   - `automation_approval` 可记录 approval_code、action、requested_by、status、decision 和过期时间。
   - `automation_executor` 可登记 noop/webhook/script、action_type、safety_level、重试次数和 backoff。
   - `automation_execution_attempt` 可记录 executor、attempt_no、status、payload、错误、retry_count 和 next_retry_at。
   - `automation_rollback` 可记录 rollback_plan、rollback_result、requested_by、executed_by 和状态。

94. Omega 审批护栏可用。
   - 高风险 action 未审批时 execute 必须写入 approval_required attempt。
   - approved 后才允许执行器执行。
   - rejected action 不会被 execute 自动重新申请审批或绕过执行。

95. Omega 执行器和重试可用。
   - 默认 noop executor 执行时不产生外部副作用，但完整记录 response_payload。
   - webhook/script executor 未显式允许外部执行时必须失败并记录原因。
   - 失败动作按 max_retry_count/backoff 进入 retry_scheduled，超过次数后进入 failed。

96. Omega 回滚演练可用。
   - 成功执行的 action 可从 rollback_hint 生成 rollback_plan。
   - run-rollback 可写入 rollback_result，并把 action 控制状态推进到 rolled_back。
   - 回滚失败必须保留 error_message，不删除原 attempt。

97. Omega 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/automation-approvals`、`/admin/automation-executors`、`/admin/automation-attempts` 和 `/admin/automation-rollbacks`。
   - `/admin/overview` 展示 automation_pending_approval_count、automation_retry_scheduled_count、automation_rollback_required_count 和 latest_automation_attempt_status。
   - Upsilon Automation 分组可展示 Automation Approvals、Automation Executors、Automation Attempts 和 Automation Rollbacks。

98. Omega 安全验收可用。
   - Kappa 查询 Omega 资源时，对 token、secret、password、authorization 等嵌套敏感字段做脱敏。
   - 默认本地 executor 为 noop，真实 webhook/script 需要显式配置和显式允许。
   - Docker `qdata-api` 下 Kappa Admin API smoke 覆盖 Omega 端点，原数据 API smoke 仍通过。

99. Alpha-2 外部执行白名单元数据可用。
   - `automation_executor_allowlist` 可记录 allowlist_code、executor_type、target_pattern、status、sandbox_only 和 max_timeout_seconds。
   - `automation_secret_ref` 只记录 secret_ref、secret_scope、secret_kind、owner 和 metadata.env_var，不保存密钥明文。
   - `automation_executor` 可绑定 sandbox_mode、allowlist_code、secret_ref、signing_algorithm 和 allowed_target。
   - 0025 回滚脚本删除 Alpha-2 种子和两张新增表，并移除 executor 安全字段。

100. Alpha-2 脚本沙箱执行可用。
   - script executor 未显式 `--allow-external` 时必须失败并记录 external_executor_disabled。
   - script target 必须为项目内相对路径，禁止绝对路径、`..` 逃逸和非 `.py` 文件。
   - 白名单内脚本执行成功时必须记录 returncode、stdout、stderr、sandbox_dispatch=true 和 external_side_effect=false。

101. Alpha-2 webhook 沙箱执行可用。
   - webhook executor 必须匹配 active allowlist，target 不匹配时必须失败并记录 target_not_allowlisted。
   - `hmac_sha256` 签名必须从 secret_ref 的 env_var 读取密钥，缺失时失败并记录 secret_missing。
   - 成功 webhook attempt 必须记录 status_code、response_body、signed=true、sandbox_dispatch=true 和 external_side_effect=false。

102. Alpha-2 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/automation-allowlists` 和 `/admin/automation-secrets`。
   - `/admin/overview` 展示 automation_active_sandbox_executor_count、automation_active_allowlist_count 和 automation_active_secret_ref_count。
   - Upsilon Automation 分组可展示 Automation Allowlists 和 Automation Secrets。

103. Alpha-2 真实链路验收可用。
   - Docker PostgreSQL 应用 `0025_postgresql_automation_alpha2.sql` 成功。
   - `alpha2-script-notify-owner` 可真实执行仓库内沙箱脚本并写入 success attempt。
   - `alpha2-webhook-notify-owner` 可真实 POST 到本地 allowlist webhook，并通过 HMAC 签名校验。
   - Docker `qdata-api` 下 Kappa Admin API smoke 覆盖 Alpha-2 端点，Upsilon marker 数从 22 增至 24，原数据 API smoke 仍通过。

104. Beta-2 外部通道元数据可用。
   - `automation_external_channel` 可记录 channel_code、channel_type、environment、endpoint_url、allowlist_code、secret_ref、retry 策略和 duplicate_window。
   - `automation_external_dispatch` 可记录 action、channel、dispatch_type、trigger_mode、status、payload、retry、next_retry_at、recovered_by 和 recovery_reason。
   - `automation_recovery_runbook` 可记录 failure_class、severity、owner、recovery_steps 和 rollback_steps。

105. Beta-2 dispatch 执行可用。
   - 未显式 `--allow-external` 时必须失败并记录 external_dispatch_disabled。
   - channel 必须通过 Alpha-2 allowlist 和 secret_ref 约束。
   - 成功 webhook dispatch 必须进入 acknowledged，并记录 status_code、signed=true 和 sandbox_dispatch=true。

106. Beta-2 重复抑制可用。
   - 同一 action/channel/dispatch_type 在 duplicate_window 内已有成功 dispatch 时，重复触发必须写入 suppressed。
   - suppressed dispatch 不调用外部系统，并记录 existing_dispatch_code。
   - `--force` 可绕过 duplicate_window，用于人工重放验证。

107. Beta-2 失败恢复可用。
   - webhook 失败时按 channel max_retry_count 进入 retry_scheduled 或 dead_letter。
   - recover 只允许 failed/retry_scheduled/dead_letter dispatch，并保留原始错误证据。
   - recover 后必须写入 recovered_by、recovery_reason、runbook_code 和 status=recovered。

108. Beta-2 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/automation-channels`、`/admin/automation-dispatches` 和 `/admin/automation-runbooks`。
   - `/admin/overview` 展示 automation_active_channel_count、automation_24h_dispatch_count、automation_dead_letter_count 和 latest_automation_dispatch_status。
   - Upsilon Automation 分组可展示 Automation Channels、Automation Dispatches 和 Automation Runbooks。

109. Gamma-2 多环境通道 profile 可用。
   - `automation_channel_profile` 可记录 profile_code、channel_code、provider_code、environment、dry_run/live endpoint、secret_ref、next_secret_ref、readiness_status 和 owner。
   - 初始本地 profile 至少覆盖 feishu、wecom、email 三类 provider。
   - profile 默认 dry_run_only，不允许未验证 live endpoint 直接进入 live_ready。

110. Gamma-2 联调验证可用。
   - `automation_channel_validation` 可记录 dry_run_dispatch、live_dispatch、secret_rotation 和 rollback_drill。
   - 成功 validation 必须关联 Beta-2 dispatch 证据，并记录 signed、status_code、dispatch_status 和 external_side_effect=false。
   - 失败或 blocked validation 必须保留 error_message，不更新为 ready。

111. Gamma-2 密钥轮换可用。
   - `automation_secret_rotation` 可记录 secret_ref、next_secret_ref、rotation_type、status、validation_id、affected_channel_count、apply/rollback 时间和证据。
   - `--apply-rotation` 必须先完成候选 secret 签名验证；验证失败不得修改 channel/profile secret_ref。
   - rollback 只允许 applied rotation，并把 channel/profile secret_ref 回退到旧 secret_ref。

112. Gamma-2 secret 安全可用。
   - 密钥明文只能来自 `automation_secret_ref.metadata.env_var` 指向的环境变量。
   - 数据库、Kappa API、CLI 报告只能输出 secret_ref、env_var 和短 fingerprint，不输出密钥明文。
   - current 和 next secret_ref 必须不同。

113. Gamma-2 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/automation-channel-profiles`、`/admin/automation-channel-validations` 和 `/admin/automation-secret-rotations`。
   - `/admin/overview` 展示 automation_active_profile_count、automation_ready_profile_count、automation_24h_validation_count、latest_automation_validation_status、automation_applied_rotation_count 和 latest_automation_rotation_status。
   - Upsilon Automation 分组可展示 Automation Channel Profiles、Automation Channel Validations 和 Automation Secret Rotations。

114. Delta-2 企业微信 live receipt 可用。
   - `automation_live_provider_receipt` 可记录 receipt_code、validation/profile/channel、provider_code、environment、message_type、status、provider_status_code、provider_errcode、provider_errmsg、request/response/evidence、sent_at 和 acknowledged_at。
   - Delta-2 初始 profile 使用 `provider_code=wecom`、`environment=live_test`、`dry_run_only=false`。
   - receipt 必须关联 Gamma-2 `automation_channel_validation`，validation_type=`live_dispatch`。

115. Delta-2 endpoint secret 安全可用。
   - 真实企业微信 webhook URL 只能来自 `automation_secret_ref.metadata.env_var=QDATA_DELTA2_WECOM_WEBHOOK_URL`。
   - 数据库、Kappa API、CLI 和 Upsilon 不输出 webhook URL 明文。
   - 缺少 env 或 URL 不合法时必须写 blocked receipt，并保留 error_message。

116. Delta-2 安全阻断 smoke 可用。
   - 未显式 `--allow-external` 时不得向企业微信发消息。
   - blocked receipt 必须记录 `external_live_dispatch_disabled` 和 `external_side_effect=false`。
   - `--require-live` 在缺少 webhook env 时必须失败，避免误判真实联调成功。

117. Delta-2 企业微信 live 发送口径可用。
   - 配置真实 `QDATA_DELTA2_WECOM_WEBHOOK_URL` 且显式 `--allow-external --require-live` 时才允许发送。
   - 企业微信 HTTP 2xx 且 JSON body `errcode=0` 才能标记 success。
   - 非 0 `errcode`、HTTP 非 2xx 或网络异常必须记录 failed/blocked 证据，不更新为 live_ready。

118. Delta-2 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/automation-live-receipts`。
   - `/admin/overview` 展示 automation_24h_live_receipt_count、automation_24h_wecom_success_count 和 latest_automation_live_receipt_status。
   - Upsilon Automation 分组可展示 Automation Live Receipts，并显示 Delta2 Live/WeCom/Receipt 概览。

119. Epsilon-3 真实供应商 live gate 审计可用。
   - `vendor_live_gate_run` 可记录 gate_code、dataset/source/primary_source、profile/review/suite 关联、run_mode、status、required_windows、executed_windows、env present flag、blocking_issues、next_actions 和 evidence。
   - gate 记录必须保留 start/end date、shard_size、max_symbols、symbol_count、duration_ms 和 requested_by/trigger_mode。
   - Epsilon-3 只追加 gate 审计，不改写 Theta benchmark、Pi readiness 或原始行情事实。

120. Epsilon-3 env-only token 安全可用。
   - 真实供应商 endpoint 和 token 只能来自 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN`。
   - 数据库、Kappa API、CLI 和 Upsilon 不输出 token 明文。
   - 未显式设置 `QDATA_VENDOR_AUTH_MODE` 时必须继承 DB vendor profile 的 `auth_mode`，当前 seeded `vendor_http` 为 bearer。

121. Epsilon-3 安全阻断 smoke 可用。
   - 未显式 `--allow-live` 时不得调用外部供应商。
   - blocked gate 必须记录 `external_vendor_live_disabled`。
   - `--require-live` 在缺少真实供应商 env 时必须失败，避免误判真实 vendor 联调成功。

122. Epsilon-3 live benchmark 准入口径可用。
   - 配置真实 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 且显式 `--allow-live --run-benchmarks` 时，才允许执行 5/20/60 benchmark windows。
   - live gate 必须把 suite_ids/suite_codes 和 Pi readiness review 写入 evidence。
   - 未达到 coverage/conflict/failure/latency/throughput 阈值时，不得给出 primary 上线成功 gate。

123. Epsilon-3 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-live-gates`。
   - `/admin/overview` 展示 vendor_24h_live_gate_count、vendor_24h_live_gate_blocked_count、vendor_24h_live_gate_executed_count 和 latest_vendor_live_gate_status。
   - Upsilon Vendor 分组可展示 Vendor Live Gates，并显示 Vendor Gates/Gate Blocked/Gate Live/Gate Status 概览。

124. Zeta-3 真实供应商 onboarding 审计可用。
   - `vendor_onboarding_run` 必须记录 source/profile/primary、dataset_codes、canary_symbols、5/20/60 required_windows、状态、推荐角色、gate_ids/gate_codes、阻塞原因和 next_actions。
   - `vendor_onboarding_dataset_result` 必须记录每个 dataset 的 preflight/canary/gate 状态、关联 gate、阻塞原因和 next_actions。
   - Zeta-3 只追加 onboarding 审计，不改写 Epsilon-3 gate、Theta benchmark、Pi readiness 或原始行情事实。

125. Zeta-3 预检和安全默认可用。
   - preflight 必须识别缺少 `QDATA_VENDOR_BASE_URL`、`QDATA_VENDOR_TOKEN`、商业合同引用、再分发授权、rate limit 和未启用 dataset。
   - 未显式 `--allow-live --run-benchmarks` 时不得调用外部供应商。
   - 数据库、Kappa API、CLI 和 Upsilon 不输出真实 vendor token 明文。

126. Zeta-3 require-live 保护可用。
   - 当前未配置真实供应商 env 时，`smoke_zeta3_vendor_onboarding.py --allow-live --require-live` 必须失败为 `missing_vendor_live_env`。
   - 本地 blocked smoke 必须写入可查询 onboarding run/result，且 status/recommendation 不得误判为生产上线成功。

127. Zeta-3 多数据集 gate 编排可用。
   - 默认覆盖 `daily_bar,security_master,adjustment_factor,limit_price_daily`。
   - 每个数据集都必须生成或记录对应 Epsilon-3 gate 证据。
   - 当前未启用的 `security_master` 必须被标记为 `dataset_not_enabled:security_master`，不得被忽略。

128. Zeta-3 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-onboarding-runs` 和 `/admin/vendor-onboarding-results`。
   - `/admin/overview` 展示 vendor_24h_onboarding_count、vendor_24h_onboarding_blocked_count 和 latest_vendor_onboarding_status。
   - Upsilon Vendor 分组可展示 Vendor Onboarding Runs、Vendor Onboarding Results 和 Vendor Live Gates。

129. Eta-3 真实供应商 live closure 审计可用。
   - `vendor_live_closure_run` 必须记录 source/profile/primary、dataset_codes、enabled/missing datasets、canary_symbols、窗口、env present flag、profile/contract/endpoint/onboarding/promotion 状态、推荐角色、阻塞原因和 next_actions。
   - closure 必须关联 Zeta-3 onboarding run、Epsilon-3 gate ids/codes 和 endpoint probe 统计。
   - Eta-3 只追加 closure/probe 审计，不改写 onboarding/gate、Theta benchmark、Pi readiness 或原始行情事实。

130. Eta-3 endpoint probe/schema/security 可用。
   - `vendor_live_endpoint_probe` 必须按 dataset 记录 endpoint_path、HTTP method、live_requested/live_executed、auth_status、schema_status、expected_fields、observed_fields、missing_fields、row_count 和 latency_ms。
   - 未显式 `--allow-live` 时不得调用外部供应商，probe 必须写为 blocked 并记录 `external_vendor_live_disabled`。
   - 数据库、Kappa API、CLI 和 Upsilon 不得输出真实供应商 token 明文或原始响应正文。

131. Eta-3 profile 写入和 live 护栏可用。
   - 未显式 `--allow-profile-write` 时不得更新 profile endpoint、dataset、合同、授权、限频或 active 状态。
   - 显式 `--allow-profile-write --activate-profile --enable-profile-datasets` 后，才允许写入 profile 元数据，并且 token 仍只能来自 env。
   - 缺少合同引用、再分发授权、rate limit、真实 env 或必要 dataset/profile 条件时，不得给出 primary_candidate。

132. Eta-3 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-live-closures` 和 `/admin/vendor-live-probes`。
   - `/admin/overview` 展示 vendor_24h_live_closure_count、vendor_24h_live_closure_blocked_count 和 latest_vendor_live_closure_status。
   - Upsilon Vendor 分组可展示 Vendor Live Closures、Vendor Live Probes、Vendor Onboarding Runs/Results 和 Vendor Live Gates。

133. Eta-3 require-live 和生产闭环可用。
   - 当前未配置真实供应商 env 时，`smoke_eta3_vendor_live_closure.py --allow-live --require-live` 必须失败为 `missing_vendor_live_env`。
   - 本地 blocked smoke 必须写入可查询 closure/probe/onboarding/gate 审计，且 status/recommendation 不得误判为生产上线成功。
   - 配置真实 env、合同、授权、限频和完整 dataset 后，`--allow-live --require-live --run-endpoint-probes --run-benchmarks` 才可进入真实 endpoint probe 和 benchmark。

134. Theta-3 真实供应商 live pilot run/result 审计可用。
   - `vendor_live_pilot_run` 必须记录 source/profile/primary、closure_code、pilot_scope、dataset_codes、canary_symbols、窗口、env present flag、closure/endpoint/onboarding/benchmark/signoff 状态、推荐角色、risk_level、阻塞原因和 next_actions。
   - `vendor_live_pilot_dataset_result` 必须按 dataset 记录 closure/probe/gate/schema/benchmark 状态、probe_code、gate_code、missing_fields、live_requested/live_executed 和 error_message。
   - Theta-3 只追加 pilot run/result 审计，不改写 Eta-3、Zeta-3、Epsilon-3、Theta benchmark、Pi readiness 或原始行情事实。

135. Theta-3 safe default 和 require-live 护栏可用。
   - 未显式 `--allow-live` 时不得调用外部供应商，pilot 必须写为 blocked/not_ready 并记录 `external_vendor_live_disabled`。
   - 当前未配置真实供应商 env 时，`smoke_theta3_vendor_live_pilot.py --allow-live --require-live` 必须失败为 `missing_vendor_live_env`。
   - 数据库、CLI、Kappa API 和 Upsilon 不得输出真实供应商 token、Authorization header 或原始响应正文。

136. Theta-3 dataset 级状态、风险和签核聚合可用。
   - 任一 dataset failed 时 pilot risk_level 必须为 critical；任一 blocked 时 risk_level 必须为 high；warning 时为 medium；全部成功才可为 low。
   - blocked/failed pilot 的 signoff_status 必须是 `not_ready`，不得进入 `pending_review` 或 `approved`。
   - 缺少合同、再分发授权、rate limit、完整 dataset、endpoint schema、onboarding 或 benchmark 证据时，不得给出 primary_candidate。

137. Theta-3 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-live-pilots` 和 `/admin/vendor-live-pilot-results`。
   - `/admin/overview` 展示 vendor_24h_live_pilot_count、vendor_24h_live_pilot_blocked_count 和 latest_vendor_live_pilot_status。
   - Upsilon Vendor 分组可展示 Vendor Live Pilots、Vendor Live Pilot Results、Eta-3 Closures/Probes、Zeta-3 Onboarding 和 Epsilon-3 Gates。

138. Theta-3 生产 pilot 晋级规则可用。
   - canary scope 通过后才允许扩大到 `pilot_scope=full_market` 或 `--full-market`。
   - full market pilot 必须保留 5/20/60 窗口、endpoint schema、onboarding/gate 和 benchmark 证据。
   - 只有 successful closure/schema/onboarding/benchmark 且签核进入 pending_review 后，才可作为 Pi 主源上线复核证据。

139. Iota-3 免费源联盟 run/result 审计可用。
   - `free_source_fabric_run` 必须记录 source_codes、dataset_codes、canary_symbols、覆盖率阈值、冲突阈值、license 风险、recommendation、risk_level、blocking_issues 和 next_actions。
   - `free_source_fabric_dataset_result` 必须按 dataset 记录 coverage_status、consistency_status、license_status、freshness_status、baseline_source_code、source 计数、coverage_rate、conflict_rate_bps 和脱敏 evidence。
   - Iota-3 只追加免费源联盟审计，不改写原始行情、真实供应商 pilot、账单、权限或生产数据事实。

140. Iota-3 safe default 和外部免费源护栏可用。
   - 默认 `smoke_iota3_free_source_fabric.py` 只使用 `csv/csv_mirror`，不得调用外部网站。
   - 只有显式 `--allow-external` 后才允许试运行 AKShare、BaoStock、TuShare 免费档、巨潮、交易所或国家统计局等外部免费源。
   - `--require-external` 在没有任何外部免费源成功执行时必须失败，避免把本地 fixture 当成真实免费源可用性结论。

141. Iota-3 免费源质量和授权判断可用。
   - 两个可用源一致且覆盖率达标时，dataset 可为 success/backup。
   - 冲突率超过阈值时，dataset 必须进入 warning 并记录 `conflict_rate_above_threshold`。
   - research_only/review_required 源在未获商业清晰授权前，不得被推荐为 primary_candidate；`--require-commercial-clearance` 打开时必须 blocked。

142. Iota-3 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/free-source-fabric-runs` 和 `/admin/free-source-fabric-results`。
   - `/admin/overview` 展示 free_source_24h_fabric_count、free_source_24h_fabric_blocked_count 和 latest_free_source_fabric_status。
   - Upsilon Free Sources 分组可展示 Free Source Fabric Runs 和 Free Source Fabric Results。

143. Iota-4 外部免费源真实 canary 可用。
   - `smoke_iota4_external_free_source_canary.py` 默认必须显式调用 AKShare 外部源，并通过 Iota-3 fabric 写入 `free_source_fabric_run` 和 `free_source_fabric_dataset_result`。
   - 成功标准是至少一个外部免费源真实执行、目标数据集覆盖率达到阈值、结果可被 Kappa 查询；fabric status 可为 warning，因为 research_only 授权风险必须继续暴露。
   - Iota-4 不新增表，不改写原始行情、生产供应商 pilot、账单、权限或租户数据。

144. Iota-4 live-only 和 compare-local 两种 canary 模式可用。
   - `live-only` 默认只跑 `akshare`，用于验证外部免费源可执行性、字段可解析和审计落库。
   - `compare-local` 默认跑 `csv/csv_mirror/akshare`，用于验证外部源能进入多源 fabric 比对；本地 fixture 不作为真实价格基准。
   - `min_source_count` 默认 live-only 为 1、compare-local 为 2，可由 CLI 显式覆盖。

145. Iota-4 商业边界判断可用。
   - AKShare 等免费源即使 canary 通过，也必须保持 `research_only` 或 license warning，不得直接推荐为 primary_candidate。
   - `--require-commercial-clearance` 打开时，research_only/review_required/free quota 未清晰授权的数据集必须失败或 blocked。
   - CLI 输出必须同时展示 canary 成功状态和 commercial_clearance，避免把技术成功误读成商业可生产。

146. Iota-4 接入现有 Kappa/Upsilon 查询面可用。
   - Kappa 通过 `/admin/free-source-fabric-runs` 可按 `requested_by=iota4` 查到真实外部 canary run。
   - Kappa 通过 `/admin/free-source-fabric-results` 可按 `source_code=akshare` 查到 daily_bar、security_master 和 trading_calendar 结果。
   - Upsilon Free Sources 分组无需新增表即可展示最新 Iota-4 run/result。

147. Iota-5 多免费源 adapter pool 可用。
   - Provider registry 必须支持 `baostock`、`tushare_free`、`cninfo_public`、`sse_public`、`szse_public` 和 `nbs_public`，不能再返回泛化的 provider_not_implemented。
   - BaoStock adapter 必须支持 explicit-symbol daily_bar/security_master/trading_calendar canary，并带 socket timeout，避免公网端口不可达时长时间挂住。
   - TuShare free adapter 必须支持 Pro HTTP token 模式；没有 `QDATA_TUSHARE_TOKEN` 或 CLI token 时必须 blocked，不能伪造免费源成功。
   - 官方公开源 adapter 必须返回结构化 scaffold-only 原因，等待 endpoint、授权和字段口径确认。

148. Iota-5 adapter pool smoke 可用。
   - `smoke_iota5_free_source_adapter_pool.py` 默认跑 akshare/baostock/tushare_free/sse_public/szse_public/cninfo_public，并写入 Iota-3 fabric run/result。
   - 当前本机没有 TuShare token 且 BaoStock socket 超时的情况下，smoke 必须输出 `iota5_free_source_adapter_pool=degraded`，并列出 `tushare_token_missing`、`baostock_source_failed` 和 `official_public_scaffold_pending`。
   - 配好 token 或网络恢复后，可用 `--require-ok` 把验收门槛提升为至少两个外部免费源真实成功。

149. Iota-5 商业和生产边界可用。
   - 多免费源即使技术 canary 成功，也仍必须是 research_only/review_required，不得直接晋级 primary_candidate。
   - `commercial_clearance=blocked` 必须在 CLI 输出和 Kappa 结果中可见。
   - 官方源 scaffold 不得抓取未确认授权的原始网页正文并写入生产表。

150. Iota-5 接入 Kappa/Upsilon 可用。
   - Kappa 可按 `requested_by=iota5` 查询 adapter pool run。
   - Kappa 可按 `source_code=baostock` 或 `source_code=tushare_free` 查询失败/降级原因。
   - Upsilon Free Sources 分组复用现有 fabric 表展示 Iota-5 run/result。

151. Kappa-5 免费源可靠性快照可用。
   - `free_source_reliability_snapshot` 必须按 source+dataset 记录 reliability_score、success_rate、coverage_rate、conflict_rate_bps、连续失败次数、授权状态、商业清晰度、降级原因和恢复动作。
   - `0034` 只追加评分快照，不改写 Iota-3 fabric、原始行情、真实供应商、账单、权限或生产事实。

152. Kappa-5 自动降级规则可用。
   - BaoStock 连接失败、TuShare token 缺失、official public scaffold、冲突率过高或商业授权未清晰时，必须进入 watch/degraded/rejected/research_only/backup，不得进入 commercial primary。
   - 连续失败次数必须影响 status 和 recommended_role；无近期观察且显式传入 source/dataset 时必须输出 no_data。

153. Kappa-5 CLI 和 smoke 可用。
   - `run_kappa5_free_source_reliability.py --resource score` 必须能从 recent fabric result 生成 snapshot。
   - `smoke_kappa5_free_source_reliability.py` 必须输出 snapshot_count、ready/watch/degraded/rejected/no_data 和分数范围。

154. Kappa-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/free-source-reliability`。
   - `/admin/overview` 展示 free_source_24h_reliability_count、free_source_24h_reliability_ready_count、free_source_24h_reliability_degraded_count、free_source_24h_reliability_rejected_count 和 latest_free_source_reliability_status。
   - Upsilon Free Sources 分组必须展示 Free Source Reliability 表。

155. Lambda-5 免费源恢复 run/action 可用。
   - `free_source_recovery_run` 必须记录 recovery_code、trigger_mode、as_of_date、lookback_hours、snapshot_count、action_count、retry/alert/manual_review/suppressed/blocked 计数和 evidence。
   - `free_source_recovery_action` 必须关联 source、dataset、Kappa-5 snapshot，并记录 action_type、status、severity、reason_code、retry_after_minutes、alert_id、degradation_reasons 和 recovery_actions。
   - `0035` 只追加恢复审计和 worker/alert 枚举，不改写 Kappa-5 snapshot、Iota-3 fabric、原始行情、真实供应商、账单、权限或生产事实。

156. Lambda-5 恢复策略可用。
   - `rejected` 或商业授权 blocked 的免费源必须进入 manual_review/high-critical 路径，并可生成 `free_source_recovery_required` 告警。
   - `degraded` 且可重试的免费源必须生成 retry_canary、next_retry_at 和退避时间。
   - `watch` 免费源只能 observe，不得触发生产 fallback 或商业 primary 推荐。
   - dry-run 必须只预览动作，不写恢复 run/action 或 alert。

157. Lambda-5 worker 和 Mu schedule 可用。
   - `WORKER_TASKS` 必须包含 `free_source_recovery`。
   - `run_lambda_worker.py --task free_source_recovery --dry-run` 必须能从 Kappa-5 snapshot 生成预览动作。
   - `worker_schedule` 默认包含 `mu_free_source_recovery_30m`，task_args 包含 lookback、max_actions、min_retry_score 和 write_alerts。

158. Lambda-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/free-source-recovery-runs` 和 `/admin/free-source-recovery-actions`。
   - `/admin/overview` 展示 free_source_24h_recovery_count、free_source_24h_recovery_action_count、free_source_24h_recovery_alert_count 和 latest_free_source_recovery_status。
   - Upsilon Free Sources 分组必须展示 Free Source Recovery Runs 和 Free Source Recovery Actions 表。

159. Mu-5 免费源恢复 execution 可用。
   - `free_source_recovery_execution` 必须记录 execution_code、action、execution_type、trigger_mode、status、Iota-5 fabric、approval、WeCom receipt、result_summary 和 evidence。
   - `retry_canary` 只有 Iota-5 pool status 为 ok 才能回写 recovered，degraded/failed 必须回写 failed。
   - `manual_review` 必须生成标准 automation action/approval；未显式允许企业微信外发时只写 blocked receipt。
   - Kappa/Upsilon 必须展示 `/admin/free-source-recovery-executions` 和 Free Source Recovery Executions 表。

160. Nu-5 免费源恢复健康快照可用。
   - `free_source_recovery_health_snapshot` 必须记录 pending action、pending retry/manual_review、execution/recovered/failed/suppressed/review_requested/blocked、failure_rate、approval pending/overdue、backlog、stale schedule、latest worker/schedule/execution status。
   - 健康状态必须能区分 healthy、warning、critical，并输出 health_issues 和 runbook_actions。
   - 只读取 Mu-5 action/execution、Omega approval 和 worker schedule/run 证据，不改写恢复 action、审批、行情、供应商、账单、权限或生产事实。

161. Nu-5 worker 和 Mu schedule 可用。
   - `WORKER_TASKS` 必须包含 `free_source_recovery_health`。
   - `run_lambda_worker.py --task free_source_recovery_health --dry-run` 必须能预览 health snapshot 且不写库。
   - `worker_schedule` 默认包含 `nu_free_source_recovery_health_15m`，task_args 包含 lookback、approval_sla、max_backlog、max_failure_rate 和 max_stale_minutes。
   - health snapshot 的 critical 必须映射为 worker task failed，warning 必须映射为 worker task warning。

162. Nu-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/free-source-recovery-health`。
   - `/admin/overview` 展示 latest_free_source_recovery_health_status、free_source_24h_recovery_health_count、free_source_recovery_overdue_approval_count 和 free_source_recovery_backlog_count。
   - Upsilon Free Sources 分组必须展示 Free Source Recovery Health 表，并能按 status/search 过滤。

163. Xi-5 免费源准入档案可用。
   - `free_source_admission_profile` 必须记录 source、license_type、license_status、commercial_clearance、redistribution_allowed、contract_status、contract_ref、terms_review_status、api_terms_url、rate_limit_per_min、daily_quota、max_allowed_role、reviewed_by 和 evidence。
   - 默认 profile 必须覆盖 csv、csv_mirror、akshare、baostock、tushare_free、cninfo_public、sse_public、szse_public 和 nbs_public。
   - 未确认商用许可、转授权、合同、条款或配额的免费源不得直接提升为商业生产主源。

164. Xi-5 source+dataset 准入快照可用。
   - `free_source_admission_snapshot` 必须按 source+dataset 输出 status、admission_role、法律/合同/配额字段、reliability_status、reliability_score、coverage_rate、conflict_rate_bps、blocking_issues 和 required_actions。
   - 只有合同 active、商用许可 clear、再分发 yes、条款 approved、限频/日配额齐全且 Kappa-5 可靠性达标，才允许 `admission_role=primary_candidate`。
   - no_data、blocked、review_required 必须保留可解释 blocking_issues。

165. Xi-5 worker 和 Mu schedule 可用。
   - `WORKER_TASKS` 必须包含 `free_source_admission_review`。
   - `run_lambda_worker.py --task free_source_admission_review --dry-run` 必须能预览准入快照且不写库。
   - `worker_schedule` 默认包含 `xi_free_source_admission_review_6h`，task_args 包含 lookback、validator/backup/primary score、coverage 和 conflict 阈值。
   - blocked/review_required/no_data 准入结论必须映射为 worker warning，而不是伪装成 success。

166. Xi-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/free-source-admission-profiles` 和 `/admin/free-source-admission`。
   - `/admin/overview` 展示 free_source_24h_admission_count、approved/conditional/review_required/blocked/no_data 和 free_source_primary_candidate_count。
   - Upsilon Free Sources 分组必须展示 Free Source Admission 和 Free Source Admission Profiles 表。

167. Omicron-5 真实主供应商合同 profile 可用。
   - `vendor_contract_profile` 必须记录 source、provider、profile、采购状态、合同状态、商用许可、再分发/缓存权、生产使用权、contract_ref、SLA、限频、日/月配额、账单口径、负责人、复核时间和 evidence。
   - 默认 `vendor_http` 合同模板必须保持 draft/review_required，不得在缺少正式合同引用、再分发授权、生产使用许可、SLA 和 quota 时成为主生产源。
   - 合同 profile 只保存合同引用、授权状态和证据元数据，不保存供应商 token 或原始响应正文。

168. Omicron-5 dataset entitlement 和采购 readiness 快照可用。
   - `vendor_contract_dataset_entitlement` 必须按 contract+source+dataset 记录 entitlement_status、allowed_role、商用/再分发/生产使用、delivery_mode、frequency、latency、endpoint_path、schema_status、field_mapping_status、限频、quota、SLA、blocking_issues 和 required_actions。
   - `vendor_procurement_readiness_snapshot` 必须按 source+dataset 输出 status、procurement_role、readiness_score、合同字段、授权字段、SLA/quota、Pi/Epsilon-3/Zeta-3/Eta-3/Theta-3 live 证据、blocking_issues 和 required_actions。
   - 只有采购 active、合同 active、商用 clear、再分发 yes、生产使用允许、合同引用存在、dataset entitlement active、schema/field mapping validated、限频/日配额/SLA 齐全且 live 证据未 blocked，才允许 `procurement_role=primary_candidate`。

169. Omicron-5 worker 和 Mu schedule 可用。
   - `WORKER_TASKS` 必须包含 `vendor_contract_readiness_review`。
   - `run_lambda_worker.py --task vendor_contract_readiness_review --dry-run` 必须能预览采购 readiness 且不写库。
   - `worker_schedule` 默认包含 `omicron5_vendor_contract_readiness_6h`，task_args 包含 min_sla_uptime_pct、min_rate_limit_per_min 和 require_live_evidence。
   - review_required/blocked/no_contract 采购结论必须映射为 worker warning，而不是伪装成 success。

170. Omicron-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-contract-profiles`、`/admin/vendor-contract-entitlements` 和 `/admin/vendor-procurement-readiness`。
   - `/admin/overview` 展示 vendor_contract_profile_count、vendor_active_contract_count、vendor_24h_procurement_readiness_count、vendor_24h_procurement_ready_count、vendor_24h_procurement_review_required_count、vendor_24h_procurement_blocked_count、latest_vendor_procurement_status 和 vendor_procurement_primary_candidate_count。
   - Upsilon Vendor 分组必须展示 Vendor Contract Profiles、Vendor Contract Entitlements 和 Vendor Procurement Readiness 表。

171. Pi-5 授权主供应商 promotion run 可用。
   - `vendor_primary_promotion_run` 必须记录 source、primary_source、as_of_date、requested_by、trigger_mode、environment、promotion_scope、status、apply_mode、routing_change_allowed/applied、dataset_count、approved/pending/blocked/applied 计数、required_windows、签批策略、target_priority、promotion_score、blocking_issues、required_actions 和 evidence。
   - 默认必须为 review-only，不得在缺少显式 apply 开关时改写 `source_priority`。

172. Pi-5 dataset promotion result 和证据闸门可用。
   - `vendor_primary_promotion_dataset_result` 必须按 source+dataset 记录 Omicron-5 procurement snapshot、Pi readiness review、Theta-3 canary/full-market pilot、当前 primary source、当前 priority、目标 priority、promotion_role、routing_change_allowed/applied、blocking_issues 和 required_actions。
   - 只有 Omicron-5 `ready/primary_candidate`、Pi 5/20/60 `ready/approve_primary/primary`、Theta-3 canary success、默认 full-market success 和签批 approved 全部满足，才允许 `approved_for_primary`。
   - 缺少采购、Pi readiness、canary、full-market 或签批证据时，必须输出 blocked/canary_required/full_market_required/pending_signoff，不得默默放行。

173. Pi-5 worker 和 Mu schedule 可用。
   - `WORKER_TASKS` 必须包含 `vendor_primary_promotion_review`。
   - `run_lambda_worker.py --task vendor_primary_promotion_review --dry-run` 必须能预览 promotion 结论且不写库。
   - `worker_schedule` 默认包含 `pi5_vendor_primary_promotion_6h`，task_args 包含 promotion_scope、require_full_market、require_signoff、apply_routing 和 target_priority。
   - blocked/canary_required/full_market_required/pending_signoff promotion 结论必须映射为 worker warning，而不是伪装成 success。

174. Pi-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-primary-promotions` 和 `/admin/vendor-primary-promotion-results`。
   - `/admin/overview` 展示 vendor_24h_primary_promotion_count、approved/blocked/applied、latest_vendor_primary_promotion_status 和 vendor_primary_promotion_routing_allowed_count。
   - Upsilon Vendor 分组必须展示 Vendor Primary Promotions 和 Vendor Primary Promotion Results 表。

175. Rho-5 主源切换后 monitor run 可用。
   - `vendor_post_promotion_monitor_run` 必须记录 promotion、source、primary_source、as_of_date、requested_by、trigger_mode、environment、monitor_scope、status、rollback_mode、require_applied_promotion、rollback_allowed/applied、dataset 计数、shadow 阈值、monitor_score、blocking_issues、required_actions 和 evidence。
   - 没有 applied Pi-5 promotion 时必须明确输出 `no_applied_promotion`，不得返回空白或静默 success。

176. Rho-5 dataset post-promotion result 和回滚闸门可用。
   - `vendor_post_promotion_dataset_monitor` 必须按 source+dataset 记录 Pi-5 promotion/result、当前 primary source、前一 primary source、shadow_status、conflict/failure/stale 指标、rollback_allowed/applied、blocking_issues 和 required_actions。
   - 只有当前 route 确认为 promoted source、shadow 指标超过阈值且前一主源存在时，才允许 `rollback_recommended`。
   - 默认 review-only、dry-run 或定时任务不得改写 `source_priority`；只有显式 `--apply-rollback` / `QDATA_RHO5_APPLY_ROLLBACK=true` 才允许受控回滚。

177. Rho-5 worker 和 Mu schedule 可用。
   - `WORKER_TASKS` 必须包含 `vendor_post_promotion_monitor`。
   - `run_lambda_worker.py --task vendor_post_promotion_monitor --dry-run` 必须能预览 monitor 结论且不写库。
   - `worker_schedule` 默认包含 `rho5_post_promotion_monitor_1h`，task_args 包含 monitor_scope、require_applied_promotion、apply_rollback、shadow_window_hours 和阈值。
   - no_applied_promotion、blocked、warning、rollback_recommended 必须映射为 worker warning，而不是伪装成 success。

178. Rho-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-post-promotion-monitors` 和 `/admin/vendor-post-promotion-results`。
   - `/admin/overview` 展示 vendor_24h_post_promotion_monitor_count、healthy、rollback_recommended、rolled_back、no_applied、latest_vendor_post_promotion_status 和 vendor_post_promotion_rollback_allowed_count。
   - Upsilon Vendor 分组必须展示 Vendor Post Promotion Monitors 和 Vendor Post Promotion Results 表。

179. Sigma-5 主供应商生产稳定性 snapshot 可用。
   - `vendor_primary_stability_snapshot` 必须记录 source、primary_source、promotion、post_promotion_monitor、SLA 阈值、dataset 计数、API request/fail/timeout/latency/cost、worker/scheduler、capacity alert、stability_score、blocking_issues 和 required_actions。
   - 没有 applied Pi-5 promotion 或当前 `source_priority` 未切为供应商主源时，必须明确输出 `no_primary_promotion`，不得返回空白或 healthy。

180. Sigma-5 dataset 级稳定性明细可用。
   - `vendor_primary_stability_dataset_snapshot` 必须按 source+dataset 记录授权状态、allowed_role、production_use_allowed、schema_status、当前主源、当前 priority、promotion 状态、post-promotion 状态、API SLA 指标和阻断原因。
   - 已切主 dataset 必须按 success_rate/error_rate/timeout_rate/latency_p95/cost 阈值输出 healthy/warning/critical。

181. Sigma-5 worker 和 Mu schedule 可用。
   - `WORKER_TASKS` 必须包含 `vendor_primary_stability_monitor`。
   - `run_lambda_worker.py --task vendor_primary_stability_monitor --dry-run` 必须能预览稳定性结论且不写库。
   - `worker_schedule` 默认包含 `sigma5_vendor_primary_stability_1h`，task_args 包含 monitor_scope、lookback_hours、capacity_window_days、SLA/cost/scheduler/Rho 阈值。
   - `critical` 必须映射为 worker failed；no_primary_promotion、blocked、warning 必须映射为 worker warning。

182. Sigma-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-primary-stability` 和 `/admin/vendor-primary-stability-datasets`。
   - `/admin/overview` 展示 vendor_24h_primary_stability_count、healthy/warning/critical/no_primary、latest_vendor_primary_stability_status、latest role、primary dataset、score、cost、scheduler lag 和 backlog。
   - Upsilon Vendor 分组必须展示 Vendor Primary Stability 和 Vendor Primary Stability Datasets 表。

183. Tau-5 主供应商成本优化 snapshot 可用。
   - `vendor_cost_optimization_snapshot` 必须记录 source、primary_source、Sigma-5 stability、预算阈值、forecast window、dataset 计数、当前/预测请求、成本、quota、推荐 primary/backup/free 权重、optimization_score、blocking_issues 和 required_actions。
   - 没有 applied Pi-5 promotion 或当前 `source_priority` 未切为供应商主源时，必须明确输出 `no_primary_promotion`，且 `recommended_primary_weight_pct=0`。

184. Tau-5 dataset route plan 和 budget stress 可用。
   - `vendor_route_weight_plan` 必须按 source+dataset 记录当前主源、当前 priority、稳定性状态、合同/授权、unit_cost、monthly_fee、forecast request/cost、quota 水位、推荐权重、routing_change_allowed 和阻断原因。
   - `vendor_budget_stress_dataset_snapshot` 必须按 dataset 和 stress_multiplier 输出预算占用、日/月 quota 水位、quota_exhaustion_days、recommended_action、blocking_issues 和 required_actions。

185. Tau-5 worker 和 Mu schedule 可用。
   - `WORKER_TASKS` 必须包含 `vendor_cost_optimizer`。
   - `run_lambda_worker.py --task vendor_cost_optimizer --dry-run` 必须能预览成本优化结论且不写库。
   - `worker_schedule` 默认包含 `tau5_vendor_cost_optimizer_6h`，task_args 包含 optimization_scope、lookback_hours、forecast_window_days、monthly_budget_amount、budget/quota/stability 阈值、cost_safety_margin_pct、default_unit_cost 和 stress_multipliers。
   - `blocked/over_budget` 必须映射为 worker failed；no_primary_promotion、quota_risk、watch 必须映射为 worker warning。

186. Tau-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-cost-optimizations`、`/admin/vendor-route-weight-plans` 和 `/admin/vendor-budget-stress`。
   - `/admin/overview` 展示 vendor_24h_cost_optimization_count、optimized、over_budget、quota_risk、no_primary、latest_vendor_cost_optimization_status、latest role、primary/backup/free weight、budget usage、quota usage 和 optimization score。
   - Upsilon Vendor 分组必须展示 Vendor Cost Optimizations、Vendor Route Weight Plans 和 Vendor Budget Stress 表。

187. Upsilon-5 路由权重执行 run/dataset/stage 可用。
   - `vendor_route_weight_execution_run` 必须记录 execution_mode、approval_policy、approval_status、rollout_policy、stage、目标/实际权重、dataset 计数、阻断原因和 required_actions。
   - `vendor_route_weight_execution_dataset` 必须按 source+dataset 记录 Tau-5 plan、当前主源、approval、target/applied 权重、routing_change_applied、rollback_applied 和阻断原因。
   - `vendor_route_weight_rollout_stage` 必须记录 stage_sequence、gate_status、目标权重、是否允许/应用路由变更和 required_actions。

188. Upsilon-5 审批、灰度和回滚护栏可用。
   - 默认 `review_only` + `approval_status=pending` 不得写入 active policy。
   - 没有 applied Pi-5 promotion 或 Tau-5 可执行 primary weight 时，必须输出 `no_primary_promotion`，且 applied primary weight 为 0。
   - 只有 `execution_mode=apply` 且审批通过时才允许写入 `source_route_weight_policy`；rollback 请求必须留下 rollback_recommended/rolled_back 证据。

189. Upsilon-5 worker 和 Mu schedule 可用。
   - `WORKER_TASKS` 必须包含 `vendor_route_weight_executor`。
   - `run_lambda_worker.py --task vendor_route_weight_executor --dry-run` 必须能预览执行结论且不写 policy。
   - `worker_schedule` 默认包含 `upsilon5_vendor_route_weight_executor_1h`，task_args 包含 execution_scope、execution_mode、approval_policy、approval_status、rollout_policy、rollout_stages、current_stage_sequence 和 rollback_requested。
   - `blocked/rollback_recommended` 必须映射为 worker failed；pending_approval、review_required、no_primary_promotion 和 staged 必须映射为 worker warning。

190. Upsilon-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/vendor-route-executions`、`/admin/vendor-route-execution-datasets`、`/admin/vendor-route-rollout-stages` 和 `/admin/source-route-weight-policies`。
   - `/admin/overview` 展示 vendor_24h_route_execution_count、pending/staged/applied/blocked、latest_vendor_route_execution_status、latest approval、applied primary weight、current stage 和 active policy 数。
   - Upsilon Vendor 分组必须展示 Vendor Route Executions、Vendor Route Execution Datasets、Vendor Route Rollout Stages 和 Source Route Weight Policies 表。

191. Phi-5 route policy resolver 可用。
   - `source_route_decision_audit` 必须记录 dataset、requested/selected/final source、decision_context、route_mode、decision_status、fallback、row_count 和 duration。
   - 没有 PostgreSQL DSN 或没有 active policy 时，resolver 必须保持 requested source 默认路径。
   - 存在 active `source_route_weight_policy` 时，resolver 必须按 deterministic bucket 稳定选择 primary/backup/free/fallback 候选源。

192. Phi-5 采集路由和 fallback 可用。
   - `sync_daily_market(... use_route_policy=True)` 必须使用 route resolver 选择 provider，并在结果中返回 `route_decision`。
   - selected provider 失败或返回空数据时，必须尝试 fallback 并记录 `fallback_success` 或 `fallback_failed`。
   - 默认 `use_route_policy=False` 时，原采集行为必须保持兼容。

193. Phi-5 API 路由元信息可用。
   - `/price`、`/matrix` 和 `/constraints` 必须在 `meta.route_policy` 返回 route_mode、decision_status、selected_source_code、final_source_code 和 fallback_applied。
   - API 查询必须写入 `source_route_decision_audit`，并把 route summary 合并进 `api_request_audit.request_summary`。
   - 路由审计失败不得破坏原有 API 查询响应。

194. Phi-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/source-route-decisions`，并支持 decision/source/context/mode/status/role 等过滤。
   - `/admin/overview` 展示 source_route_24h_decision_count、source_route_24h_fallback_count、latest_source_route_decision_status 和 latest_source_route_final_source_code。
   - Upsilon Vendor 分组必须展示 Source Route Decisions 表。

195. Chi-5 route feedback health monitor 可用。
   - `source_route_health_snapshot` 必须按 source+dataset 记录 request/success/failed/fallback/empty、success_rate、failure_rate、fallback_rate、empty_rate、latency_p95_ms、阈值、health_issues 和 runbook_actions。
   - `run_chi5_route_feedback.py --resource check` 必须能从 `source_route_decision_audit` 生成 healthy/degraded/circuit_open 快照。
   - 没有足够 request 时必须给出可解释的 healthy/no issue 结果，不得返回空白页面或破坏 API 查询。

196. Chi-5 自动熔断和恢复探测可用。
   - 当 success/failure/fallback/empty/latency 任一阈值越界时，必须写入或更新 `source_route_circuit_breaker`，并设置 `status=open` 与 `open_until`。
   - open circuit 在 `open_until` 之前必须保持 open；恢复窗口健康时才允许 close，并写入 `source_route_recovery_probe status=recovered`。
   - recovery probe 失败必须保留 `status=failed` 和 decision_summary，不能静默恢复。

197. Chi-5 接入 Phi-5 resolver、Worker 和 Mu 可用。
   - Phi-5 resolver 必须跳过 open circuit 候选源，并在全部候选都 open 时 fail-open 且返回 `circuit_fail_open=true`。
   - `WORKER_TASKS` 必须包含 `source_route_feedback_monitor`；dry-run 不得写库。
   - `worker_schedule` 默认包含 `chi5_source_route_feedback_15m`，task_args 包含 lookback、成功率、失败率、fallback、空响应、延迟、open window 和 recovery probe 阈值。

198. Chi-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/source-route-health`、`/admin/source-route-circuit-breakers` 和 `/admin/source-route-recovery-probes`。
   - `/admin/overview` 展示 source_route_24h_health_count、source_route_24h_unhealthy_count、latest_source_route_health_status、source_route_open_circuit_count、source_route_24h_recovery_probe_count 和 recovered probe 数。
   - Upsilon Vendor 分组必须展示 Source Route Health、Source Route Circuit Breakers 和 Source Route Recovery Probes 表。

199. Psi-5 route incident action 审计可用。
   - `source_route_incident_action` 必须记录 incident action、automation run/action、source_signal_type、dataset/source、breaker/snapshot/probe、状态、owner、health_issues、planned_effect、executed_effect 和 rollback_hint。
   - `circuit_open` 必须映射为 `degrade_vendor` 高风险动作，且默认 `status=approval_required`，不得未经审批改写 `source_priority`、policy、合同或授权。
   - `recovery_failed` 必须生成 owner 通知动作；`recovered` 必须生成恢复监控动作，并通过 idempotency 避免重复执行。

200. Psi-5 Worker/Mu 可用。
   - `WORKER_TASKS` 必须包含 `route_incident_automation`；dry-run 不得写库。
   - `worker_schedule` 默认包含 `psi5_route_incident_automation_15m`，task_args 包含 lookback、max_actions、execution_mode、approve_high_risk、owner 和 include_recovered。
   - 非 dry-run 必须写入 automation_run、automation_action 和 source_route_incident_action，并把审批/跳过/失败计数映射到 worker warning/failed。

201. Psi-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/source-route-incident-actions`，并支持 incident/action/run/signal/source/dataset/status/owner 等过滤。
   - `/admin/overview` 展示 source_route_24h_incident_action_count、source_route_pending_incident_action_count 和 latest_source_route_incident_action_status。
   - Upsilon Vendor 分组必须展示 Source Route Incident Actions 表。

202. Psi-5 smoke 可复现。
   - `scripts/smoke_psi5_route_incident_automation.py` 必须串起 failed route decision、Chi-5 open circuit、Psi-5 approval-required action、success route decision、Chi-5 recovered probe 和 Psi-5 recovered action。
   - smoke 可重复运行；若恢复动作已有成功记录，允许 idempotency skip，但必须保留 recovered incident action 查询结果。

203. Omega-5 route incident control 审计可用。
   - `source_route_incident_control` 必须记录 control、incident action、automation action、approval、dispatch、WeCom receipt、execution attempt、rollback、control_stage、owner/requested_by 和 planned/executed/rollback evidence。
   - 高风险 `circuit_open` action 必须先进入 approval pending；pending/rejected 时不得执行真实动作。
   - 默认未显式允许外发企业微信时，不得产生真实外部副作用，但必须保留 blocked/success receipt 和 acknowledged dispatch 审计。

204. Omega-5 Worker/Mu 可用。
   - `WORKER_TASKS` 必须包含 `route_incident_control`；dry-run 不得写库。
   - `worker_schedule` 默认包含 `omega5_route_incident_control_15m`，task_args 包含 lookback、max_controls、execution_mode、auto_approve、requested_by、approval_sla、notify_wecom、allow_wecom_external 和 create_rollback。
   - 非 dry-run 必须把 approval pending、auto approval、execution attempt、rollback plan 和 warning/failed 计数映射到 worker 结果。

205. Omega-5 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/source-route-incident-controls`，并支持 control/incident/action/run/signal/source/dataset/stage/approval/dispatch/receipt/attempt/rollback 等过滤。
   - `/admin/overview` 展示 source_route_24h_incident_control_count、source_route_pending_incident_control_count 和 latest_source_route_incident_control_stage。
   - Upsilon Vendor 分组必须展示 Source Route Incident Controls 表。

206. Omega-5 smoke 可复现。
   - `scripts/smoke_omega5_route_incident_control.py` 必须串起 failed route decision、Chi-5 open circuit、Psi-5 approval-required action、Omega-5 pending approval、企业微信 receipt、dispatch audit、rollback plan、auto approval 和 Omega execution attempt。
   - smoke 默认不外发企业微信；只有显式 `--allow-wecom-external` 且 webhook 环境变量存在时才允许真实发送。
   - smoke 可重复运行；重复控制必须幂等更新同一 incident action 的 control，不得重复真实执行外部动作。

207. Alpha-6 route incident control health 审计可用。
   - `source_route_incident_control_health_snapshot` 必须记录 snapshot、control_count、pending_control_count、approval_pending/overdue、企业微信 blocked/success receipt、blocked_receipt_rate、execution_failure_rate、missing_rollback、stale_schedule、latest worker/schedule/control stage、health_issues、runbook_actions 和 evidence。
   - `receipt_status=blocked` 在本机/未配置 webhook 时只能升级为 warning；approval SLA overdue、执行失败率超阈值、缺回滚或 stale schedule 必须升级为 critical。

208. Alpha-6 Worker/Mu 可用。
   - `WORKER_TASKS` 必须包含 `route_incident_control_health`；dry-run 不得写 snapshot。
   - `worker_schedule` 默认包含 `alpha6_route_incident_control_health_15m`，task_args 包含 lookback、approval_sla、max_pending_controls、max_failed_execution_rate、max_blocked_receipt_rate、max_stale_minutes、requested_by、environment 和 control_schedule_code。
   - 非 dry-run 必须把 healthy/warning/critical 映射到 success/warning/failed worker 结果。

209. Alpha-6 接入 Kappa/Upsilon 可用。
   - Kappa 支持 `/admin/source-route-incident-control-health`，并支持 snapshot/status/requested_by/trigger/environment/schedule/date 分页过滤。
   - `/admin/overview` 展示 source_route_latest_control_health_status、source_route_control_health_issue_count、source_route_control_health_overdue_approval_count 和 source_route_control_health_blocked_receipt_count。
   - Upsilon Vendor 分组必须展示 Source Route Incident Control Health 表。

210. Alpha-6 smoke 可复现。
   - `scripts/smoke_alpha6_route_incident_control_health.py` 必须复用 Omega-5 控制闭环证据并写入健康快照。
   - smoke 必须输出 `alpha6_route_incident_control_health_smoke=ok`，包含 status、snapshot_code、controls、pending、blocked_receipts、failed_execution、stale 和 latest_stage。
   - smoke 不得产生真实企业微信外发、审批、执行或回滚副作用。

211. Beta-6 route incident operation queue 可用。
   - `source_route_incident_operation_batch` 必须记录 batch、candidate/eligible、approved/rejected/held/skipped/failed、通知分组、suppressed notification、stress dataset/source/scenario、operation_issues、required_actions 和 evidence。
   - `source_route_incident_operation_item` 必须记录 control/approval、dataset/source/signal/safety、审批前后状态、operation_decision、operation_status、notification_group_key、suppress_notification、priority_score 和 evidence。

212. Beta-6 批量审批和通知降噪安全可控。
   - 默认 `approval_decision=hold`、`apply_decisions=false`，只能生成队列/预览，不得改变 Omega approval 状态。
   - 显式 apply approve/reject 时必须通过 Omega approval 控制面更新审批状态，并同步 route incident control 的 approval_status/control_stage。
   - `dedupe_digest` 必须保留每个分组的首条通知证据，重复非 critical 通知进入 suppressed audit；不得默认外发企业微信。

213. Beta-6 Worker/Mu 和压测证据可用。
   - `WORKER_TASKS` 必须包含 `route_incident_operations`。
   - `worker_schedule` 默认包含 `beta6_route_incident_operations_30m`，task_args 包含 lookback、max_controls、approval_decision、apply_decisions、requested_by、environment、notification_policy、stress_scope、notify_wecom 和 allow_wecom_external。
   - full_market/smoke 压测必须输出 scenario_count、dataset_count、source_count 和 capped/缺数据问题，不得制造真实全市场故障。

214. Beta-6 接入 Kappa/Upsilon 且 smoke 可复现。
   - Kappa 支持 `/admin/source-route-incident-operation-batches` 和 `/admin/source-route-incident-operation-items`，并支持 batch/status/requested_by/trigger/environment/operation/decision/notification/stress/date 分页过滤。
   - `/admin/overview` 展示 source_route_latest_operation_status、source_route_operation_queue_count、source_route_operation_suppressed_notification_count 和 source_route_operation_stress_scenario_count。
   - Upsilon Vendor 分组必须展示 Source Route Incident Operation Batches 和 Source Route Incident Operation Items。
   - `scripts/smoke_beta6_route_incident_operations.py` 必须造 pending route control，再输出 `beta6_route_incident_operations_smoke=ok`，包含 status、batch_code、eligible、approved、suppressed、stress_scenarios 和 items。

215. Gamma-6 route incident writable approval API 可用。
   - `source_route_incident_approval_command` 必须记录 command、idempotency_key、requested_by/principal_code、decision、status、scope、required_approvals、approval_count、quorum_status、target/applied/held/rejected/skipped/failed 计数、evidence 和 response_payload。
   - `source_route_incident_approval_command_item` 必须记录 control/approval、dataset/source/signal/safety、审批前后状态、signer、signature_count、required_approvals、item_status 和 evidence。
   - `source_route_incident_approval_signature` 必须记录 signer、decision、idempotency_key、signature_code、status 和 signed_at，且同一 control+decision+signer 不得重复生效。

216. Gamma-6 多审批人 quorum 和幂等安全可控。
   - `required_approvals > active_signature_count` 时只能返回 `pending_quorum`，不得改写 Omega approval 或 route incident control。
   - quorum 满足后 approve/reject 必须通过 Omega `decide_automation_approval` 改写审批状态，并同步 control 的 `approval_status/control_stage`。
   - 同一 `idempotency_key` 重放必须返回原 command，不得创建重复 command/item/signature。

217. Gamma-6 接入 Kappa/Upsilon 且 POST 受 admin 保护。
   - POST `/admin/source-route-incident-approval-commands` 必须要求 admin scope 和 bearer token。
   - Kappa 支持 approval commands/items/signatures 三个 GET endpoint，并支持 command/status/decision/principal/quorum/control/approval/signer/date 分页过滤。
   - Upsilon Vendor 分组必须展示 Source Route Incident Approval Commands、Command Items、Signatures，并在 Operation Items 行内展示 Approve/Reject/Hold 操作按钮。

218. Gamma-6 smoke 可复现。
   - `scripts/smoke_gamma6_route_incident_approval_api.py` 必须造 pending route control，通过真实 HTTP POST 输出 `first=pending_quorum`、`second=applied`、`quorum=met`、`signatures>=2`、`approved=approved`。
   - smoke 不得产生真实企业微信外发或真实 route policy 改写副作用。

219. Delta-6 route incident approval governance schema 可用。
   - `source_route_incident_approval_role_binding` 必须记录 principal、role、dataset/source/safety scope、status、有效期、evidence，且同一 active principal+role+scope 不得重复。
   - `source_route_incident_approval_policy` 必须记录 min_approvals、职责分离、高风险风控审批、HMAC 签名、timeout、replay、timestamp skew 和 escalation owner 策略。
   - `source_route_incident_approval_callback` 必须记录 provider、nonce、request_hash、signature_status、governance_status、policy/binding/command 引用、target、decision、signer、脱敏 payload 和 response evidence。
   - `source_route_incident_approval_escalation` 必须记录 timeout、quorum stalled、policy denied、missing binding、invalid signature、replay rejected 和 cancel requested 的升级证据。

220. Delta-6 企业微信签名回调安全可控。
   - `POST /webhooks/wecom/source-route-incident-approval-callbacks` 不要求 Bearer token，但必须验证 `X-QData-Timestamp`、`X-QData-Nonce` 和 `X-QData-Signature`。
   - 同一 provider+nonce 重放必须返回 `replay_rejected` 并写入 replay escalation，不得创建重复 Gamma-6 签批。
   - HMAC 密钥只允许来自 `QDATA_DELTA6_WECOM_CALLBACK_SECRET`，不得写入 DB、CLI、Kappa API 或 Upsilon HTML。

221. Delta-6 RBAC、职责分离、quorum 和升级可控。
   - 签批人必须匹配 scoped `route_approver` 或 `route_risk_admin` 角色；高风险/critical policy 要求风控管理员时普通审批人不得通过。
   - 开启 `require_distinct_requester` 时，`signer_code == requested_by` 必须返回 `denied`，不得进入 Gamma-6。
   - 治理通过后才允许调用 Gamma-6；第一签不足 quorum 必须保持 `pending_quorum`，第二签满足 quorum 后才通过 Omega approval 控制面 applied。
   - pending command 超过 policy timeout 必须写入 `approval_timeout` escalation；显式 cancel 必须写入 `cancel_requested` escalation 并同步 control/approval cancelled 状态。

222. Delta-6 接入 Kappa/Upsilon/API smoke 可复现。
   - Kappa 支持 role bindings、policies、callbacks、escalations 四个 GET endpoint，并支持 role/policy/callback/provider/signature/governance/reason/owner/date 分页过滤。
   - `/admin/overview` 展示 approval role/policy 数、latest callback status、24h verified/replay/denied callback 和 open escalation 指标。
   - Upsilon Vendor 分组必须展示 Source Route Incident Approval Role Bindings、Policies、Callbacks、Escalations。
   - `scripts/smoke_delta6_route_incident_approval_governance.py` 必须通过真实 HTTP callback 输出 denied、pending_quorum、timeout escalation、replay_rejected 和 applied。

223. Epsilon-6 route incident approval resilience schema 可用。
   - `source_route_incident_approval_lock_event` 必须记录 lock_scope、lock_key、provider、nonce、request_hash、target、signer、lock_status、held_ms、concurrency_token 和 evidence。
   - `source_route_incident_approval_state_transition` 必须记录 callback/command/target、requested_decision、approval/control 前后状态、transition_status、reason_code 和 state_version。
   - `source_route_incident_approval_audit_hash` 必须记录 chain_scope、sequence_no、entity_type/code/id、previous_hash、payload_hash、entry_hash、canonical_payload 和 verification_status。
   - `source_route_incident_approval_sla_action` 与 `source_route_incident_approval_recovery_drill` 必须记录 SLA planned action 和恢复演练检查证据，且默认无外部副作用。

224. Epsilon-6 并发一致性和状态机守卫可控。
   - 同一 approval target 的回调必须使用 deterministic advisory lock key，拿不到锁时返回 `lock_busy` 并写入 lock event，不得进入 Delta-6/Gamma-6。
   - pending/unknown 目标允许 approve/reject/hold；approved/rejected/cancelled/expired 终态目标必须返回 `state_blocked` 和 `invalid_terminal_state`。
   - Epsilon-6 只在 Delta-6/Gamma-6/Omega 前后增加锁、状态和审计证据，不绕过原审批控制面。

225. Epsilon-6 不可变审计、SLA 自动处置和恢复演练可复现。
   - 每个 callback/state transition/SLA action/recovery drill 必须进入 audit hash chain，`verify_approval_audit_chain` 能校验 previous_hash、payload_hash 和 entry_hash。
   - SLA 自动化必须读取 Delta-6 open escalation 并生成 planned action，不外发企业微信、不执行真实 route 变更。
   - recovery drill 必须验证 DB reconnect、hash chain、lock key deterministic 和状态机终态守卫，并写入 drill 审计。

226. Epsilon-6 接入 Kappa/Upsilon/API smoke 可复现。
   - API signed/admin callback 均必须调用 Epsilon-6 wrapper，再进入 Delta-6 签名治理。
   - Kappa 支持 lock events、state transitions、audit chain、SLA actions、recovery drills 五个 GET endpoint，并支持 code/status/reason/target/date 分页过滤。
   - `/admin/overview` 展示 24h lock/busy/state/blocked、audit hash、broken hash、planned SLA action 和 latest recovery drill 指标。
   - Upsilon Vendor 分组必须展示 Source Route Incident Approval Lock Events、State Transitions、Audit Chain、SLA Actions、Recovery Drills。
   - `scripts/smoke_epsilon6_route_incident_approval_resilience.py` 必须通过真实 HTTP callback 输出 pending_quorum、applied、terminal block、audit_broken=0、SLA actions 和 recovery drill。

227. Epsilon-6 Worker/Mu 长期值守可复现。
   - `WORKER_TASKS` 必须包含 `route_incident_approval_resilience`。
   - `worker_schedule` 默认包含 `epsilon6_route_incident_approval_resilience_15m`，task_args 包含 `epsilon6_sla_automation`、`epsilon6_hash_verify`、`epsilon6_recovery_drill`、`epsilon6_requested_by` 和 `epsilon6_environment`。
   - dry-run 不得写 Epsilon-6 表；非 dry-run 必须校验 audit chain、生成 planned SLA action、写 recovery drill。
   - hash chain 或 recovery drill 失败必须映射为 worker failed；SLA planned action 必须映射为 worker warning；Mu tick 必须记录 `lock_acquired=True` 和 `worker_run_id`。

228. Zeta-6 route incident approval release schema 可用。
   - `source_route_incident_approval_release_preflight` 必须记录 environment、status、release_version、check_count、passed/warning/failed count、dual_secret_enabled、audit_broken_count、latest_recovery_drill_status、checks 和 evidence。
   - `source_route_incident_approval_secret_rotation` 必须记录 current/next label、rotation_phase、verified_secret_label、nonce、request_hash、signature_digest 和 evidence，不得记录密钥原文。
   - `source_route_incident_approval_concurrency_test` 必须记录 target_scope、callback_count、success/locked/blocked/replay/failed count 和 max_worker_threads。
   - `source_route_incident_approval_audit_export` 必须记录 chain_scope/target、included_entity_count、broken_hash_count、package_hash 和 export_payload。

229. Zeta-6 API/Kappa/Upsilon 发布门禁可复现。
   - signed/admin callback 必须先尝试 current secret，再尝试 `QDATA_ZETA6_WECOM_CALLBACK_SECRET_NEXT`；命中 next 时必须用 next secret 交给 Epsilon-6/Delta-6 复验。
   - API 响应、CLI、Kappa 和 Upsilon 不得暴露 current/next secret 原文，只能展示 label、digest tail、request hash 等摘要。
   - Kappa 支持 release preflights、secret rotations、concurrency tests、audit exports 四个 GET endpoint。
   - Upsilon Vendor 分组必须展示 Source Route Incident Approval Release Preflights、Secret Rotations、Concurrency Tests、Audit Exports。

230. Zeta-6 Worker/Mu 和 smoke 可复现。
   - `WORKER_TASKS` 必须包含 `route_incident_approval_release`。
   - `worker_schedule` 默认包含 `zeta6_route_incident_approval_release_30m`，task_args 包含 `zeta6_environment`、`zeta6_release_version`、`zeta6_requested_by`、`zeta6_require_dual_secret` 和 `zeta6_export_audit`。
   - dry-run 不得写 Zeta-6 表；非 dry-run 必须写 preflight，并在启用时写 audit export。
   - preflight failed 或 audit export broken hash 必须映射为 worker failed；preflight warning 或 audit export warning 必须映射为 worker warning。
   - `scripts/smoke_zeta6_route_incident_approval_release.py` 必须输出 preflight、rotation、concurrency、export 和 package_hash。

231. Eta-6 真实供应商生产主源闭环 schema 可用。
   - `vendor_production_source_run` 必须记录 source、primary_source、environment、closure_scope、closure_mode、status、production_role、dataset 计数、ready/blocked 计数、live env presence、生产评分和脱敏 evidence。
   - `vendor_production_source_dataset_check` 必须记录每个 dataset 的 Omicron-5 合同/entitlement、Theta-3 pilot、Pi-5 promotion、Sigma-5 stability、Tau-5 cost、Upsilon-5 route execution 和 rollback guard 证据。
   - `vendor_production_source_decision` 必须记录 profile/env、contract、pilot、promotion、stability、cost、route、rollback 和 final_decision 的 status、severity、summary、blocking_issues 和 required_actions。
   - 任何表、CLI、Kappa API 或 Upsilon HTML 都不得保存或输出 `QDATA_VENDOR_TOKEN` 原文、Authorization header 或原始供应商响应正文。

232. Eta-6 API/Kappa/Upsilon 生产闭环可复现。
   - Kappa 支持 `/admin/vendor-production-source-runs`、`/admin/vendor-production-source-dataset-checks`、`/admin/vendor-production-source-decisions` 三个 GET endpoint，并支持 code/source/status/role/environment/date 分页过滤。
   - `/admin/overview` 展示 24h production source count、ready、blocked、latest status、role、score 和 live env presence。
   - Upsilon Vendor 分组必须展示 Vendor Production Source Runs、Vendor Production Source Dataset Checks、Vendor Production Source Decisions。
   - CLI formatter 不得输出 token_digest 全值，只能展示业务字段、状态、计数、阻断原因和脱敏摘要。

233. Eta-6 Worker/Mu 和 smoke 可复现。
   - `WORKER_TASKS` 必须包含 `vendor_production_source_closure`。
   - `worker_schedule` 默认包含 `eta6_vendor_production_source_closure_30m`，task_args 包含 `eta6_environment`、`eta6_closure_scope`、`eta6_closure_mode`、`eta6_require_real_vendor_env`、`eta6_external_probe_allowed`、`eta6_min_stability_score` 和 `eta6_allow_cost_watch`。
   - dry-run 不得写 Eta-6 表；非 dry-run 必须写 run、dataset check 和 decision。
   - 缺少真实 `QDATA_VENDOR_BASE_URL` 或 `QDATA_VENDOR_TOKEN` 时必须映射为 blocked/warning，不得误报 production_ready。
   - `scripts/smoke_eta6_vendor_production_source.py` 必须输出 status、role、datasets、production_ready、blocked、decisions、live env presence 和 score。

## 验收用例

| 用例 | 命令 | 预期结果 |
|---|---|---|
| 单元测试 | `python3 -m unittest discover -s tests` | 以当前命令输出为准，不固定易过期数量 |
| CSV 全市场样例 | `./scripts/run_daily_pipeline.py --provider csv --all-market --job-code daily_market_csv_all --trade-date 2024-01-04 --batch-size 1 --force` | `partial_success`，expected=3，rows=2，missing=1 |
| CSV 非交易日 | `./scripts/run_daily_pipeline.py --provider csv --all-market --job-code daily_market_csv_all --trade-date 2024-01-05 --batch-size 1 --force` | `skipped` |
| CSV 生产 smoke | `./scripts/smoke_full_market_daily.py --job-code daily_market_csv_all --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ` | 输出 `missing_symbols=300750.SZ`，health 为当前 job 的 2 条 warning |
| AkShare 全市场小样本 | `.venv312/bin/python scripts/run_daily_pipeline.py --provider akshare --all-market --job-code daily_market_akshare_all_smoke --trade-date 2024-01-04 --max-symbols 2 --batch-size 1 --min-completeness 0.5 --force` | `success`，expected=2，rows=2，missing=0 |
| AkShare 生产 smoke | `.venv312/bin/python scripts/smoke_full_market_daily.py --job-code daily_market_akshare_all_smoke --trade-date 2024-01-04 --symbols 000001.SZ,000002.SZ` | 样例价格数为 2，health 为当前 job 的 pass |
| 生产入口 | `./scripts/run_daily_production.sh --provider csv --job-code daily_market_csv_all --start-date 2024-01-04 --end-date 2024-01-04 --batch-size 1 --force` | 输出 production_report，问题日进入 repair queue |
| 只读日报 | `./scripts/report_daily_production.py --job-code daily_market_csv_all --start-date 2024-01-04 --end-date 2024-01-05` | 输出 status_counts、missing_total、repair 摘要 |
| 修复队列 | `./scripts/run_repair_queue.py --job-code daily_market_csv_all --limit 1` | 读取 open repair item 并重跑对应日期 |
| 查询压测 | `./scripts/benchmark_daily_query.py --symbols 600519.SH,000001.SZ --start-date 2024-01-04 --end-date 2024-01-04 --repeat 3` | 输出 median_ms 和 rows_per_second |
| 约束同步 | `./scripts/sync_market_constraints.py --provider csv --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ` | factors=2，limits=2，suspensions=0 |
| 可交易股票池 | `./scripts/build_tradable_universe.py --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ` | members=2，并可通过 `get_universe("tradable_a_share")` 查询 |
| 价格矩阵 | `./scripts/export_price_matrix.py --symbols 600519.SH,000001.SZ --start-date 2024-01-04 --end-date 2024-01-04 --field close --output raw/exports/close_matrix.csv` | 生成矩阵文件并记录 audit |
| 分钟线 Alpha | `./scripts/sync_minute_market.py --provider csv --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ` | 写入分钟线，SDK 可查回 1m 数据 |
| 多源 dry-run | `./scripts/compare_daily_sources.py --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ --dry-run` | 输出 conflicts=2、coverage_rate=1.0 |
| 多源落库 | `./scripts/compare_daily_sources.py --trade-date 2024-01-04 --symbols 600519.SH,000001.SZ` | `data_conflict_daily` 写入 2 条，质量日报为 warning |
| REST 服务 | `./scripts/run_api_server.py --backend sql --port 18080 --tokens devtoken` | 输出 `qdata_api=http://127.0.0.1:18080 backend=sql` |
| REST smoke | `./scripts/smoke_api_server.py --base-url http://127.0.0.1:18080 --token devtoken --start-date 2024-01-02 --end-date 2024-01-02 --asof-date 2024-01-02 --symbols 600519.SH,000001.SZ` | health/price/constraints/tradable/matrix 均输出 ok |
| 运维看板 | `./scripts/report_ops_dashboard.py --start-date 2024-01-04 --end-date 2024-01-04 --dataset-code daily_bar --write-snapshot` | 输出 pipeline/quality/api/alerts 汇总，并写入 snapshot |
| SLA 告警 | `./scripts/check_sla_alerts.py --policy-code daily_bar_conflict_sla --policy-name "Daily bar conflict SLA" --ensure-policy --dataset-code daily_bar --max-conflict-rate 0.001 --trade-date 2024-01-04` | 写入 1 条 `conflict_rate_above_sla` open alert |
| API 审计报表 | `.venv312/bin/python scripts/report_api_audit.py --start-date 2026-07-24 --end-date 2026-07-28` | 输出 requests=5833、failed=5、慢接口列表；失败主要为无 Bearer token 的浏览器/curl 验证访问 |
| 注册供应商 profile | `./scripts/register_vendor_profile.py --source-code vendor_http --source-name "Commercial HTTP Vendor Fixture" --provider-name vendor_http --auth-mode bearer --enabled-datasets daily_bar,adjustment_factor,limit_price_daily --rate-limit-per-min 120 --license-scope "commercial contract required; fixture smoke only" --redistribution-allowed unknown --status testing` | 输出 `provider=vendor_http` 和 `profile_id` |
| 商业 adapter fixture benchmark | `./scripts/benchmark_vendor_sources.py --primary-provider csv --secondary-provider vendor_http --start-date 2024-01-04 --end-date 2024-01-04 --symbols 600519.SH,000001.SZ --write-db` | 输出 `status=warning`、coverage=1、conflict_rate=0.16666667、rating=A |
| AkShare 真实第二源 benchmark | `.venv312/bin/python scripts/benchmark_vendor_sources.py --primary-provider csv --secondary-provider akshare --start-date 2024-01-04 --end-date 2024-01-04 --symbols 600519.SH,000001.SZ --write-db` | 输出真实网络源 benchmark，当前样例 rating=C |
| 供应商评分榜 | `./scripts/report_vendor_scores.py --dataset-code daily_bar` | 输出 `vendor_http rating=A` 和 `akshare rating=C` |
| 注册字段映射 | `./scripts/register_vendor_field_mapping.py --source-code vendor_http --dataset-code daily_bar --print-mapping` | 写入 28 条字段映射并输出 mapping/transforms |
| 激活供应商 profile | `./scripts/activate_vendor_profile.py --source-code vendor_http --provider-name vendor_http --status active` | 输出 `status=active` |
| 分片供应商压测 | `./scripts/benchmark_vendor_universe.py --primary-provider csv --secondary-provider vendor_http --start-date 2024-01-04 --end-date 2024-01-04 --symbols 600519.SH,000001.SZ --shard-size 1 --write-db` | 输出 `shards=2`、`benchmarks=2`、rating=A，并写入 suite |
| Provider SLA | `./scripts/check_provider_sla_alerts.py --source-code vendor_http --dataset-code daily_bar --trade-date 2024-01-04` | 写入 1 条 `vendor_conflict_rate_above_sla` open alert |
| 上线决策报告 | `./scripts/report_vendor_decisions.py --dataset-code daily_bar --write-db` | 输出 `vendor_http approve_backup`、`akshare watch` 并写入决策报告 |
| Iota 安全初始化 | `.venv312/bin/python scripts/bootstrap_iota_security.py --token iotatoken --json` | 写入 demo/quant-research/research-bot，token_id=1，access=3 |
| Iota 通知通道 | `.venv312/bin/python scripts/register_notification_channel.py --channel-code stdout-high --channel-type stdout --min-severity high --json` | 写入 active stdout-high 通道 |
| Iota 告警投递 | `.venv312/bin/python scripts/send_alert_notifications.py --channel-code stdout-high --json` | open high 告警写入 `alert_notification_delivery`，当前 sent=2 |
| Iota DB token REST smoke | `.venv312/bin/python scripts/smoke_api_server.py --base-url http://127.0.0.1:18081 --token iotatoken --start-date 2024-01-04 --end-date 2024-01-04 --asof-date 2024-01-04 --symbols 600519.SH,000001.SZ` | health/price/constraints/tradable/matrix 均输出 ok |
| Iota/Kappa 用量日报 | `.venv312/bin/python scripts/report_api_usage.py --trade-date 2026-07-24 --rollup --project-code quant-research` | 输出项目用量，覆盖数据 API 和 Kappa 管理 API |
| Iota 压测调度 | `.venv312/bin/python scripts/manage_vendor_benchmark_schedule.py --schedule-code daily_bar_vendor_fixture_schedule --run-now --json` | schedule active，run status=warning，写入 suite_id |
| 多数据集字段映射 | `./scripts/register_vendor_field_mapping.py --source-code vendor_http --dataset-code adjustment_factor` | `adjustment_factor=10`、`limit_price_daily=12`、`security_master=11` 可分别写入 |
| Kappa CLI overview | `.venv312/bin/python scripts/report_kappa_admin.py --resource overview` | 输出 active_tenant_count=1、active_worker_schedule_count=3、latest_deployment_health_status=success、active_product_count=1、budget_open_alert_count=1、invoice_month_count=2、latest_vendor_readiness_status=watch、latest_reconciliation_status=matched、customer_health_active_count=1、payment_month_received_amount=100.00000000、latest_runtime_report_status=warning、latest_strategy_status=warning、access_denied_24h_count=1、project_governance_critical_count=1、open_governance_action_count=1、automation_24h_run_count=4、automation_24h_action_count=11、automation_approval_required_count=2、latest_automation_status=success、automation_active_profile_count=4、automation_ready_profile_count=1、automation_24h_validation_count=8、automation_24h_live_receipt_count=2、latest_automation_live_receipt_status=blocked |
| Kappa CLI usage | `.venv312/bin/python scripts/report_kappa_admin.py --resource usage-daily --trade-date 2026-07-24 --project-code quant-research` | 输出 14 行 quant-research 项目用量 |
| Kappa CLI token 脱敏 | `.venv312/bin/python scripts/report_kappa_admin.py --resource tokens --limit 5` | 输出 `token_hash_tail` 和 scopes，不输出完整 token_hash |
| Phi 策略运行 | `.venv312/bin/python scripts/report_phi_strategy.py --resource run-all --as-of-date 2026-07-27 --environment local --trigger-mode smoke` | `status=warning`、`highest=high`、signals=7、decisions=5、escalations=2 |
| Phi 决策查询 | `.venv312/bin/python scripts/report_phi_strategy.py --resource decisions --run-code phi-local-20260727` | 输出质量、供应商、运行、商业和回款 5 条决策 |
| Kappa Strategy 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource strategy-decisions --run-code phi-local-20260727 --limit 10` | strategy decisions rows=5，并可看到 action/status/severity/reason |
| Chi access allow | `.venv312/bin/python scripts/report_chi_governance.py --resource evaluate-access --tenant-code demo --project-code quant-research --principal-code research-bot --dataset-code daily_bar --api-name price --fields close,volume --request-id chi-smoke-allow --write-audit` | 输出 decision=allow、effective_scope=principal、access_level=read |
| Chi access deny | `.venv312/bin/python scripts/report_chi_governance.py --resource evaluate-access --tenant-code demo --project-code quant-research --principal-code research-bot --dataset-code financial_statement --api-name fundamentals --request-id chi-smoke-deny --write-audit` | 输出 decision=deny、reason=dataset access denied |
| Chi 项目治理 | `.venv312/bin/python scripts/report_chi_governance.py --resource collect-snapshots --snapshot-date 2026-07-27 --tenant-code demo --project-code quant-research --write-db --write-actions` | 输出 status=critical、risk_score=49.0、denied_access_7d_count=1、budget_status=exceeded |
| Kappa Chi 审计 | `.venv312/bin/python scripts/report_kappa_admin.py --resource access-decisions --project-code quant-research --limit 10` | 输出 access decisions rows，并可看到 allow/deny、effective_scope、reason |
| Kappa Chi 治理 | `.venv312/bin/python scripts/report_kappa_admin.py --resource project-governance --project-code quant-research --limit 10` | 输出项目治理快照，status=critical、recommended_action=review_budget |
| Kappa Chi 动作 | `.venv312/bin/python scripts/report_kappa_admin.py --resource governance-actions --project-code quant-research --limit 10` | 输出 open review_budget 高优先级治理动作 |
| Psi dry-run | `.venv312/bin/python scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode dry_run` | 输出 status=success、actions=5、executed=0、skipped=5，覆盖 5 类 action_type |
| Psi execute Phi safe | `.venv312/bin/python scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode execute --no-chi --source-run-code phi-local-20260727 --run-code psi-local-20260727-execute-phi-safe` | 输出 status=warning、actions=4、executed=2、approval_required=2、failed=0 |
| Psi execute Chi guard | `.venv312/bin/python scripts/report_psi_automation.py --resource run --as-of-date 2026-07-27 --environment local --trigger-mode smoke --execution-mode execute --no-phi --tenant-code demo --project-code quant-research --run-code psi-local-20260727-execute-chi-guard` | 输出 freeze_budget 高风险动作 status=approval_required |
| Kappa Psi 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource automation-actions --limit 10` | 输出 automation action rows，可看到 skipped/success/approval_required |
| Omega 生成审批 | `.venv312/bin/python scripts/report_omega_control.py --resource execute --run-code psi-local-20260727-execute-phi-safe --trigger-mode smoke --requested-by omega-smoke` | 高风险动作写入 approval_required attempts，并生成 pending approvals |
| Omega 审批执行 | `.venv312/bin/python scripts/report_omega_control.py --resource decide-approval --approval-code <approval_code> --decision approved --decided-by platform-lead && .venv312/bin/python scripts/report_omega_control.py --resource execute --action-code <action_code> --trigger-mode smoke` | approved degrade_vendor 通过 noop executor 成功，external_side_effect=false |
| Omega 失败重试 | `.venv312/bin/python scripts/report_omega_control.py --resource execute --action-code omega-smoke-retry-action --executor-code omega-noop-force-fail-notify --trigger-mode smoke` | 输出 retry_scheduled=1、error_message=forced executor failure |
| Omega 回滚演练 | `.venv312/bin/python scripts/report_omega_control.py --resource request-rollback --action-code <action_code> --requested-by omega-smoke --reason "smoke rollback drill" && .venv312/bin/python scripts/report_omega_control.py --resource run-rollback --rollback-code <rollback_code> --executed-by platform-lead` | rollback status=success，action 控制状态 rolled_back |
| Kappa Omega 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource automation-attempts --limit 10` | 输出 approval_required/success/retry_scheduled attempts |
| Alpha-2 allowlist 查询 | `.venv312/bin/python scripts/report_omega_control.py --resource allowlists` | 输出 `alpha2-script-reporter` 和 `alpha2-webhook-localhost` 两条 active allowlist |
| Alpha-2 secret ref 查询 | `.venv312/bin/python scripts/report_omega_control.py --resource secrets` | 输出 `alpha2-local-hmac`，metadata 仅包含 env_var 引用 |
| Alpha-2 脚本沙箱 | `.venv312/bin/python scripts/report_omega_control.py --resource execute --action-code omega-smoke-retry-action --executor-code alpha2-script-notify-owner --allow-external --trigger-mode smoke --requested-by alpha2-smoke` | 输出 success attempt，response_payload 中 returncode=0、sandbox_dispatch=true |
| Alpha-2 webhook 沙箱 | `QDATA_ALPHA2_HMAC_SECRET=alpha2-local-secret .venv312/bin/python scripts/report_omega_control.py --resource execute --action-code omega-smoke-retry-action --executor-code alpha2-webhook-notify-owner --allow-external --trigger-mode smoke --requested-by alpha2-smoke` | 输出 success attempt，response_payload 中 status_code=200、signed=true、sandbox_dispatch=true |
| Beta-2 通道查询 | `.venv312/bin/python scripts/report_beta2_external.py --resource channels` | 输出 `beta2-local-approval-webhook` 和 `beta2-local-deadletter-webhook` 两条 active channel |
| Beta-2 dispatch 成功 | `QDATA_ALPHA2_HMAC_SECRET=alpha2-local-secret .venv312/bin/python scripts/report_beta2_external.py --resource dispatch --action-code omega-smoke-retry-action --channel-code beta2-local-approval-webhook --allow-external --trigger-mode smoke --requested-by beta2-smoke` | 输出 acknowledged dispatch，response_payload 中 status_code=200、signed=true |
| Beta-2 重复抑制 | `.venv312/bin/python scripts/report_beta2_external.py --resource dispatch --action-code omega-smoke-retry-action --channel-code beta2-local-approval-webhook --allow-external --trigger-mode smoke --requested-by beta2-smoke` | 第二次触发输出 suppressed，response_payload 中 blocked_by=duplicate_window |
| Beta-2 dead-letter | `QDATA_ALPHA2_HMAC_SECRET=alpha2-local-secret .venv312/bin/python scripts/report_beta2_external.py --resource dispatch --action-code omega-smoke-retry-action --channel-code beta2-local-deadletter-webhook --allow-external --trigger-mode smoke --requested-by beta2-smoke` | 输出 dead_letter dispatch，并保留 error_message |
| Beta-2 recovery | `.venv312/bin/python scripts/report_beta2_external.py --resource recover --dispatch-code <dead_letter_dispatch_code> --recovered-by beta2-smoke --reason "manual recovery smoke" --runbook-code beta2-webhook-timeout` | 输出 status=recovered、recovered_by=beta2-smoke、runbook_code=beta2-webhook-timeout |
| Gamma-2 smoke | `.venv312/bin/python scripts/smoke_gamma2_external.py` | 输出 `gamma2_smoke=ok profiles=3 ready_profiles=1 validations=6 rotations=2 current_validation=success rotation=applied rollback=rolled_back post_rollback_validation=success` |
| Gamma-2 profiles 查询 | `.venv312/bin/python scripts/report_gamma2_external.py --resource profiles --limit 10` | 输出 feishu/wecom/email 三条 local active profile，feishu readiness_status=dry_run_ready |
| Gamma-2 validations 查询 | `.venv312/bin/python scripts/report_gamma2_external.py --resource validations --limit 5` | 输出 success validation，覆盖 dry_run_dispatch、secret_rotation、rollback_drill |
| Gamma-2 rotations 查询 | `.venv312/bin/python scripts/report_gamma2_external.py --resource rotations --limit 5` | 输出 status=rolled_back rotation，validation_status=success，affected_channel_count=1 |
| Kappa Gamma-2 profile 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource automation-channel-profiles --profile-code gamma2-local-feishu-profile --limit 1` | 输出 gamma2-local-feishu-profile，readiness_status=dry_run_ready，next_secret_ref=gamma2-local-hmac-next |
| Delta-2 blocked smoke | `.venv312/bin/python scripts/smoke_delta2_wecom.py` | 输出 `delta2_wecom_smoke=ok mode=blocked status=blocked ... provider_errcode=None`，不产生外部副作用 |
| Delta-2 require-live 保护 | `.venv312/bin/python scripts/smoke_delta2_wecom.py --allow-external --require-live` | 当前未配置 `QDATA_DELTA2_WECOM_WEBHOOK_URL` 时输出 `delta2_wecom_smoke=failed reason=missing_env ...` |
| Delta-2 receipts 查询 | `.venv312/bin/python scripts/report_delta2_wecom.py --resource receipts --profile-code delta2-wecom-live-profile --provider-code wecom --limit 5` | 输出 2 条 blocked receipt，error_message=external_live_dispatch_disabled |
| Kappa Delta-2 receipts 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource automation-live-receipts --limit 5` | 输出 `admin.automation-live-receipts rows=2`，可看到 delta2-wecom-live-profile blocked receipt |
| Epsilon-3 blocked smoke | `.venv312/bin/python scripts/smoke_epsilon3_vendor_live_gate.py` | 输出 `epsilon3_vendor_live_gate_smoke=ok mode=blocked status=blocked ... live_base_url_present=False live_token_present=False`，不产生外部副作用 |
| Epsilon-3 require-live 保护 | `.venv312/bin/python scripts/smoke_epsilon3_vendor_live_gate.py --allow-live --require-live` | 当前未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时输出 `epsilon3_vendor_live_gate_smoke=failed reason=missing_vendor_live_env` |
| Epsilon-3 gate 查询 | `.venv312/bin/python scripts/run_epsilon3_vendor_live_gate.py --resource runs --limit 5` | 输出最新 blocked gate，最新一条 `live_token_present=False`、error_message=external_vendor_live_disabled |
| Kappa Epsilon-3 gate 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-gates --limit 100` | 输出最近 blocked gate；Theta-3 编排后当前 `admin.vendor-live-gates rows=26` |
| Zeta-3 blocked smoke | `.venv312/bin/python scripts/smoke_zeta3_vendor_onboarding.py` | 输出 `zeta3_vendor_onboarding_smoke=ok mode=blocked status=blocked ... dataset_count=4 gate_count=4 live_base_url_present=False live_token_present=False`，不产生外部副作用 |
| Zeta-3 require-live 保护 | `.venv312/bin/python scripts/smoke_zeta3_vendor_onboarding.py --allow-live --require-live` | 当前未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时输出 `zeta3_vendor_onboarding_smoke=failed reason=missing_vendor_live_env` |
| Zeta-3 onboarding runs 查询 | `.venv312/bin/python scripts/run_zeta3_vendor_onboarding.py --resource runs --limit 5` | 输出 blocked onboarding run，`recommendation=research_only`，error_message 包含 external_vendor_live_disabled 和缺少 env |
| Zeta-3 onboarding results 查询 | `.venv312/bin/python scripts/run_zeta3_vendor_onboarding.py --resource results --limit 20` | 当前累计 16 条 blocked dataset result，`security_master` 包含 `dataset_not_enabled:security_master` |
| Kappa Zeta-3 runs 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-onboarding-runs --limit 10` | 输出 `admin.vendor-onboarding-runs rows=6`，可看到最新 blocked onboarding run |
| Kappa Zeta-3 results 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-onboarding-results --limit 100` | 输出 `admin.vendor-onboarding-results rows=24`，可看到 4 个数据集的多轮结果 |
| Eta-3 blocked smoke | `.venv312/bin/python scripts/smoke_eta3_vendor_live_closure.py` | 输出 `eta3_vendor_live_closure_smoke=ok mode=blocked status=blocked ... probe_count=4 onboarding_status=blocked live_base_url_present=False live_token_present=False`，不产生外部副作用 |
| Eta-3 require-live 保护 | `.venv312/bin/python scripts/smoke_eta3_vendor_live_closure.py --allow-live --require-live` | 当前未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时输出 `eta3_vendor_live_closure_smoke=failed reason=missing_vendor_live_env` |
| Eta-3 closure 查询 | `.venv312/bin/python scripts/run_eta3_vendor_live_closure.py --resource runs --limit 5` | 输出 2 条 blocked closure，`recommendation=research_only`，error_message 包含 external_vendor_live_disabled、缺少 env、合同/授权/限频和 dataset 阻塞 |
| Eta-3 probe 查询 | `.venv312/bin/python scripts/run_eta3_vendor_live_closure.py --resource probes --limit 10` | 输出 8 条 dataset probe，最新 `daily_bar` 包含 `close/symbol/trade_date` schema 检查，`security_master` 包含 `dataset_not_enabled:security_master` |
| Kappa Eta-3 closures 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-closures --limit 10` | 输出 `admin.vendor-live-closures rows=4`，可看到最新 blocked closure |
| Kappa Eta-3 probes 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-probes --limit 100` | 输出 `admin.vendor-live-probes rows=16`，可看到 4 个数据集 probe |
| Theta-3 blocked smoke | `.venv312/bin/python scripts/smoke_theta3_vendor_live_pilot.py` | 输出 `theta3_vendor_live_pilot_smoke=ok mode=blocked status=blocked ... dataset_count=4 signoff_status=not_ready risk_level=high live_base_url_present=False live_token_present=False`，不产生外部副作用 |
| Theta-3 require-live 保护 | `.venv312/bin/python scripts/smoke_theta3_vendor_live_pilot.py --allow-live --require-live` | 当前未配置 `QDATA_VENDOR_BASE_URL` / `QDATA_VENDOR_TOKEN` 时输出 `theta3_vendor_live_pilot_smoke=failed reason=missing_vendor_live_env` |
| Theta-3 pilot 查询 | `.venv312/bin/python scripts/run_theta3_vendor_live_pilot.py --resource runs --limit 5` | 输出最新 blocked pilot，signoff_status=`not_ready`，risk_level=`high`，recommendation=`research_only` |
| Theta-3 result 查询 | `.venv312/bin/python scripts/run_theta3_vendor_live_pilot.py --resource results --limit 20` | 输出 8 条 dataset pilot result，覆盖 daily_bar/security_master/adjustment_factor/limit_price_daily 和 probe/gate 证据 |
| Kappa Theta-3 pilots 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-pilots --limit 5` | 输出 `admin.vendor-live-pilots rows=2`，可看到最新 blocked pilot |
| Kappa Theta-3 results 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-live-pilot-results --limit 20` | 输出 `admin.vendor-live-pilot-results rows=8`，可看到 4 个数据集 pilot result |
| Iota-3 免费源目录 | `.venv312/bin/python scripts/run_iota3_free_source_fabric.py --resource catalog` | 输出 csv/csv_mirror/akshare/baostock/tushare_free/cninfo_public/sse_public/szse_public/nbs_public 候选源 |
| Iota-3 本地 fabric smoke | `.venv312/bin/python scripts/smoke_iota3_free_source_fabric.py` | 输出 `iota3_free_source_fabric_smoke=ok status=success ... dataset_count=5 source_count=2 usable_source_count=2 coverage_rate=1.000000 conflict_rate_bps=0.000000 allow_external=False` |
| Iota-3 冲突 warning | `.venv312/bin/python scripts/run_iota3_free_source_fabric.py --resource run --dataset-codes daily_bar --csv-mirror-close-offset-bps 10` | 输出 warning，dataset result 的 consistency_status=`warning` 且 blocking_issues 包含 conflict threshold |
| Kappa Iota-3 runs 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-runs --limit 5` | 输出 `admin.free-source-fabric-runs rows=4`，可看到最新 success fabric 和 require-external blocked 护栏记录 |
| Kappa Iota-3 results 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-results --limit 20` | 输出 `admin.free-source-fabric-results rows=16`，可看到 coverage/consistency/license 状态 |
| Iota-4 AKShare live-only canary | `.venv312/bin/python scripts/smoke_iota4_external_free_source_canary.py` | 输出 `iota4_external_free_source_canary=ok mode=live-only fabric_status=warning ... external_executed=1 coverage_rate=1.000000 recommendation=research_only commercial_clearance=blocked`，真实外部 AKShare 链路可执行且授权风险保留 |
| Iota-4 AKShare compare-local canary | `.venv312/bin/python scripts/smoke_iota4_external_free_source_canary.py --mode compare-local` | 输出 `iota4_external_free_source_canary=ok mode=compare-local ... external_executed=1`，AKShare 进入 csv/csv_mirror/akshare 多源 fabric 审计 |
| Kappa Iota-4 runs 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-runs --requested-by iota4 --limit 5` | 输出 Iota-4 canary run，可看到 baseline_source_code、coverage_rate、license_review_required_count 和 recommendation |
| Kappa Iota-4 AKShare results 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-results --source-code akshare --limit 10` | 输出 AKShare 相关 dataset result，至少覆盖 daily_bar/security_master/trading_calendar |
| Iota-5 provider 单测 | `.venv312/bin/python -m unittest tests.test_free_source_providers tests.test_iota5_free_source_adapter_pool` | 9 个测试通过，覆盖 BaoStock/TuShare/official scaffold 和 adapter pool ok/degraded/failed |
| Iota-5 adapter pool smoke | `.venv312/bin/python scripts/smoke_iota5_free_source_adapter_pool.py --baostock-timeout-seconds 3` | 当前本机输出 `iota5_free_source_adapter_pool=degraded ... external_executed=1 ... degraded_reasons=fabric_status_degraded:failed,external_successful_sources_below_target:1/2,official_public_scaffold_pending,tushare_token_missing,baostock_source_failed` |
| Iota-5 strict ok gate | `.venv312/bin/python scripts/smoke_iota5_free_source_adapter_pool.py --require-ok --tushare-token <token>` | 只有至少两个外部免费源真实成功时返回 0；否则返回失败并保留审计 |
| Kappa Iota-5 runs 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-runs --requested-by iota5 --limit 5` | 输出 Iota-5 adapter pool run，当前最新 baseline_source_code=`akshare`、status=`failed`、recommendation=`reject` |
| Kappa Iota-5 source results 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-fabric-results --source-code baostock --limit 10` | 输出 baostock 相关 dataset result，可看到 blocked/failed 状态和 baseline_source_code |
| Kappa-5 reliability smoke | `.venv312/bin/python scripts/smoke_kappa5_free_source_reliability.py --lookback-hours 72` | 输出 `kappa5_free_source_reliability_smoke=ok snapshot_count=28 ready=0 watch=11 degraded=2 rejected=15 no_data=0 min_score=0.0000 max_score=72.0000` |
| Kappa-5 reliability 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-reliability --limit 5` | 输出 latest reliability snapshot，包含 source_code、dataset_code、status、recommended_role、reliability_score 和 commercial_clearance |
| Lambda-5 recovery smoke | `.venv312/bin/python scripts/smoke_lambda5_free_source_recovery.py --lookback-hours 72` | 输出 `lambda5_free_source_recovery_smoke=ok status=warning ... snapshot_count=28 action_count=28 retry=0 alerts=17 manual_review=17` |
| Lambda-5 worker dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task free_source_recovery --dry-run --trade-date 2026-07-28` | 输出 `task name=free_source_recovery status=skipped processed=28 warning=28`，不新增恢复 run |
| Lambda-5 recovery 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-recovery-runs --limit 5` | 输出 `admin.free-source-recovery-runs rows=2`，可看到 status、action_count、created_alert_count |
| Lambda-5 action 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-recovery-actions --limit 5` | 输出恢复动作明细，包含 source_code、dataset_code、action_type、severity、reason_code |
| Mu-5 execution 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-recovery-executions --limit 5` | 输出 `admin.free-source-recovery-executions rows=3`，包含 retry_canary recovered 和 manual_review review_requested |
| Nu-5 health smoke | `.venv312/bin/python scripts/smoke_nu5_free_source_recovery_health.py` | 输出 `nu5_free_source_recovery_health_smoke=ok status=warning ... backlog=34 approvals=2 overdue=0 stale_schedule=0` |
| Nu-5 worker dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task free_source_recovery_health --dry-run --trade-date 2026-07-28` | 输出 `task name=free_source_recovery_health status=skipped processed=1 warning=1`，不写 health snapshot |
| Nu-5 schedule | `.venv312/bin/python scripts/run_mu_scheduler.py --schedule-code nu_free_source_recovery_health_15m --once --force-due --trade-date 2026-07-28` | 输出 tick status=warning 且 worker_run_id 写回 schedule tick |
| Nu-5 health 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-recovery-health --limit 5` | 输出 `admin.free-source-recovery-health rows=3`，包含 backlog、approval_pending、failure_rate、health_issues 和 runbook_actions |
| Xi-5 admission smoke | `.venv312/bin/python scripts/smoke_xi5_free_source_admission.py` | 输出 `xi5_free_source_admission_smoke=ok snapshots=38 approved=0 conditional=0 review_required=11 blocked=17 no_data=10 primary_candidate=0` |
| Xi-5 worker dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task free_source_admission_review --dry-run --trade-date 2026-07-28` | 输出 `task name=free_source_admission_review status=skipped processed=38 warning=38`，不写 admission snapshot |
| Xi-5 schedule | `.venv312/bin/python scripts/run_mu_scheduler.py --schedule-code xi_free_source_admission_review_6h --once --force-due --trade-date 2026-07-28` | 输出 tick status=warning 且 worker_run_id 写回 schedule tick |
| Xi-5 admission 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource free-source-admission --limit 5` | 输出 `admin.free-source-admission rows=5`，包含 source_code、dataset_code、status、admission_role、license、contract 和 blocking_issues |
| Omicron-5 procurement smoke | `.venv312/bin/python scripts/smoke_omicron5_vendor_contract.py` | 输出 `omicron5_vendor_contract_smoke=ok snapshots=7 ready=0 conditional=0 review_required=3 blocked=4 no_contract=0 primary_candidate=0` |
| Omicron-5 contract profiles 查询 | `.venv312/bin/python scripts/run_omicron5_vendor_contract.py --resource profiles --limit 2` | 输出 `omicron5 resource=profiles rows=1`，`vendor_http` 合同模板为 `draft/review_required` |
| Omicron-5 entitlements 查询 | `.venv312/bin/python scripts/run_omicron5_vendor_contract.py --resource entitlements --limit 2` | 输出 dataset entitlement，blocking_issues 包含合同未 active、商用未 clear、再分发 unknown、生产使用未允许和 schema pending |
| Omicron-5 readiness 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-procurement-readiness --limit 2` | 输出 `admin.vendor-procurement-readiness rows=2`，包含 `review_required/blocked` 和采购角色 |
| Omicron-5 worker dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_contract_readiness_review --dry-run --trade-date 2026-07-28` | 输出 `status=skipped processed=7 warning=7`，dry-run 不写 procurement snapshot |
| Omicron-5 worker 非 dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_contract_readiness_review --trade-date 2026-07-28` | 输出 `status=warning processed=7 warning=7 failed=0`，写入 procurement snapshot |
| Omicron-5 schedule | `.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code omicron5_vendor_contract_readiness_6h --trade-date 2026-07-28` | 输出 tick status=warning 且 worker_run_id 写回 schedule tick |
| Pi-5 promotion smoke | `.venv312/bin/python scripts/smoke_pi5_vendor_primary_promotion.py` | 输出 `pi5_vendor_primary_promotion_smoke=ok status=blocked datasets=7 approved=0 pending=0 blocked=7 applied=0 routing_allowed=False routing_applied=False` |
| Pi-5 promotion runs 查询 | `.venv312/bin/python scripts/run_pi5_vendor_primary_promotion.py --resource runs --limit 5` | 输出 `pi5 resource=runs rows=1`，当前 latest 为 `status=blocked apply_mode=review_only dataset_count=7 blocked_dataset_count=7` |
| Pi-5 promotion results 查询 | `.venv312/bin/python scripts/run_pi5_vendor_primary_promotion.py --resource results --limit 20` | 输出 `pi5 resource=results rows=7`，每个 dataset 均保留 Omicron-5/Pi/Theta-3 阻塞原因 |
| Pi-5 worker dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_promotion_review --dry-run --trade-date 2026-07-28` | 输出 `task name=vendor_primary_promotion_review status=skipped processed=7 warning=7`，dry-run 不写 promotion run/result |
| Pi-5 worker 非 dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_promotion_review --trade-date 2026-07-28` | 输出 `task name=vendor_primary_promotion_review status=warning processed=7 warning=7 failed=0`，当前模板授权环境不改写 `source_priority` |
| Pi-5 schedule | `.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code pi5_vendor_primary_promotion_6h --trade-date 2026-07-28` | 输出 `tick schedule=pi5_vendor_primary_promotion_6h task=vendor_primary_promotion_review status=warning lock_acquired=True worker_run_id=23` |
| Pi-5 Kappa 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-promotions --limit 5` | 输出 `admin.vendor-primary-promotions rows=3`；`vendor-primary-promotion-results` 当前可查 `rows=20` |
| Rho-5 monitor smoke | `.venv312/bin/python scripts/smoke_rho5_post_promotion_monitor.py` | 当前未 applied Pi-5 时输出 `rho5_post_promotion_monitor_smoke=ok status=no_applied_promotion datasets=7 no_applied=7 rollback_allowed=False rollback_applied=False` |
| Rho-5 monitor runs 查询 | `.venv312/bin/python scripts/run_rho5_post_promotion_monitor.py --resource runs --limit 5` | 输出 `rho5 resource=runs rows>=1`，latest 为 `monitor_scope=post_promotion rollback_mode=review_only` |
| Rho-5 monitor results 查询 | `.venv312/bin/python scripts/run_rho5_post_promotion_monitor.py --resource results --limit 20` | 输出 `rho5 resource=results rows>=7`，每个 dataset 均保留 Pi-5 未 applied 或 shadow/rollback 证据 |
| Rho-5 worker dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_post_promotion_monitor --dry-run --trade-date 2026-07-28` | 输出 `task name=vendor_post_promotion_monitor status=skipped processed=7 warning=7`，dry-run 不写 monitor run/result |
| Rho-5 worker 非 dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_post_promotion_monitor --trade-date 2026-07-28` | 输出 `task name=vendor_post_promotion_monitor status=warning processed=7 warning=7 failed=0`，当前未 applied promotion 不改写 `source_priority` |
| Rho-5 schedule | `.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code rho5_post_promotion_monitor_1h --trade-date 2026-07-28` | 输出 `tick schedule=rho5_post_promotion_monitor_1h task=vendor_post_promotion_monitor status=warning lock_acquired=True` |
| Rho-5 Kappa 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-post-promotion-monitors --limit 5` | 输出 `admin.vendor-post-promotion-monitors rows>=1`；`vendor-post-promotion-results` 当前可查 dataset monitor |
| Sigma-5 stability smoke | `.venv312/bin/python scripts/smoke_sigma5_vendor_primary_stability.py` | 当前未 applied Pi-5 时输出 `sigma5_primary_stability_smoke=ok status=no_primary_promotion role=watch datasets=7 primary=0 healthy=0 warning=0 critical=0 blocked=0 no_primary=7 api_success_rate=0.999307 scheduler_lag=0 backlog=1 score=0.0000` |
| Sigma-5 snapshots 查询 | `.venv312/bin/python scripts/run_sigma5_vendor_primary_stability.py --resource snapshots --limit 1` | 输出 `sigma5 resource=snapshots rows=1`，latest 为 `status=no_primary_promotion primary_dataset_count=0 no_primary_dataset_count=7 api_success_rate=0.999307 scheduler_lag_minutes=0 backlog_count=1 stability_score=0.0000` |
| Sigma-5 datasets 查询 | `.venv312/bin/python scripts/run_sigma5_vendor_primary_stability.py --resource datasets --limit 3` | 输出 `sigma5 resource=datasets rows=3`，dataset 明细保留 `entitlement_status=review_required`、`production_use_allowed=False`、`schema_status=pending`、`promotion_status=blocked` 和当前主源证据 |
| Sigma-5 worker dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_stability_monitor --dry-run --trade-date 2026-07-28` | 输出 `task name=vendor_primary_stability_monitor status=skipped processed=7 warning=7`，dry-run 不写 stability snapshot |
| Sigma-5 worker 非 dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_primary_stability_monitor --trade-date 2026-07-28` | 输出 `task name=vendor_primary_stability_monitor status=warning processed=7 warning=7 failed=0`，当前未 applied promotion 不改写 `source_priority` |
| Sigma-5 schedule | `.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code sigma5_vendor_primary_stability_1h --trade-date 2026-07-28` | 输出 `tick schedule=sigma5_vendor_primary_stability_1h task=vendor_primary_stability_monitor status=warning lock_acquired=True worker_run_id=29` |
| Sigma-5 Kappa 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-primary-stability --limit 1` | 输出 `admin.vendor-primary-stability rows=1`；`vendor-primary-stability-datasets --limit 3` 输出 `admin.vendor-primary-stability-datasets rows=3` |
| Tau-5 cost smoke | `.venv312/bin/python scripts/smoke_tau5_vendor_cost_optimization.py --as-of-date 2026-07-29` | 当前未 applied Pi-5 时输出 `tau5_vendor_cost_smoke=ok status=no_primary_promotion role=watch datasets=7 optimized=0 watch=0 over_budget=0 quota_risk=0 blocked=0 no_primary=7 primary_weight=0.0000 backup_weight=100.0000 free_weight=0.0000 budget_pct=0E-8 monthly_quota_pct=0E-8 score=0.0000 stress=21` |
| Tau-5 optimizations 查询 | `.venv312/bin/python scripts/run_tau5_vendor_cost_optimization.py --resource optimizations --limit 1` | 输出 `tau5 resource=optimizations rows=1`，latest 为 `status=no_primary_promotion dataset_count=7 no_primary_dataset_count=7 recommended_primary_weight_pct=0.0000 recommended_backup_weight_pct=100.0000` |
| Tau-5 plans 查询 | `.venv312/bin/python scripts/run_tau5_vendor_cost_optimization.py --resource plans --limit 3` | 输出 `tau5 resource=plans rows=3`，dataset 明细保留 `plan_role=watch`、`is_primary_route=False`、`contract_status=draft`、`entitlement_status=review_required` 和 `routing_change_allowed=False` |
| Tau-5 budget stress 查询 | `.venv312/bin/python scripts/run_tau5_vendor_cost_optimization.py --resource stress --limit 3` | 输出 `tau5 resource=stress rows=3`，包含 `stress_multiplier=1.0000/5.0000/10.0000` 和 `recommended_action=wait_primary_promotion` |
| Tau-5 worker dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_cost_optimizer --dry-run --trade-date 2026-07-29` | 输出 `task name=vendor_cost_optimizer status=skipped processed=7 warning=7`，dry-run 不写 optimization snapshot |
| Tau-5 worker 非 dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_cost_optimizer --trade-date 2026-07-29` | 输出 `task name=vendor_cost_optimizer status=warning processed=7 warning=7 failed=0`，当前未 applied promotion 不改写 `source_priority` |
| Tau-5 schedule | `.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code tau5_vendor_cost_optimizer_6h --trade-date 2026-07-29` | 输出 `tick schedule=tau5_vendor_cost_optimizer_6h task=vendor_cost_optimizer status=warning lock_acquired=True worker_run_id=32` |
| Tau-5 Kappa 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-cost-optimizations --limit 1` | 输出 `admin.vendor-cost-optimizations rows=1`；`vendor-route-weight-plans --limit 3` 输出 `admin.vendor-route-weight-plans rows=3`；`vendor-budget-stress --limit 3` 输出 `admin.vendor-budget-stress rows=3` |
| Upsilon-5 route execution smoke | `.venv312/bin/python scripts/smoke_upsilon5_route_weight_execution.py --as-of-date 2026-07-29` | 当前未 applied Pi-5 时输出 `upsilon5_route_execution_smoke=ok status=no_primary_promotion datasets=7 pending=0 approved=0 staged=0 applied=0 blocked=0 no_primary=7 target_primary=0.0000 applied_primary=0.0000 policies=0 stages=7` |
| Upsilon-5 executions 查询 | `.venv312/bin/python scripts/run_upsilon5_route_weight_execution.py --resource executions --limit 1` | 输出 `upsilon5 resource=executions rows=1`，latest 为 `status=no_primary_promotion approval_status=blocked execution_mode=review_only dataset_count=7 no_primary_dataset_count=7 applied_primary_weight_pct=0.0000` |
| Upsilon-5 datasets/stages/policies 查询 | `.venv312/bin/python scripts/run_upsilon5_route_weight_execution.py --resource datasets --limit 3` | datasets 输出 `rows=3` 且 `routing_change_allowed=False`；stages 输出 `rows=3 status=blocked gate_status=blocked`；Phi-5 smoke 后 policies 当前输出 `rows=2 policy_status=superseded`，无 active policy |
| Upsilon-5 worker dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_route_weight_executor --dry-run --trade-date 2026-07-29` | 输出 `task name=vendor_route_weight_executor status=skipped processed=7 warning=7`，dry-run 不写 policy |
| Upsilon-5 worker 非 dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task vendor_route_weight_executor --trade-date 2026-07-29` | 输出 `task name=vendor_route_weight_executor status=warning processed=7 warning=7 failed=0`，当前未 applied promotion 不写 active policy |
| Upsilon-5 schedule | `.venv312/bin/python scripts/run_mu_scheduler.py --once --force-due --schedule-code upsilon5_vendor_route_weight_executor_1h --trade-date 2026-07-29` | 输出 `tick schedule=upsilon5_vendor_route_weight_executor_1h task=vendor_route_weight_executor status=warning lock_acquired=True worker_run_id=35` |
| Upsilon-5 Kappa 查询 | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-route-executions --limit 1` | 输出 `admin.vendor-route-executions rows=1 status=no_primary_promotion`；dataset/stage endpoints 可查，`source-route-weight-policies` 当前 `rows=2 policy_status=superseded`，无 active policy |
| Phi-5 route policy smoke | `python3 scripts/smoke_phi5_route_policy_runtime.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata --trade-date 2024-01-04` | 输出 `phi5_route_policy_smoke=ok policy_code=phi5-smoke-policy-20260729023952118375 selected=csv_mirror final=csv_mirror fallback=False audits=1` |
| Phi-5 source route decisions 查询 | `python3 scripts/report_kappa_admin.py --resource source-route-decisions --limit 5` | 输出 `kappa resource=admin.source-route-decisions rows=5`，包含 `decision_context=api route_mode=default decision_status=success` 和 `decision_context=sync route_mode=policy_weighted selected_source_code=csv_mirror` |
| Phi-5 API meta | `curl -s -H 'Authorization: Bearer devtoken' 'http://127.0.0.1:18080/price?symbols=600519.SH,000001.SZ&start_date=2024-01-04&end_date=2024-01-04'` | `meta.route_policy` 包含 `decision_context=api`、`route_mode=default`、`decision_status=success`、`selected_source_code=csv` 和 `final_source_code=csv` |
| Chi-5 route feedback smoke | `python3 scripts/smoke_chi5_route_feedback.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `chi5_route_feedback_smoke=ok first_status=critical second_status=healthy health=2 circuit=closed probe=recovered` |
| Chi-5 health/circuit/probe 查询 | `python3 scripts/run_chi5_route_feedback.py --resource health --dataset-code daily_bar --source-code baostock --limit 5` | health 输出 open/close 两类快照；circuits 输出 `status=open` 或 `closed` 和 `open_until`；probes 输出 `status=recovered/failed` |
| Chi-5 Worker/Mu | `python3 scripts/run_lambda_worker.py --task source_route_feedback_monitor --trade-date 2026-07-29` | worker 输出 `task name=source_route_feedback_monitor`；Mu 强制触发 `chi5_source_route_feedback_15m` 后 tick 写入且 `lock_acquired=True` |
| Psi-5 route incident smoke | `python3 scripts/smoke_psi5_route_incident_automation.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `psi5_route_incident_smoke=ok open_action=approval_required recovered_action=success|skipped`，并写入 `circuit_open` 与 `recovered` incident action |
| Psi-5 route actions 查询 | `python3 scripts/report_kappa_admin.py --resource source-route-incident-actions --limit 5` | 输出 `admin.source-route-incident-actions rows>=1`，包含 `source_signal_type=circuit_open` 或 `source_signal_type=recovered` |
| Psi-5 Worker/Mu | `python3 scripts/run_lambda_worker.py --task route_incident_automation --trade-date 2026-07-29` | worker 输出 `task name=route_incident_automation`；Mu 强制触发 `psi5_route_incident_automation_15m` 后 tick 写入且 `lock_acquired=True` |
| Omega-5 route incident control smoke | `python3 scripts/smoke_omega5_route_incident_control.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `omega5_route_incident_smoke=ok pending_approval=pending approved=approved dispatch=acknowledged receipt=blocked|success attempt=success rollback=planned control=executed` |
| Omega-5 controls 查询 | `python3 scripts/report_kappa_admin.py --resource source-route-incident-controls --limit 5` | 输出 `admin.source-route-incident-controls rows>=1`，包含 `control_stage`、`approval_status`、`dispatch_status`、`receipt_status`、`attempt_status` 或 `rollback_status` |
| Omega-5 Worker/Mu | `python3 scripts/run_lambda_worker.py --task route_incident_control --trade-date 2026-07-29` | worker 输出 `task name=route_incident_control`；Mu 强制触发 `omega5_route_incident_control_15m` 后 tick 写入且 `lock_acquired=True` |
| Alpha-6 route control health smoke | `python3 scripts/smoke_alpha6_route_incident_control_health.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `alpha6_route_incident_control_health_smoke=ok status=healthy|warning controls>=1`，包含 pending、blocked_receipts、failed_execution、stale 和 latest_stage |
| Alpha-6 health 查询 | `python3 scripts/report_kappa_admin.py --resource source-route-incident-control-health --limit 5` | 输出 `admin.source-route-incident-control-health rows>=1`，包含 `status`、`control_count`、`pending_control_count`、`blocked_receipt_rate`、`execution_failure_rate`、`health_issues` |
| Alpha-6 Worker/Mu | `python3 scripts/run_lambda_worker.py --task route_incident_control_health --trade-date 2026-07-29` | worker 输出 `task name=route_incident_control_health`；Mu 强制触发 `alpha6_route_incident_control_health_15m` 后 tick 写入且 `lock_acquired=True` |
| Beta-6 route operation smoke | `python3 scripts/smoke_beta6_route_incident_operations.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `beta6_route_incident_operations_smoke=ok status=success|warning eligible>=1 approved>=1`，包含 batch_code、suppressed、stress_scenarios、items |
| Beta-6 operation 查询 | `python3 scripts/report_kappa_admin.py --resource source-route-incident-operation-batches --limit 5` | 输出 `admin.source-route-incident-operation-batches rows>=1`；items 查询输出 `admin.source-route-incident-operation-items rows>=1`，包含 operation_status 和 approval_status_after |
| Beta-6 Worker/Mu | `python3 scripts/run_lambda_worker.py --task route_incident_operations --trade-date 2026-07-29` | worker 输出 `task name=route_incident_operations`；Mu 强制触发 `beta6_route_incident_operations_30m` 后 tick 写入且 `lock_acquired=True` |
| Gamma-6 approval API smoke | `python3 scripts/smoke_gamma6_route_incident_approval_api.py --base-url http://127.0.0.1:18080 --token devtoken --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `gamma6_route_approval_api_smoke=ok first=pending_quorum second=applied quorum=met signatures>=2 approved=approved` |
| Gamma-6 approval 查询 | `python3 scripts/report_kappa_admin.py --resource source-route-incident-approval-commands --limit 5` | 输出 `admin.source-route-incident-approval-commands rows>=1`；items/signatures 查询分别输出 rows>=1，包含 `item_status`、`signature_count`、`signer_code` |
| Delta-6 approval governance smoke | `python3 scripts/smoke_delta6_route_incident_approval_governance.py --base-url http://127.0.0.1:18080 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `delta6_route_approval_governance_smoke=ok denied=denied first=pending_quorum second=applied replay=replay_rejected escalations>=1 approved=approved` |
| Delta-6 approval governance 查询 | `python3 scripts/run_delta6_route_incident_approval_governance.py --resource callbacks --limit 5` | 输出 `delta6.callbacks rows>=1`；role-bindings/policies/escalations 查询分别输出 rows>=1，包含 `governance_status`、`signature_status`、`reason_code` |
| Epsilon-6 approval resilience smoke | `python3 scripts/smoke_epsilon6_route_incident_approval_resilience.py --base-url http://127.0.0.1:18080 --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `epsilon6_route_approval_resilience_smoke=ok first=pending_quorum second=applied terminal_block=invalid_terminal_state audit_broken=0 sla_actions>=1 lock_events>=3 transitions>=3 audit_hashes>=4 drills>=1 approved=approved` |
| Epsilon-6 approval resilience 查询 | `python3 scripts/run_epsilon6_route_incident_approval_resilience.py --resource audit-chain --limit 5` | 输出 `epsilon6 resource=audit_chain rows>=1`；lock-events/state-transitions/sla-actions/recovery-drills/verify-chain 查询分别可返回 rows 或 `broken_count=0` |
| Epsilon-6 Worker/Mu | `python3 scripts/run_lambda_worker.py --task route_incident_approval_resilience --trade-date 2026-07-29` | worker 输出 `task name=route_incident_approval_resilience`；Mu 强制触发 `epsilon6_route_incident_approval_resilience_15m` 后 tick 写入且 `lock_acquired=True` |
| Zeta-6 approval release smoke | `python3 scripts/smoke_zeta6_route_incident_approval_release.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `zeta6_route_approval_release_smoke=ok preflight=success|warning rotation=success concurrency=success export=success|warning package_hash=<sha256>` |
| Zeta-6 approval release 查询 | `python3 scripts/run_zeta6_route_incident_approval_release.py --resource release-preflights --limit 5` | 输出 `zeta6 resource=release_preflights rows>=1`；secret-rotations/concurrency-tests/audit-exports 查询分别可返回 rows，audit export 包含 `package_hash` |
| Zeta-6 Worker/Mu | `python3 scripts/run_lambda_worker.py --task route_incident_approval_release --trade-date 2026-07-30` | worker 输出 `task name=route_incident_approval_release`；Mu 强制触发 `zeta6_route_incident_approval_release_30m` 后 tick 写入且 `lock_acquired=True` |
| Eta-6 production source smoke | `python3 scripts/smoke_eta6_vendor_production_source.py --postgres-dsn postgresql://qdata:qdata@127.0.0.1:15432/qdata` | 输出 `eta6_vendor_production_source_smoke=ok status=blocked|ready_for_pilot|ready_for_primary|ready_for_rollout|production_ready|monitoring role=<role> datasets>=1 decisions>=1 live_base_url_present=<bool> live_token_present=<bool> score=<score>` |
| Eta-6 production source 查询 | `python3 scripts/run_eta6_vendor_production_source.py --resource runs --limit 5` | 输出 `eta6 resource=runs rows>=1`；dataset-checks/decisions 查询分别可返回 rows，输出不得包含 token 原文 |
| Eta-6 Worker/Mu | `python3 scripts/run_lambda_worker.py --task vendor_production_source_closure --trade-date 2026-07-30` | worker 输出 `task name=vendor_production_source_closure`；Mu 强制触发 `eta6_vendor_production_source_closure_30m` 后 tick 写入且 `lock_acquired=True` |
| Kappa Admin API smoke | `python3 scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18080 --token devtoken,smoketoken --trade-date 2026-07-30` | overview/tenants/projects/tokens/ACL/delivery/schedule/worker/deployment/Xi/Omicron/Pi/Rho/Sigma/Tau/Phi/Chi/Psi/Omega/Omega-5/Alpha-6/Beta-6/Gamma-6/Delta-6/Epsilon-6/Zeta-6/Eta-6/Alpha-2/Beta-2/Gamma-2/Delta-2/Epsilon-3/Zeta-3/Eta-3/Theta-3/Iota-3/Iota-4/Iota-5/Kappa-5/Lambda-5/Mu-5/Nu-5/Xi-5/Omicron-5/Pi-5/Rho-5/Sigma-5/Tau-5/Upsilon-5/Phi-5/Chi-5/Psi-5/Upsilon/usage/console 均 ok，Gamma-6、Delta-6、Epsilon-6、Zeta-6 approval 和 Eta-6 production endpoints 均 `rows>=1`，`console=ok`；单 token 运行时脚本必须能对 429 限流退避重试 |
| Upsilon Console smoke | `python3 scripts/smoke_upsilon_console.py --base-url http://127.0.0.1:18080 --token devtoken` | 输出 `upsilon_console=ok ... markers=73`，Vendor 分组、Pi-5/Rho-5/Sigma-5/Tau-5/Upsilon-5/Phi-5/Chi-5/Psi-5/Omega-5/Alpha-6/Beta-6/Gamma-6/Delta-6/Epsilon-6/Zeta-6/Eta-6 表和 Free Sources 分组均可渲染 |
| Upsilon Playwright desktop | `npx --yes playwright screenshot --full-page --viewport-size=1440,1100 --wait-for-selector='[data-upsilon-controls]' 'http://127.0.0.1:18080/admin/console?token=devtoken' /tmp/sigma5-upsilon-desktop.png` | 生成桌面全页截图和 `/tmp/sigma5-upsilon-desktop-viewport.png` 首屏截图，页面非空且 Sigma-5 overview 指标可见 |
| Upsilon Playwright mobile | `npx --yes playwright screenshot --full-page --viewport-size=390,900 --wait-for-selector='[data-upsilon-controls]' 'http://127.0.0.1:18080/admin/console?token=devtoken' /tmp/sigma5-upsilon-mobile.png` | 生成移动全页截图和 `/tmp/sigma5-upsilon-mobile-viewport.png` 首屏截图，页面非空且表格在容器内滚动 |
| Tau-5 Upsilon Playwright desktop | `npx --yes playwright screenshot --viewport-size=1440,1100 --wait-for-selector='[data-upsilon-controls]' 'http://127.0.0.1:18080/admin/console?token=devtoken' /tmp/tau5-upsilon-desktop-viewport.png` | 生成桌面首屏截图和 `/tmp/tau5-upsilon-desktop-long.png` 长视口截图，页面非空且 Tau-5 Cost Plans、Primary Weight、Budget Usage 指标可见 |
| Tau-5 Upsilon Playwright mobile | `npx --yes playwright screenshot --viewport-size=390,900 --wait-for-selector='[data-upsilon-controls]' 'http://127.0.0.1:18080/admin/console?token=devtoken' /tmp/tau5-upsilon-mobile-viewport.png` | 生成移动首屏截图和 `/tmp/tau5-upsilon-mobile.png` 全页截图，页面非空且表格在容器内滚动 |
| Upsilon-5 Playwright desktop/mobile | `playwright chromium.goto('/admin/console')` | 生成 `/tmp/upsilon5-upsilon-desktop-viewport.png` 和 `/tmp/upsilon5-upsilon-mobile-viewport.png`，DOM 检查 `tables=82 tiles=148 route_executions=true route_policies=true` |
| Phi-5 Upsilon Playwright desktop/mobile | `npx --yes playwright screenshot --viewport-size=1440,1100/390,900 --wait-for-selector='[data-upsilon-controls]' 'http://127.0.0.1:18080/admin/console?token=devtoken'` | 生成 `/tmp/phi5-upsilon-desktop-viewport.png` 和 `/tmp/phi5-upsilon-mobile-viewport.png`，桌面与移动首屏均非空 |
| Chi-5 Upsilon Playwright desktop/mobile | `npx --yes playwright screenshot --viewport-size=1440,1100/390,900 --wait-for-selector='[data-upsilon-controls]' 'http://127.0.0.1:18080/admin/console?token=devtoken'` | 生成 `/tmp/chi5-upsilon-desktop-viewport.png` 和 `/tmp/chi5-upsilon-mobile-viewport.png`，桌面与移动首屏均非空 |
| Kappa 与数据 API 共存 | `.venv312/bin/python scripts/smoke_api_server.py --base-url http://127.0.0.1:18080 --token devtoken --start-date 2024-01-04 --end-date 2024-01-04 --asof-date 2024-01-04 --symbols 600519.SH,000001.SZ` | 原有 health/price/constraints/tradable/matrix 全部 ok |
| Docker app profile smoke | `docker compose --profile app up -d --force-recreate qdata-api && python3 scripts/smoke_upsilon_console.py --base-url http://127.0.0.1:18080 --token devtoken` | `qdata-api=healthy`，容器 API 下 Upsilon/Kappa/数据 API smoke 均 ok |
| Lambda dry-run | `.venv312/bin/python scripts/run_lambda_worker.py --task usage_rollup --task alert_dispatch --trade-date 2026-07-24 --channel-code stdout-high --dry-run --json` | 写入 dry_run worker，预览 18 个 usage 分组和 2 条 alert/channel 组合 |
| Lambda 完整 worker | `.venv312/bin/python scripts/run_lambda_worker.py --once --trade-date 2026-07-24 --channel-code stdout-high --schedule-code daily_bar_vendor_fixture_schedule --json` | usage_rollup 和 alert_dispatch success，vendor schedule warning，failed_count=0，last_suite_id=3 |
| Lambda 最新 rollup | `.venv312/bin/python scripts/run_lambda_worker.py --task usage_rollup --once --trade-date 2026-07-24` | worker_run 最新状态 success，processed 与当前审计分组一致 |
| Kappa worker-runs | `.venv312/bin/python scripts/report_kappa_admin.py --resource worker-runs --limit 5` | 输出最近 worker run，最新 success |
| Kappa worker API smoke | `.venv312/bin/python scripts/smoke_kappa_admin_api.py --base-url http://127.0.0.1:18085 --token iotatoken --trade-date 2026-07-24` | `worker_runs/worker_schedules/worker_heartbeats/worker_schedule_ticks=ok`，console 返回 HTML |
| Mu scheduler smoke | `.venv312/bin/python scripts/smoke_mu_scheduler.py --schedule-code mu_usage_rollup_5m --scheduler-id mu-smoke --trade-date 2026-07-24` | 强制 due 后写入 success tick，并生成 scheduled worker_run |
| Mu 最新 rollup | `.venv312/bin/python scripts/run_mu_scheduler.py --schedule-code mu_usage_rollup_5m --once --force-due --trade-date 2026-07-24` | tick status=success，worker_run_id 写回 schedule tick |
| Mu Docker profile smoke | `docker compose --profile scheduler run --rm mu-scheduler sh -lc "... python scripts/run_mu_scheduler.py --schedule-code mu_alert_dispatch_1m --once --force-due --json"` | 容器内 scheduler 成功连接 Postgres，alert_dispatch 写入 worker_run |
| Nu 健康检查 | `.venv312/bin/python scripts/check_nu_health.py --environment local --release-code nu-local-smoke-20260726 --api-base-url http://127.0.0.1:18085 --api-token iotatoken --write-db --json` | 6 项检查 success，写入 snapshot_id=1、release_id=1 |
| Nu Kappa deployment | `.venv312/bin/python scripts/report_kappa_admin.py --resource deployment-health --limit 5` | 输出 status=success、check_count=6、failed_count=0 |
| Nu Compose profile | `docker compose --profile app --profile scheduler config --services` | 输出 postgres/clickhouse/qdata-api/mu-scheduler |
| Nu rollback | `./scripts/rollback_nu_local.sh` | 默认停止 app/scheduler，保留 Nu 元数据和业务数据 |
| Xi 商业目录初始化 | `.venv312/bin/python scripts/bootstrap_xi_commercial.py --evaluate --write-alerts --as-of-date 2026-07-26` | 写入 a_share_daily_core、quant_starter_monthly、项目订阅和预算策略 |
| Xi 预算评估 | `.venv312/bin/python scripts/report_xi_billing.py --resource evaluate-budgets --budget-code demo_quant-research_monthly_budget --as-of-date 2026-07-26 --write-db --write-alerts` | 输出 status=exceeded、usage=0.160028、budget=0.150000、alert=budget_exceeded |
| Xi Kappa 产品 | `.venv312/bin/python scripts/report_kappa_admin.py --resource data-products --limit 5` | 输出 product_code=a_share_daily_core、dataset_count=4、api_count=4 |
| Xi Kappa 预算 | `.venv312/bin/python scripts/report_kappa_admin.py --resource budget-alerts --limit 10` | 当前 budget_exceeded 为 open，旧 warning/blocked 为 resolved |
| Xi hard limit 决策 | `check_budget_allowed(... api_name="price")` | hard_limit 打开时返回 allowed=False、status=blocked，恢复后正常只告警 |
| Omicron 生成账单 | `.venv312/bin/python scripts/generate_omicron_invoices.py --period-start 2026-07-01 --period-end 2026-07-31 --tenant-code demo --project-code quant-research --json` | 写入 1 张账单，total 与 Xi 用量金额一致 |
| Omicron Kappa 账单 | `.venv312/bin/python scripts/report_kappa_admin.py --resource invoices --limit 10` | 输出 invoice_code、status、total_amount、paid_amount、outstanding_amount |
| Omicron 收入汇总 | `.venv312/bin/python scripts/report_omicron_revenue.py --resource revenue-summary --tenant-code demo --project-code quant-research` | 输出 total_amount、paid_amount、outstanding_amount |
| Omicron 回款状态 | `.venv312/bin/python scripts/update_omicron_invoice_status.py --invoice-code inv-demo-quant-research-a_share_daily_core-20260701-20260731 --status paid --json` | status=paid、paid_amount=total_amount、outstanding_amount=0 |
| Pi 5/20/60 suite | `.venv312/bin/python scripts/benchmark_vendor_universe.py --primary-provider csv --secondary-provider vendor_http --start-date 2024-01-04 --end-date 2024-01-04 --target-trade-days 5/20/60 --symbols 600519.SH,000001.SZ --shard-size 1 --write-db` | 写入 3 条 target suite |
| Pi readiness | `.venv312/bin/python scripts/report_pi_vendor_readiness.py --dataset-code daily_bar --source-code vendor_http --primary-source-code csv --windows 5,20,60 --json` | status=watch、recommendation=approve_backup、role=backup、suite_count=3 |
| Pi Kappa readiness | `.venv312/bin/python scripts/report_kappa_admin.py --resource vendor-readiness --source-code vendor_http --limit 10` | 输出 review_code、status=watch、recommendation=approve_backup、recommended_role=backup |
| Rho 生成经营快照 | `.venv312/bin/python scripts/report_rho_revenue.py --resource generate-all --period-start 2026-07-01 --period-end 2026-07-31 --as-of-date 2026-07-26 --tenant-code demo --project-code quant-research --json` | 写入 reconciliation=1、reconciliation_lines=4、ar_aging=1、customer_health=1 |
| Rho 收入对账 | `.venv312/bin/python scripts/report_kappa_admin.py --resource revenue-reconciliation --tenant-code demo --limit 10` | status=matched、invoice_total=0.16002800、recomputed_total=0.16002800、amount_delta=0 |
| Rho 对账明细 | `.venv312/bin/python scripts/report_kappa_admin.py --resource revenue-reconciliation-lines --reconciliation-code rho-recon-demo-quant-research-a_share_daily_core-20260701-20260731-20260726 --limit 10` | 输出 4 行 matched，覆盖 constraints/matrix/price/tradable-universe |
| Rho AR aging | `.venv312/bin/python scripts/report_kappa_admin.py --resource ar-aging --as-of-date 2026-07-26 --limit 10` | status=current、outstanding_amount=0、overdue_invoice_count=0 |
| Rho 客户健康 | `.venv312/bin/python scripts/report_kappa_admin.py --resource customer-health --as-of-date 2026-07-26 --limit 10` | status=active、retention_signal=healthy、health_score=100 |
| Sigma 运行采集 | `.venv312/bin/python scripts/report_sigma_runtime.py --resource collect --environment local --report-date 2026-07-26` | 写入 metrics=8、capacity_alerts=1、daily_status=warning |
| Sigma 运行指标 | `.venv312/bin/python scripts/report_kappa_admin.py --resource runtime-metrics --environment local --limit 10` | 输出 8 条指标，`api_request_count_7d=271` 为 warning |
| Sigma 运行日报 | `.venv312/bin/python scripts/report_kappa_admin.py --resource runtime-daily-reports --environment local --limit 5` | `sigma-runtime-local-20260726` status=warning、api_request_count=213、api_failed_count=0 |
| Sigma 容量告警 | `.venv312/bin/python scripts/report_kappa_admin.py --resource capacity-alerts --environment local --limit 5` | open 容量告警 1 条，metric_value=271、threshold=200、severity=medium |
| Tau migration | `./scripts/apply_postgres_migrations.sh` | `0020_postgresql_payments_tau.sql` 应用成功，5 张 Tau 表存在 |
| Tau demo 回款 | `.venv312/bin/python scripts/report_tau_payments.py --resource bootstrap-demo --as-of-date 2026-07-27 --tenant-code demo --project-code quant-research --amount 100.00000000` | invoice paid、batch matched、matches=1、matched_amount=100.00000000 |
| Tau 回款批次 | `.venv312/bin/python scripts/report_tau_payments.py --resource payment-batches --batch-code tau-demo-payments-20260727` | status=matched、transaction_count=1、matched_count=1、unmatched_count=0 |
| Tau 付款流水 | `.venv312/bin/python scripts/report_tau_payments.py --resource payments --batch-code tau-demo-payments-20260727` | transaction_code=tau-pay-tau-demo-payment-20260727、status=matched、invoice_code 指向 Tau demo invoice |
| Tau 匹配记录 | `.venv312/bin/python scripts/report_tau_payments.py --resource payment-matches --batch-code tau-demo-payments-20260727` | status=matched、match_type=auto_exact、invoice_status=paid |
| Tau 收入 ledger | `.venv312/bin/python scripts/report_tau_payments.py --resource revenue-ledger --transaction-code tau-pay-tau-demo-payment-20260727` | 输出 payment_received 和 payment_matched 两条分录 |

## 不通过条件

- 全市场任务无法解析任何股票池。
- 同一日期不同 job/source 的质量报告互相覆盖，无法看到各自完整性。
- 缺失证券没有写入 `pipeline_run.missing_symbols`。
- 交易所拆分或缺失解释为空，导致无法定位缺失来源。
- 非交易日仍执行 provider 拉数并入库。
- `smoke_full_market_daily.py` 查不到对应 pipeline_run 或 SDK 样例行情。
- `partial_success/failed` 没有进入 repair queue。
- 日报或压测脚本不能在本地 SQL backend 环境执行。
- 复权因子或交易约束只能随日线入库，不能独立补跑。
- 可交易股票池不能排除停牌/ST/新股/退市期。
- 矩阵导出文件缺行、缺列或没有审计记录。
- 分钟线同步后 SDK `frequency="1m"` 查不到数据。
- 多源冲突不能落到字段级，或无法区分主源和备源。
- REST 受保护接口无 token 仍可访问。
- API 成功请求没有写入 `api_request_audit`。
- Arrow 依赖缺失时服务崩溃而非返回可解释错误。
- 运维看板不能同时展示 pipeline、质量、多源冲突、API 和告警摘要。
- SLA 策略创建后不能生成幂等告警。
- 看板快照不能落库，导致日报无法复现。
- API 审计报表不能显示失败率或慢接口。
- 供应商 profile 不能记录授权、限频或启用数据集。
- `vendor_http` 不能在缺少商业账号时用 fixture 完成同一接入链路验收。
- benchmark 结果不能同时落到供应商评分表和多源质量表。
- provider 错误不能归因到 auth/rate_limit/timeout/network/schema 等可处理类型。
- AkShare 真实第二源 smoke 不可用时没有清晰错误提示或替代 fixture 验收路径。
- vendor 字段映射不能处理单位转换或误丢 0 值。
- 分片 benchmark 只能输出子任务，不能输出 suite 聚合评分。
- Provider SLA 不能从供应商评分和错误事件生成告警。
- 决策报告不能区分 primary、backup、research_only 和 reject。
- 告警通知没有投递记录，或无法按通道、告警和时间定位重试。
- 数据库 token 绑定租户后仍能访问未授权 dataset。
- API 用量日报重复 rollup 后行数膨胀。
- 供应商压测 schedule 不能复用 Theta suite 或不能回写最近运行结果。
- 新增 dataset 字段映射只能写死在 daily_bar，不能按 dataset 选择默认规则。
- `/admin/*` 不校验 admin scope，或普通 read token 可访问。
- Kappa token 列表返回完整 token_hash 或明文 token。
- `/admin/console` 无法在真实 API 服务中打开。
- Kappa API 接入后破坏原有量化数据查询端点。
- worker 执行后没有写入 `worker_run` 或 `worker_task_run`。
- dry-run 直接触发供应商压测或真实外部通知。
- `usage_rollup` 重复执行导致 `api_usage_daily` 行数异常膨胀。
- schedule suite 返回 warning 时被错误计为 failed。
- Kappa 无法查询 `/admin/worker-runs`。
- Mu scheduler 执行后没有写入 `worker_schedule_tick`。
- 同一 schedule 被两个 scheduler 同时真实执行，未出现锁保护。
- scheduler 停止或失败后无法从 `worker_heartbeat` 定位最后心跳。
- `/admin/worker-schedules`、`/admin/worker-heartbeats` 或 `/admin/worker-schedule-ticks` 无法查询。
- Docker profile 下 `mu-scheduler` 不能连接 Compose PostgreSQL。
- Nu 健康检查不能写入 release/snapshot/check/event，或 Kappa 查不到部署健康。
- Nu 回滚脚本默认删除业务数据或部署元数据。
- Xi 产品不能绑定 dataset/API，导致预算无法按产品过滤用量。
- Xi 价格规则不能按 cost_unit/request/row 计算金额。
- Xi 预算评估不能写入 `budget_usage_snapshot` 或不能生成/升级/恢复 `budget_alert`。
- Xi hard limit 打开后仍允许超预算 DB token 查询，或误拦截未配置预算的兼容 token。
- Kappa 无法查询 Xi 产品、价格、订阅、预算和预算告警资源。
- Omicron 不能从订阅和用量生成账单，或重复生成导致同账期多张主账单。
- Omicron-5 缺少 `vendor_contract_profile`、`vendor_contract_dataset_entitlement` 或 `vendor_procurement_readiness_snapshot`，导致主供应商采购证据无法落库。
- Omicron-5 在合同未 active、商用未 clear、再分发 unknown/no、生产使用未允许、schema/field mapping 未 validated、quota/SLA 缺失或 live 证据 blocked 时仍输出 `primary_candidate`。
- Omicron-5 worker dry-run 写入 snapshot，或 review_required/blocked/no_contract 被错误计为 success。
- Kappa/Upsilon 无法查询或展示 Omicron-5 合同 profile、dataset entitlement 和 procurement readiness。
- Pi-5 缺少 `vendor_primary_promotion_run` 或 `vendor_primary_promotion_dataset_result`，导致切主证据无法审计。
- Pi-5 在 Omicron-5、Pi 5/20/60、Theta-3 canary/full-market 或签批证据缺失时仍输出 `approved_for_primary`。
- Pi-5 默认 review-only、dry-run 或定时任务在未显式 `--apply-routing` 时改写 `source_priority`。
- Pi-5 只要有任一 dataset blocked/canary_required/full_market_required/pending_signoff，却仍把整体 run 标记为 success 或 applied。
- Kappa/Upsilon 无法查询或展示 Pi-5 promotion run/result 和 overview 指标。
- Rho-5 缺少 `vendor_post_promotion_monitor_run` 或 `vendor_post_promotion_dataset_monitor`，导致切主后健康、影子对账和回滚证据无法审计。
- Rho-5 在没有 applied Pi-5 promotion 时返回空白、success 或 healthy，而不是 `no_applied_promotion`。
- Rho-5 当前主源不是 promoted source 时仍允许 rollback apply，或缺少前一主源时仍输出 `rollback_allowed=true`。
- Rho-5 默认 review-only、dry-run 或定时任务在未显式 `--apply-rollback` 时改写 `source_priority`。
- Kappa/Upsilon 无法查询或展示 Rho-5 post-promotion monitor/result 和 overview 指标。
- Sigma-5 缺少 `vendor_primary_stability_snapshot` 或 `vendor_primary_stability_dataset_snapshot`，导致主供应商长期 SLA、容量、成本和调度稳定性不可审计。
- Sigma-5 在没有 applied Pi-5 promotion 或当前主源未切到供应商时返回空白、success 或 healthy，而不是 `no_primary_promotion`。
- Sigma-5 critical SLA、capacity alert、Rho-5 rollback 或 scheduler backlog 风险被 worker 映射为 success。
- Kappa/Upsilon 无法查询或展示 Sigma-5 primary stability snapshot/dataset 和 overview 指标。
- Tau-5 缺少 `vendor_cost_optimization_snapshot`、`vendor_route_weight_plan` 或 `vendor_budget_stress_dataset_snapshot`，导致成本、quota 和路由权重建议不可审计。
- Tau-5 在没有 applied Pi-5 promotion 或当前主源未切到供应商时返回 optimized/watch 且给出供应商 primary weight，而不是 `no_primary_promotion` 和 `recommended_primary_weight_pct=0`。
- Tau-5 over_budget、quota_risk、blocked 或 no_primary_promotion 被 worker 映射为 success，导致成本和 quota 风险被静默吞掉。
- Kappa/Upsilon 无法查询或展示 Tau-5 cost optimization、route weight plan、budget stress 和 overview 指标。
- Upsilon-5 缺少 `vendor_route_weight_execution_run`、dataset execution、rollout stage 或 `source_route_weight_policy`，导致权重执行、审批、灰度和回滚不可审计。
- Upsilon-5 在默认 review-only/pending approval 下写入 active policy，或直接改写 `source_priority`。
- Upsilon-5 在没有 applied Pi-5 promotion、Tau-5 primary weight 为 0、over_budget/quota_risk 未审批时仍应用供应商 primary 权重。
- Upsilon-5 rollback 请求没有留下 rollback_recommended/rolled_back 证据，或未经审批直接写入回滚 policy。
- Kappa/Upsilon 无法查询或展示 Upsilon-5 route execution、dataset、stage、policy 和 overview 指标。
- Phi-5 缺少 `source_route_decision_audit`，导致真实 API/sync 路由决策不可审计。
- Phi-5 在没有 PostgreSQL DSN 或没有 active policy 时改变默认 requested source 行为。
- Phi-5 selected provider 失败或无数据时没有尝试 fallback，或没有记录 final source、fallback_applied 和 decision_status。
- Phi-5 API 响应缺少 `meta.route_policy`，或路由审计失败直接破坏原有数据查询。
- Kappa/Upsilon 无法查询或展示 `/admin/source-route-decisions`、source route overview 指标和 Source Route Decisions 表。
- Chi-5 缺少 `source_route_health_snapshot`、`source_route_circuit_breaker` 或 `source_route_recovery_probe`，导致路由健康、熔断和恢复探测不可审计。
- Chi-5 在 source+dataset 失败率、空响应或延迟超阈值时没有打开/保持 circuit，或恢复探测失败却静默关闭 circuit。
- Phi-5 resolver 不读取 open circuit，导致已熔断源继续被优先选择；或所有候选 open 时没有 fail-open 兼容路径。
- Kappa/Upsilon 无法查询或展示 `/admin/source-route-health`、`/admin/source-route-circuit-breakers`、`/admin/source-route-recovery-probes` 和 Source Route Health/Circuit/Probe 表。
- Psi-5 缺少 `source_route_incident_action`，导致路由故障处置动作、审批状态和恢复确认不可审计。
- Psi-5 对 `circuit_open` 未生成 approval-required 高风险动作，或未经审批直接改写 `source_priority`、route policy、合同或授权。
- Kappa/Upsilon 无法查询或展示 `/admin/source-route-incident-actions`、source route incident overview 指标和 Source Route Incident Actions 表。
- Omega-5 缺少 `source_route_incident_control`，导致路由故障从审批到通知、执行和回滚不可追溯。
- Omega-5 高风险 incident action 未生成 pending approval，或 pending/rejected 时仍执行动作。
- Omega-5 未显式允许企业微信外发时产生真实外部副作用，或企业微信 webhook URL/密钥明文出现在数据库、CLI、Kappa API 或 Upsilon HTML。
- Kappa/Upsilon 无法查询或展示 `/admin/source-route-incident-controls`、source route incident control overview 指标和 Source Route Incident Controls 表。
- Alpha-6 缺少 `source_route_incident_control_health_snapshot`，或无法查询/展示 `/admin/source-route-incident-control-health` 与 Source Route Incident Control Health 表。
- Alpha-6 未能识别 approval overdue、执行失败率超阈值、缺回滚或 stale schedule，或健康检查产生真实审批/通知/执行/回滚副作用。
- Beta-6 缺少 `source_route_incident_operation_batch` 或 `source_route_incident_operation_item`，导致批量审批、通知降噪和压测证据不可审计。
- Beta-6 默认 hold/dry-run/未 apply 时改变审批状态、外发企业微信或执行真实路由变更。
- Beta-6 批量 approve/reject 绕过 Omega approval 控制面，或 Kappa/Upsilon 无法查询/展示 Operation Batches/Items。
- Gamma-6 POST 无需 admin token 即可写入，或同一幂等键重放创建重复 command/signature。
- Gamma-6 quorum 未满足时改写 Omega approval，或 quorum 满足后绕过 Omega approval 控制面直接改业务状态。
- Gamma-6 缺少 approval command/item/signature 审计表，或 Kappa/Upsilon 无法查询/展示三张表和行级按钮。
- Delta-6 回调无 HMAC 签名、签名错误、时间戳偏移过大或 nonce 重放仍能创建 Gamma-6 command/signature。
- Delta-6 允许 requester 自批，或签批人缺少 scoped approver/risk admin 角色仍能通过治理。
- Delta-6 超时、策略拒绝、缺角色、无效签名、replay 或撤销没有写入 escalation 审计。
- Delta-6 缺少 role/policy/callback/escalation 审计表，或 Kappa/Upsilon 无法查询/展示四张治理表。
- Epsilon-6 同一 approval target 并发回调没有 advisory lock 证据，或 lock busy 仍进入 Delta-6/Gamma-6。
- Epsilon-6 允许终态 approval 被 stale callback 改写，或没有写入 state transition 阻断证据。
- Epsilon-6 audit hash chain 缺少 previous/payload/entry hash，或篡改 canonical_payload 后仍校验通过。
- Epsilon-6 SLA 自动处置产生真实外部副作用，或超时 escalation 没有生成 planned SLA action。
- Epsilon-6 recovery drill 不验证 DB reconnect/hash chain/lock key/state guard，或 Kappa/Upsilon 无法查询/展示五张韧性表。
- Epsilon-6 `worker_schedule` 已创建但 Lambda worker 不支持 `route_incident_approval_resilience`，或 Mu 强制触发后没有写入 tick/worker_run。
- Zeta-6 把 current/next callback secret 原文写入数据库、CLI、Kappa API、Upsilon HTML 或 API 响应。
- Zeta-6 对 next secret 签名回调不能正确选择 next secret 并交给 Epsilon-6/Delta-6 复验。
- Zeta-6 preflight 缺少 DB/audit/recovery/schedule/secret 检查，或 audit export 缺少 package_hash/broken_hash_count。
- Zeta-6 `worker_schedule` 已创建但 Lambda worker 不支持 `route_incident_approval_release`，或 Kappa/Upsilon 无法查询/展示四张发布审计表。
- Eta-6 把 `QDATA_VENDOR_TOKEN` 原文、Authorization header 或原始供应商响应正文写入数据库、CLI、Kappa API、Upsilon HTML 或 API 响应。
- Eta-6 缺少真实 vendor env、合同/entitlement、full-market live pilot、primary promotion、稳定性、成本或 route execution 证据时仍返回 production_ready/monitoring。
- Eta-6 `worker_schedule` 已创建但 Lambda worker 不支持 `vendor_production_source_closure`，或 Kappa/Upsilon 无法查询/展示 production source runs、dataset checks、decisions。
- 账单明细金额与价格规则不一致，或缺少 API/metric 级对账信息。
- 回款后 `paid_amount`、`outstanding_amount` 或 status 不一致。
- Kappa 无法查询 Omicron 账单、明细、事件或收入汇总资源。
- Pi 缺少 5/20/60 任一必要窗口时仍给出 primary 上线建议。
- Pi 复核结论无法解释阻塞原因或没有保留窗口级指标。
- Kappa 无法查询 Pi readiness 总结或窗口明细。
- Rho 重算直接覆盖 Omicron 原始账单，导致无法审计历史开票事实。
- Rho 对账只给总金额，不保留 API/metric 行级差异。
- 已结清客户无法生成 AR aging 或 customer health 快照。
- Kappa 无法查询 Rho 对账、AR aging 或客户健康资源。
- Sigma 运行采集无法写入日志、指标、日报或容量告警。
- Sigma 超阈值指标没有同步写入 `capacity_alert` 和 `alert_event`。
- Kappa 无法查询 Sigma 运行日志、指标、日报或容量告警资源。
- Tau 重复匹配已 paid 发票时把已匹配流水改成 unmatched。
- Tau 导入同一外部交易号导致流水或 ledger 分录重复膨胀。
- Kappa 无法查询 Tau 回款批次、付款流水、匹配、ledger 或 FX rate 资源。
- `/admin/console` 缺少搜索、状态筛选、分组切换或关键 Tau/Sigma/Rho/Phi/Chi/Psi/Omega 区块。
- Upsilon 页面未转义动态数据，导致 `<ops>` 等值直接进入 HTML。
- Upsilon 页面在桌面或移动视口无法渲染、出现空白页或破坏原有 Kappa/数据 API smoke。
- Phi 不能把质量、供应商、运行、商业和回款事实聚合成同一 run。
- Phi 信号缺少 source_table/source_ref/message，导致决策不可审计。
- Phi 决策没有 action/status/severity/reason，无法指导自动化或人工处理。
- high/critical 或 block/escalate 决策没有生成升级事件。
- Kappa 无法查询 Phi runs/signals/decisions/escalations，或 Upsilon Strategy 分组缺失。
- principal 级 ACL 可被同租户或同项目其他主体通过 fallback 误用。
- 数据接口在 DB token 下没有写入 `access_decision_audit`，或审计缺少 allow/deny、effective_scope、reason、api_name、request_id。
- Chi 项目治理快照缺少用量、拒绝访问、预算、账单、开放动作或风险评分，或同日重跑产生重复快照。
- warning/critical 项目没有生成治理动作，或同一项目同日同 action_type 重跑导致动作重复膨胀。
- Kappa 无法查询 Chi access decisions/project governance/governance actions，或 Upsilon Governance 分组缺失。
- Psi 不能从 Phi/Chi 生成统一 action，或缺少 planned_effect/rollback_hint。
- dry-run 改写了源事实，或没有记录 would_execute/requires_approval。
- 高风险 execute 未审批仍直接执行。
- 同一 idempotency_key 重复真实执行，导致重复暂停、重复降级或重复通知。
- Kappa 无法查询 Psi automation runs/actions，或 Upsilon Automation 分组缺少 Automation Runs/Actions。
- Omega 高风险动作 pending/rejected 时仍能执行。
- Omega webhook/script 在未显式允许外部执行时产生外部副作用。
- Omega 失败动作没有 retry_count/next_retry_at，或超过 max_retry_count 后仍无限重试。
- Omega rollback 缺少 rollback_plan/rollback_result，或回滚演练覆盖了原执行 attempt。
- Kappa 无法查询 Omega approval/executor/attempt/rollback，或敏感 config/payload 未脱敏。
- Gamma-2/Delta-2 把 webhook URL 或密钥明文写入数据库、Kappa API、CLI 输出或 Upsilon HTML。
- Delta-2 未显式 `--allow-external` 时仍向企业微信发消息。
- Delta-2 缺少 `QDATA_DELTA2_WECOM_WEBHOOK_URL` 时 `--require-live` 仍返回成功。
- Delta-2 企业微信 HTTP 成功但 `errcode` 非 0 时被误标记为 success。
- Kappa 无法查询 `/admin/automation-live-receipts`，或 Upsilon Automation 分组缺少 Automation Live Receipts。
- Epsilon-3 未显式 `--allow-live` 时仍调用外部供应商。
- Epsilon-3 缺少 `QDATA_VENDOR_BASE_URL` 或 bearer token 时 `--require-live` 仍返回成功。
- Epsilon-3 把真实供应商 token 明文写入数据库、CLI、Kappa API 或 Upsilon HTML。
- Epsilon-3 未完成 5/20/60 任一必要 live benchmark window 时仍给出 primary 上线成功 gate。
- Kappa 无法查询 `/admin/vendor-live-gates`，或 Upsilon Vendor 分组缺少 Vendor Live Gates。
- Zeta-3 未显式 `--allow-live --run-benchmarks` 时仍调用外部供应商。
- Zeta-3 缺少 `QDATA_VENDOR_BASE_URL` 或 bearer token 时 `--require-live` 仍返回成功。
- Zeta-3 把真实供应商 token 明文写入数据库、CLI、Kappa API 或 Upsilon HTML。
- Zeta-3 onboarding 没有写入 run/result 两级审计，或 dataset result 无法追溯关联 Epsilon-3 gate。
- Zeta-3 未启用 dataset 没有明确标记为 `dataset_not_enabled:<dataset_code>`。
- Zeta-3 缺少合同、再分发授权或 rate limit 时仍给出 primary_candidate。
- Kappa 无法查询 `/admin/vendor-onboarding-runs` 或 `/admin/vendor-onboarding-results`，或 Upsilon Vendor 分组缺少 onboarding 表格。
- Eta-3 未显式 `--allow-live` 时仍调用外部供应商 endpoint。
- Eta-3 把真实供应商 token、Authorization header 或原始响应正文写入数据库、CLI、Kappa API 或 Upsilon HTML。
- Eta-3 未显式 `--allow-profile-write` 时改写供应商 profile。
- Eta-3 缺少 `QDATA_VENDOR_BASE_URL` 或 bearer token 时 `--require-live` 仍返回成功。
- Eta-3 closure/probe 没有写入两级审计，或 probe 没有记录 expected_fields/missing_fields/schema_status。
- Eta-3 缺少合同、再分发授权、rate limit、完整 dataset 或 endpoint schema 通过证据时仍给出 primary_candidate。
- Kappa 无法查询 `/admin/vendor-live-closures` 或 `/admin/vendor-live-probes`，或 Upsilon Vendor 分组缺少 closure/probe 表格。
- Theta-3 未显式 `--allow-live --require-live` 时仍调用外部供应商 endpoint。
- Theta-3 把真实供应商 token、Authorization header 或原始响应正文写入数据库、CLI、Kappa API 或 Upsilon HTML。
- Theta-3 缺少 pilot run/result 两级审计，或 dataset result 无法追溯 closure/probe/gate 证据。
- Theta-3 blocked/failed pilot 的 signoff_status 进入 pending_review/approved。
- Theta-3 缺少 successful closure/schema/onboarding/benchmark 证据时仍给出 primary_candidate。
- Theta-3 risk_level 不能从 dataset failed/blocked/warning/success 状态聚合。
- Kappa 无法查询 `/admin/vendor-live-pilots` 或 `/admin/vendor-live-pilot-results`，或 Upsilon Vendor 分组缺少 pilot/result 表格。
- Iota-3 默认 smoke 调用了外部免费源网站，或没有显式 `--allow-external` 仍产生外部请求。
- Iota-3 没有写入 free_source_fabric_run/free_source_fabric_dataset_result 两级审计，导致免费源覆盖、冲突和授权判断不可追溯。
- Iota-3 把 research_only/review_required 免费源推荐为 primary_candidate，或 `--require-commercial-clearance` 时没有 blocked。
- Iota-3 免费源结果只保存原始响应正文，缺少 coverage_status/consistency_status/license_status/freshness_status 等结构化状态。
- Kappa 无法查询 `/admin/free-source-fabric-runs` 或 `/admin/free-source-fabric-results`，或 Upsilon Free Sources 分组缺少 fabric run/result 表格。
- Iota-4 smoke 没有真实执行任何外部免费源，却返回 canary ok。
- Iota-4 把 AKShare warning/research_only 误当成商业生产可用，或输出中缺少 commercial_clearance。
- Iota-4 canary 结果没有写入 Iota-3 fabric run/result，导致 Kappa/Upsilon 无法查询。
- Iota-4 compare-local 把本地 fixture 当成真实价格基准并据此做生产主源结论。
- Iota-5 registry 对 baostock/tushare_free/official public 源仍返回 provider_not_implemented，而不是结构化 adapter 或 scaffold reason。
- Iota-5 BaoStock socket 不设超时，导致公网不可达时 smoke 长时间挂住。
- Iota-5 没有 TuShare token 时仍返回成功，或把 legacy/free quota 当成商业授权。
- Iota-5 degraded 被伪装成 ok，或者没有列出 baostock、tushare、official public 的具体降级原因。
- Iota-5 免费源被推荐为 commercial primary_candidate。
- Kappa-5 没有写入 free_source_reliability_snapshot，导致免费源 source+dataset 可靠性不可追溯。
- Kappa-5 把 local_smoke/research_only/review_required/blocked 免费源推荐为商业生产主源。
- Kappa-5 不展示连续失败、授权阻塞、商业清晰度或恢复动作，导致自动降级不可解释。
- Kappa 无法查询 `/admin/free-source-reliability`，或 Upsilon Free Sources 分组缺少 Free Source Reliability 表格。
- Lambda-5 没有写入 free_source_recovery_run/free_source_recovery_action，导致恢复动作不可审计。
- Lambda-5 dry-run 写入了恢复表或告警。
- Lambda-5 把 rejected/blocked 免费源直接排入生产 fallback，而不是 manual_review/alert。
- Lambda-5 对 degraded 可重试源不生成 retry_canary、next_retry_at 或退避时间。
- Lambda-5 告警未写入通用 `alert_event`，或 `alert_type` 不可被 CHECK 约束接受。
- Kappa 无法查询 `/admin/free-source-recovery-runs` 或 `/admin/free-source-recovery-actions`，或 Upsilon Free Sources 分组缺少恢复表格。
- Mu-5 没有写入 `free_source_recovery_execution`，导致恢复动作执行不可审计。
- Mu-5 `retry_canary` 在 Iota-5 degraded/failed 时仍回写 recovered。
- Mu-5 `manual_review` 没有生成 `automation_action`、`automation_approval` 或企业微信 blocked/success receipt。
- Mu-5 未显式 `--allow-wecom-external` 时仍向企业微信外发消息。
- Mu-5 把 TuShare token、Authorization header、企业微信 webhook URL 或未确认授权的原始网页正文写入数据库、CLI、Kappa API 或 Upsilon HTML。
- Mu-5 重复调度同一已完成 action 时没有 suppressed execution，导致重复审批或重复通知。
- Kappa 无法查询 `/admin/free-source-recovery-executions`，或 Upsilon Free Sources 分组缺少恢复 execution 表格。
- Nu-5 没有写入 `free_source_recovery_health_snapshot`，导致恢复执行闭环长期健康不可审计。
- Nu-5 没有识别审批超 SLA、backlog 超阈值、失败率过高、Mu-5 schedule 陈旧或 worker failed。
- Nu-5 health status 为 critical 时 worker task 仍返回 success，导致 Mu scheduler 无法感知风险。
- Nu-5 runbook_actions 缺少审批、backlog、失败、调度陈旧等可执行处置建议。
- Kappa 无法查询 `/admin/free-source-recovery-health`，或 Upsilon Free Sources 分组缺少恢复 health 表格。
- Xi-5 没有写入 `free_source_admission_profile` 或 `free_source_admission_snapshot`，导致免费源授权准入不可审计。
- Xi-5 在缺少合同 active、商用许可 clear、再分发 yes、条款 approved、限频/日配额或可靠性达标证据时仍给出 `primary_candidate`。
- Xi-5 对 research_only、review_required、local_smoke 或未确认转授权的源没有输出 blocking_issues 和 required_actions。
- Xi-5 worker dry-run 写库，或 blocked/review_required/no_data 被错误映射为 worker success。
- Kappa 无法查询 `/admin/free-source-admission-profiles` 或 `/admin/free-source-admission`，或 Upsilon Free Sources 分组缺少准入矩阵表格。
