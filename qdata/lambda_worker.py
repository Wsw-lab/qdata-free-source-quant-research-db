from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from typing import Any, Callable

from qdata.backend_utils import date_range, normalize_rows
from qdata.alpha6_route_incident_control_health import run_route_incident_control_health
from qdata.beta6_route_incident_ops import run_route_incident_operations
from qdata.chi5_route_feedback import run_source_route_feedback_monitor
from qdata.epsilon6_route_incident_approval_resilience import (
    run_approval_recovery_drill,
    run_approval_sla_automation,
    verify_approval_audit_chain,
)
from qdata.eta6_vendor_production_source import run_vendor_production_source_closure
from qdata.exceptions import QDataValidationError
from qdata.iota import SEVERITY_ORDER, dispatch_alert_notifications, rollup_api_usage_daily, run_vendor_benchmark_schedule
from qdata.lambda5_free_source_recovery import run_free_source_recovery
from qdata.mu5_free_source_recovery_executor import execute_free_source_recovery_actions
from qdata.nu5_free_source_recovery_health import run_free_source_recovery_health
from qdata.omicron5_vendor_contract import run_vendor_contract_readiness_review
from qdata.omega5_route_incident_control import run_route_incident_control
from qdata.pi5_vendor_primary_promotion import run_vendor_primary_promotion_review
from qdata.psi_automation import run_psi_automation
from qdata.rho5_post_promotion_monitor import run_post_promotion_monitor
from qdata.sigma5_vendor_primary_stability import run_vendor_primary_stability_monitor
from qdata.tau5_vendor_cost_optimization import run_vendor_cost_optimizer
from qdata.upsilon5_route_weight_execution import run_vendor_route_weight_execution
from qdata.xi5_free_source_admission import run_free_source_admission_review
from qdata.zeta6_route_incident_approval_release import export_approval_audit_package, run_release_preflight


WORKER_TASKS = (
    "usage_rollup",
    "alert_dispatch",
    "vendor_benchmark_schedule",
    "free_source_recovery",
    "free_source_recovery_execute",
    "free_source_recovery_health",
    "free_source_admission_review",
    "vendor_contract_readiness_review",
    "vendor_primary_promotion_review",
    "vendor_post_promotion_monitor",
    "vendor_primary_stability_monitor",
    "vendor_cost_optimizer",
    "vendor_route_weight_executor",
    "vendor_production_source_closure",
    "source_route_feedback_monitor",
    "route_incident_automation",
    "route_incident_control",
    "route_incident_control_health",
    "route_incident_operations",
    "route_incident_approval_resilience",
    "route_incident_approval_release",
)


@dataclass(frozen=True)
class LambdaWorkerContext:
    postgres_dsn: str | None
    start_date: str
    end_date: str
    dry_run: bool
    trigger_mode: str = "manual"
    channel_code: str | None = None
    alert_limit: int = 50
    schedule_code: str | None = None
    include_manual_schedules: bool = False
    cost_per_request: float = 1.0
    cost_per_1000_rows: float = 0.1
    free_source_lookback_hours: int = 72
    free_source_max_actions: int = 50
    free_source_min_retry_score: float = 75.0
    free_source_write_alerts: bool = True
    mu5_max_actions: int = 20
    mu5_start_date: str = "2024-01-04"
    mu5_end_date: str = "2024-01-04"
    mu5_execute_retry_canary: bool = True
    mu5_request_manual_review: bool = True
    mu5_notify_wecom: bool = True
    mu5_allow_wecom_external: bool = False
    mu5_baostock_timeout_seconds: float = 3.0
    nu5_lookback_hours: int = 24
    nu5_approval_sla_hours: int = 4
    nu5_max_backlog_actions: int = 50
    nu5_max_failure_rate: float = 0.5
    nu5_max_stale_minutes: int = 90
    xi5_lookback_days: int = 30
    xi5_min_validator_score: float = 55.0
    xi5_min_backup_score: float = 75.0
    xi5_min_primary_score: float = 90.0
    xi5_min_coverage_rate: float = 0.95
    xi5_max_conflict_rate_bps: float = 5.0
    omicron5_min_sla_uptime_pct: float = 99.5
    omicron5_min_rate_limit_per_min: int = 60
    omicron5_require_live_evidence: bool = False
    pi5_promotion_scope: str = "full_market"
    pi5_require_full_market: bool = True
    pi5_require_signoff: bool = True
    pi5_apply_routing: bool = False
    pi5_target_priority: int = 0
    rho5_monitor_scope: str = "post_promotion"
    rho5_require_applied_promotion: bool = True
    rho5_apply_rollback: bool = False
    rho5_shadow_window_hours: int = 24
    rho5_max_conflict_rate_bps: float = 5.0
    rho5_max_failure_rate: float = 0.01
    rho5_max_stale_minutes: int = 90
    sigma5_monitor_scope: str = "primary_source"
    sigma5_lookback_hours: int = 24
    sigma5_capacity_window_days: int = 7
    sigma5_min_success_rate: float = 0.995
    sigma5_max_error_rate: float = 0.005
    sigma5_max_latency_p95_ms: float = 2000.0
    sigma5_max_timeout_rate: float = 0.01
    sigma5_max_cost_units: float = 500.0
    sigma5_max_scheduler_lag_minutes: int = 90
    sigma5_max_backlog_count: int = 50
    sigma5_max_post_promotion_no_applied_count: int = 0
    tau5_optimization_scope: str = "primary_source"
    tau5_lookback_hours: int = 24
    tau5_forecast_window_days: int = 30
    tau5_monthly_budget_amount: float = 10000.0
    tau5_max_budget_usage_pct: float = 0.85
    tau5_max_daily_quota_usage_pct: float = 0.85
    tau5_max_monthly_quota_usage_pct: float = 0.85
    tau5_min_stability_score: float = 70.0
    tau5_cost_safety_margin_pct: float = 0.15
    tau5_default_unit_cost: float = 0.01
    tau5_stress_multipliers: tuple[float, ...] = (1.0, 5.0, 10.0)
    upsilon5_execution_scope: str = "primary_source"
    upsilon5_execution_mode: str = "review_only"
    upsilon5_approval_policy: str = "manual_required"
    upsilon5_approval_status: str = "pending"
    upsilon5_rollout_policy: str = "gradual"
    upsilon5_rollout_stages: tuple[float, ...] = (10.0, 30.0, 60.0, 90.0)
    upsilon5_current_stage_sequence: int = 1
    upsilon5_max_initial_primary_weight_pct: float = 10.0
    upsilon5_allow_over_budget: bool = False
    upsilon5_allow_quota_risk: bool = False
    upsilon5_rollback_requested: bool = False
    chi5_lookback_hours: int = 24
    chi5_min_request_count: int = 1
    chi5_min_success_rate: float = 0.95
    chi5_max_failure_rate: float = 0.10
    chi5_max_fallback_rate: float = 0.20
    chi5_max_empty_rate: float = 0.20
    chi5_max_latency_p95_ms: float = 2000.0
    chi5_circuit_open_minutes: int = 30
    chi5_recovery_probe_min_success_rate: float = 1.0
    psi5_route_lookback_hours: int = 24
    psi5_route_max_actions: int = 50
    psi5_route_execution_mode: str = "execute"
    psi5_route_approve_high_risk: bool = False
    psi5_route_approved_by: str | None = None
    psi5_route_owner: str = "platform-ops"
    psi5_route_include_recovered: bool = True
    omega5_route_lookback_hours: int = 24
    omega5_route_max_controls: int = 50
    omega5_route_execution_mode: str = "review_only"
    omega5_route_auto_approve: bool = False
    omega5_route_approved_by: str | None = None
    omega5_route_requested_by: str = "omega5"
    omega5_route_approval_sla_hours: int = 4
    omega5_route_notify_wecom: bool = True
    omega5_route_allow_wecom_external: bool = False
    omega5_route_create_rollback: bool = True
    alpha6_route_lookback_hours: int = 24
    alpha6_route_approval_sla_hours: int = 4
    alpha6_route_max_pending_controls: int = 50
    alpha6_route_max_failed_execution_rate: float = 0.1
    alpha6_route_max_blocked_receipt_rate: float = 0.8
    alpha6_route_max_stale_minutes: int = 90
    alpha6_route_requested_by: str = "alpha6"
    alpha6_route_environment: str = "local"
    alpha6_route_control_schedule_code: str = "omega5_route_incident_control_15m"
    beta6_route_lookback_hours: int = 24
    beta6_route_max_controls: int = 100
    beta6_route_approval_decision: str = "hold"
    beta6_route_apply_decisions: bool = False
    beta6_route_requested_by: str = "beta6"
    beta6_route_environment: str = "local"
    beta6_route_notification_policy: str = "dedupe_digest"
    beta6_route_stress_scope: str = "full_market"
    beta6_route_notify_wecom: bool = False
    beta6_route_allow_wecom_external: bool = False
    epsilon6_sla_automation: bool = True
    epsilon6_hash_verify: bool = True
    epsilon6_recovery_drill: str = "hash_chain_verify"
    epsilon6_requested_by: str = "epsilon6"
    epsilon6_environment: str = "local"
    epsilon6_sla_limit: int = 100
    epsilon6_audit_verify_limit: int = 1000
    zeta6_environment: str = "local"
    zeta6_release_version: str = "zeta6-local"
    zeta6_requested_by: str = "zeta6"
    zeta6_require_dual_secret: bool = False
    zeta6_export_audit: bool = True
    zeta6_export_chain_scope: str | None = None
    zeta6_export_control_code: str | None = None
    zeta6_export_limit: int = 1000
    eta6_source_code: str = "vendor_http"
    eta6_primary_source_code: str = "csv"
    eta6_dataset_codes: tuple[str, ...] = ()
    eta6_environment: str = "local"
    eta6_closure_scope: str = "production_primary"
    eta6_closure_mode: str = "review_only"
    eta6_requested_by: str = "eta6"
    eta6_require_real_vendor_env: bool = True
    eta6_external_probe_allowed: bool = False
    eta6_min_stability_score: float = 70.0
    eta6_allow_cost_watch: bool = False


@dataclass(frozen=True)
class LambdaTaskResult:
    task_name: str
    status: str
    processed_count: int
    success_count: int = 0
    failed_count: int = 0
    warning_count: int = 0
    details: dict[str, Any] | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class LambdaWorkerResult:
    run_code: str
    status: str
    worker_run_id: int | None
    task_results: list[LambdaTaskResult]
    processed_count: int
    success_count: int
    failed_count: int
    warning_count: int
    duration_ms: int
    dry_run: bool


TaskHandler = Callable[[LambdaWorkerContext], LambdaTaskResult]


def run_lambda_worker(
    postgres_dsn: str | None,
    *,
    task_names: list[str] | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    dry_run: bool = False,
    trigger_mode: str = "manual",
    channel_code: str | None = None,
    alert_limit: int = 50,
    schedule_code: str | None = None,
    include_manual_schedules: bool = False,
    cost_per_request: float = 1.0,
    cost_per_1000_rows: float = 0.1,
    free_source_lookback_hours: int = 72,
    free_source_max_actions: int = 50,
    free_source_min_retry_score: float = 75.0,
    free_source_write_alerts: bool = True,
    mu5_max_actions: int = 20,
    mu5_start_date: str = "2024-01-04",
    mu5_end_date: str = "2024-01-04",
    mu5_execute_retry_canary: bool = True,
    mu5_request_manual_review: bool = True,
    mu5_notify_wecom: bool = True,
    mu5_allow_wecom_external: bool = False,
    mu5_baostock_timeout_seconds: float = 3.0,
    nu5_lookback_hours: int = 24,
    nu5_approval_sla_hours: int = 4,
    nu5_max_backlog_actions: int = 50,
    nu5_max_failure_rate: float = 0.5,
    nu5_max_stale_minutes: int = 90,
    xi5_lookback_days: int = 30,
    xi5_min_validator_score: float = 55.0,
    xi5_min_backup_score: float = 75.0,
    xi5_min_primary_score: float = 90.0,
    xi5_min_coverage_rate: float = 0.95,
    xi5_max_conflict_rate_bps: float = 5.0,
    omicron5_min_sla_uptime_pct: float = 99.5,
    omicron5_min_rate_limit_per_min: int = 60,
    omicron5_require_live_evidence: bool = False,
    pi5_promotion_scope: str = "full_market",
    pi5_require_full_market: bool = True,
    pi5_require_signoff: bool = True,
    pi5_apply_routing: bool = False,
    pi5_target_priority: int = 0,
    rho5_monitor_scope: str = "post_promotion",
    rho5_require_applied_promotion: bool = True,
    rho5_apply_rollback: bool = False,
    rho5_shadow_window_hours: int = 24,
    rho5_max_conflict_rate_bps: float = 5.0,
    rho5_max_failure_rate: float = 0.01,
    rho5_max_stale_minutes: int = 90,
    sigma5_monitor_scope: str = "primary_source",
    sigma5_lookback_hours: int = 24,
    sigma5_capacity_window_days: int = 7,
    sigma5_min_success_rate: float = 0.995,
    sigma5_max_error_rate: float = 0.005,
    sigma5_max_latency_p95_ms: float = 2000.0,
    sigma5_max_timeout_rate: float = 0.01,
    sigma5_max_cost_units: float = 500.0,
    sigma5_max_scheduler_lag_minutes: int = 90,
    sigma5_max_backlog_count: int = 50,
    sigma5_max_post_promotion_no_applied_count: int = 0,
    tau5_optimization_scope: str = "primary_source",
    tau5_lookback_hours: int = 24,
    tau5_forecast_window_days: int = 30,
    tau5_monthly_budget_amount: float = 10000.0,
    tau5_max_budget_usage_pct: float = 0.85,
    tau5_max_daily_quota_usage_pct: float = 0.85,
    tau5_max_monthly_quota_usage_pct: float = 0.85,
    tau5_min_stability_score: float = 70.0,
    tau5_cost_safety_margin_pct: float = 0.15,
    tau5_default_unit_cost: float = 0.01,
    tau5_stress_multipliers: tuple[float, ...] = (1.0, 5.0, 10.0),
    upsilon5_execution_scope: str = "primary_source",
    upsilon5_execution_mode: str = "review_only",
    upsilon5_approval_policy: str = "manual_required",
    upsilon5_approval_status: str = "pending",
    upsilon5_rollout_policy: str = "gradual",
    upsilon5_rollout_stages: tuple[float, ...] = (10.0, 30.0, 60.0, 90.0),
    upsilon5_current_stage_sequence: int = 1,
    upsilon5_max_initial_primary_weight_pct: float = 10.0,
    upsilon5_allow_over_budget: bool = False,
    upsilon5_allow_quota_risk: bool = False,
    upsilon5_rollback_requested: bool = False,
    chi5_lookback_hours: int = 24,
    chi5_min_request_count: int = 1,
    chi5_min_success_rate: float = 0.95,
    chi5_max_failure_rate: float = 0.10,
    chi5_max_fallback_rate: float = 0.20,
    chi5_max_empty_rate: float = 0.20,
    chi5_max_latency_p95_ms: float = 2000.0,
    chi5_circuit_open_minutes: int = 30,
    chi5_recovery_probe_min_success_rate: float = 1.0,
    psi5_route_lookback_hours: int = 24,
    psi5_route_max_actions: int = 50,
    psi5_route_execution_mode: str = "execute",
    psi5_route_approve_high_risk: bool = False,
    psi5_route_approved_by: str | None = None,
    psi5_route_owner: str = "platform-ops",
    psi5_route_include_recovered: bool = True,
    omega5_route_lookback_hours: int = 24,
    omega5_route_max_controls: int = 50,
    omega5_route_execution_mode: str = "review_only",
    omega5_route_auto_approve: bool = False,
    omega5_route_approved_by: str | None = None,
    omega5_route_requested_by: str = "omega5",
    omega5_route_approval_sla_hours: int = 4,
    omega5_route_notify_wecom: bool = True,
    omega5_route_allow_wecom_external: bool = False,
    omega5_route_create_rollback: bool = True,
    alpha6_route_lookback_hours: int = 24,
    alpha6_route_approval_sla_hours: int = 4,
    alpha6_route_max_pending_controls: int = 50,
    alpha6_route_max_failed_execution_rate: float = 0.1,
    alpha6_route_max_blocked_receipt_rate: float = 0.8,
    alpha6_route_max_stale_minutes: int = 90,
    alpha6_route_requested_by: str = "alpha6",
    alpha6_route_environment: str = "local",
    alpha6_route_control_schedule_code: str = "omega5_route_incident_control_15m",
    beta6_route_lookback_hours: int = 24,
    beta6_route_max_controls: int = 100,
    beta6_route_approval_decision: str = "hold",
    beta6_route_apply_decisions: bool = False,
    beta6_route_requested_by: str = "beta6",
    beta6_route_environment: str = "local",
    beta6_route_notification_policy: str = "dedupe_digest",
    beta6_route_stress_scope: str = "full_market",
    beta6_route_notify_wecom: bool = False,
    beta6_route_allow_wecom_external: bool = False,
    epsilon6_sla_automation: bool = True,
    epsilon6_hash_verify: bool = True,
    epsilon6_recovery_drill: str = "hash_chain_verify",
    epsilon6_requested_by: str = "epsilon6",
    epsilon6_environment: str = "local",
    epsilon6_sla_limit: int = 100,
    epsilon6_audit_verify_limit: int = 1000,
    zeta6_environment: str = "local",
    zeta6_release_version: str = "zeta6-local",
    zeta6_requested_by: str = "zeta6",
    zeta6_require_dual_secret: bool = False,
    zeta6_export_audit: bool = True,
    zeta6_export_chain_scope: str | None = None,
    zeta6_export_control_code: str | None = None,
    zeta6_export_limit: int = 1000,
    eta6_source_code: str = "vendor_http",
    eta6_primary_source_code: str = "csv",
    eta6_dataset_codes: tuple[str, ...] = (),
    eta6_environment: str = "local",
    eta6_closure_scope: str = "production_primary",
    eta6_closure_mode: str = "review_only",
    eta6_requested_by: str = "eta6",
    eta6_require_real_vendor_env: bool = True,
    eta6_external_probe_allowed: bool = False,
    eta6_min_stability_score: float = 70.0,
    eta6_allow_cost_watch: bool = False,
    write_db: bool = True,
    task_handlers: dict[str, TaskHandler] | None = None,
) -> LambdaWorkerResult:
    tasks = normalize_task_names(task_names)
    if trigger_mode not in {"manual", "scheduled", "once", "smoke"}:
        raise QDataValidationError("trigger_mode must be one of: manual, scheduled, once, smoke")
    if alert_limit <= 0:
        raise QDataValidationError("alert_limit must be greater than 0")
    start, end = _date_window(trade_date, start_date, end_date)
    context = LambdaWorkerContext(
        postgres_dsn=postgres_dsn,
        start_date=start,
        end_date=end,
        dry_run=dry_run,
        trigger_mode=trigger_mode,
        channel_code=channel_code,
        alert_limit=alert_limit,
        schedule_code=schedule_code,
        include_manual_schedules=include_manual_schedules,
        cost_per_request=cost_per_request,
        cost_per_1000_rows=cost_per_1000_rows,
        free_source_lookback_hours=free_source_lookback_hours,
        free_source_max_actions=free_source_max_actions,
        free_source_min_retry_score=free_source_min_retry_score,
        free_source_write_alerts=free_source_write_alerts,
        mu5_max_actions=mu5_max_actions,
        mu5_start_date=mu5_start_date,
        mu5_end_date=mu5_end_date,
        mu5_execute_retry_canary=mu5_execute_retry_canary,
        mu5_request_manual_review=mu5_request_manual_review,
        mu5_notify_wecom=mu5_notify_wecom,
        mu5_allow_wecom_external=mu5_allow_wecom_external,
        mu5_baostock_timeout_seconds=mu5_baostock_timeout_seconds,
        nu5_lookback_hours=nu5_lookback_hours,
        nu5_approval_sla_hours=nu5_approval_sla_hours,
        nu5_max_backlog_actions=nu5_max_backlog_actions,
        nu5_max_failure_rate=nu5_max_failure_rate,
        nu5_max_stale_minutes=nu5_max_stale_minutes,
        xi5_lookback_days=xi5_lookback_days,
        xi5_min_validator_score=xi5_min_validator_score,
        xi5_min_backup_score=xi5_min_backup_score,
        xi5_min_primary_score=xi5_min_primary_score,
        xi5_min_coverage_rate=xi5_min_coverage_rate,
        xi5_max_conflict_rate_bps=xi5_max_conflict_rate_bps,
        omicron5_min_sla_uptime_pct=omicron5_min_sla_uptime_pct,
        omicron5_min_rate_limit_per_min=omicron5_min_rate_limit_per_min,
        omicron5_require_live_evidence=omicron5_require_live_evidence,
        pi5_promotion_scope=pi5_promotion_scope,
        pi5_require_full_market=pi5_require_full_market,
        pi5_require_signoff=pi5_require_signoff,
        pi5_apply_routing=pi5_apply_routing,
        pi5_target_priority=pi5_target_priority,
        rho5_monitor_scope=rho5_monitor_scope,
        rho5_require_applied_promotion=rho5_require_applied_promotion,
        rho5_apply_rollback=rho5_apply_rollback,
        rho5_shadow_window_hours=rho5_shadow_window_hours,
        rho5_max_conflict_rate_bps=rho5_max_conflict_rate_bps,
        rho5_max_failure_rate=rho5_max_failure_rate,
        rho5_max_stale_minutes=rho5_max_stale_minutes,
        sigma5_monitor_scope=sigma5_monitor_scope,
        sigma5_lookback_hours=sigma5_lookback_hours,
        sigma5_capacity_window_days=sigma5_capacity_window_days,
        sigma5_min_success_rate=sigma5_min_success_rate,
        sigma5_max_error_rate=sigma5_max_error_rate,
        sigma5_max_latency_p95_ms=sigma5_max_latency_p95_ms,
        sigma5_max_timeout_rate=sigma5_max_timeout_rate,
        sigma5_max_cost_units=sigma5_max_cost_units,
        sigma5_max_scheduler_lag_minutes=sigma5_max_scheduler_lag_minutes,
        sigma5_max_backlog_count=sigma5_max_backlog_count,
        sigma5_max_post_promotion_no_applied_count=sigma5_max_post_promotion_no_applied_count,
        tau5_optimization_scope=tau5_optimization_scope,
        tau5_lookback_hours=tau5_lookback_hours,
        tau5_forecast_window_days=tau5_forecast_window_days,
        tau5_monthly_budget_amount=tau5_monthly_budget_amount,
        tau5_max_budget_usage_pct=tau5_max_budget_usage_pct,
        tau5_max_daily_quota_usage_pct=tau5_max_daily_quota_usage_pct,
        tau5_max_monthly_quota_usage_pct=tau5_max_monthly_quota_usage_pct,
        tau5_min_stability_score=tau5_min_stability_score,
        tau5_cost_safety_margin_pct=tau5_cost_safety_margin_pct,
        tau5_default_unit_cost=tau5_default_unit_cost,
        tau5_stress_multipliers=tau5_stress_multipliers,
        upsilon5_execution_scope=upsilon5_execution_scope,
        upsilon5_execution_mode=upsilon5_execution_mode,
        upsilon5_approval_policy=upsilon5_approval_policy,
        upsilon5_approval_status=upsilon5_approval_status,
        upsilon5_rollout_policy=upsilon5_rollout_policy,
        upsilon5_rollout_stages=upsilon5_rollout_stages,
        upsilon5_current_stage_sequence=upsilon5_current_stage_sequence,
        upsilon5_max_initial_primary_weight_pct=upsilon5_max_initial_primary_weight_pct,
        upsilon5_allow_over_budget=upsilon5_allow_over_budget,
        upsilon5_allow_quota_risk=upsilon5_allow_quota_risk,
        upsilon5_rollback_requested=upsilon5_rollback_requested,
        chi5_lookback_hours=chi5_lookback_hours,
        chi5_min_request_count=chi5_min_request_count,
        chi5_min_success_rate=chi5_min_success_rate,
        chi5_max_failure_rate=chi5_max_failure_rate,
        chi5_max_fallback_rate=chi5_max_fallback_rate,
        chi5_max_empty_rate=chi5_max_empty_rate,
        chi5_max_latency_p95_ms=chi5_max_latency_p95_ms,
        chi5_circuit_open_minutes=chi5_circuit_open_minutes,
        chi5_recovery_probe_min_success_rate=chi5_recovery_probe_min_success_rate,
        psi5_route_lookback_hours=psi5_route_lookback_hours,
        psi5_route_max_actions=psi5_route_max_actions,
        psi5_route_execution_mode=psi5_route_execution_mode,
        psi5_route_approve_high_risk=psi5_route_approve_high_risk,
        psi5_route_approved_by=psi5_route_approved_by,
        psi5_route_owner=psi5_route_owner,
        psi5_route_include_recovered=psi5_route_include_recovered,
        omega5_route_lookback_hours=omega5_route_lookback_hours,
        omega5_route_max_controls=omega5_route_max_controls,
        omega5_route_execution_mode=omega5_route_execution_mode,
        omega5_route_auto_approve=omega5_route_auto_approve,
        omega5_route_approved_by=omega5_route_approved_by,
        omega5_route_requested_by=omega5_route_requested_by,
        omega5_route_approval_sla_hours=omega5_route_approval_sla_hours,
        omega5_route_notify_wecom=omega5_route_notify_wecom,
        omega5_route_allow_wecom_external=omega5_route_allow_wecom_external,
        omega5_route_create_rollback=omega5_route_create_rollback,
        alpha6_route_lookback_hours=alpha6_route_lookback_hours,
        alpha6_route_approval_sla_hours=alpha6_route_approval_sla_hours,
        alpha6_route_max_pending_controls=alpha6_route_max_pending_controls,
        alpha6_route_max_failed_execution_rate=alpha6_route_max_failed_execution_rate,
        alpha6_route_max_blocked_receipt_rate=alpha6_route_max_blocked_receipt_rate,
        alpha6_route_max_stale_minutes=alpha6_route_max_stale_minutes,
        alpha6_route_requested_by=alpha6_route_requested_by,
        alpha6_route_environment=alpha6_route_environment,
        alpha6_route_control_schedule_code=alpha6_route_control_schedule_code,
        beta6_route_lookback_hours=beta6_route_lookback_hours,
        beta6_route_max_controls=beta6_route_max_controls,
        beta6_route_approval_decision=beta6_route_approval_decision,
        beta6_route_apply_decisions=beta6_route_apply_decisions,
        beta6_route_requested_by=beta6_route_requested_by,
        beta6_route_environment=beta6_route_environment,
        beta6_route_notification_policy=beta6_route_notification_policy,
        beta6_route_stress_scope=beta6_route_stress_scope,
        beta6_route_notify_wecom=beta6_route_notify_wecom,
        beta6_route_allow_wecom_external=beta6_route_allow_wecom_external,
        epsilon6_sla_automation=epsilon6_sla_automation,
        epsilon6_hash_verify=epsilon6_hash_verify,
        epsilon6_recovery_drill=epsilon6_recovery_drill,
        epsilon6_requested_by=epsilon6_requested_by,
        epsilon6_environment=epsilon6_environment,
        epsilon6_sla_limit=epsilon6_sla_limit,
        epsilon6_audit_verify_limit=epsilon6_audit_verify_limit,
        zeta6_environment=zeta6_environment,
        zeta6_release_version=zeta6_release_version,
        zeta6_requested_by=zeta6_requested_by,
        zeta6_require_dual_secret=zeta6_require_dual_secret,
        zeta6_export_audit=zeta6_export_audit,
        zeta6_export_chain_scope=zeta6_export_chain_scope,
        zeta6_export_control_code=zeta6_export_control_code,
        zeta6_export_limit=zeta6_export_limit,
        eta6_source_code=eta6_source_code,
        eta6_primary_source_code=eta6_primary_source_code,
        eta6_dataset_codes=tuple(eta6_dataset_codes or ()),
        eta6_environment=eta6_environment,
        eta6_closure_scope=eta6_closure_scope,
        eta6_closure_mode=eta6_closure_mode,
        eta6_requested_by=eta6_requested_by,
        eta6_require_real_vendor_env=eta6_require_real_vendor_env,
        eta6_external_probe_allowed=eta6_external_probe_allowed,
        eta6_min_stability_score=eta6_min_stability_score,
        eta6_allow_cost_watch=eta6_allow_cost_watch,
    )
    handlers = task_handlers or _default_task_handlers()
    run_code = _run_code()
    started_at = datetime.now(timezone.utc)
    worker_run_id = _insert_worker_run(postgres_dsn, run_code, trigger_mode, tasks, dry_run, start, end) if write_db else None
    task_results: list[LambdaTaskResult] = []
    run_error: str | None = None
    for task_name in tasks:
        task_run_id = _insert_worker_task_run(postgres_dsn, worker_run_id, task_name) if write_db and worker_run_id is not None else None
        task_started = datetime.now(timezone.utc)
        try:
            result = handlers[task_name](context)
        except Exception as exc:
            result = LambdaTaskResult(task_name, "failed", 0, failed_count=1, error_message=str(exc), details={})
        task_results.append(result)
        if result.status == "failed" and not run_error:
            run_error = result.error_message
        if write_db and task_run_id is not None:
            _finish_worker_task_run(postgres_dsn, task_run_id, result, _duration_ms(task_started))
    finished_at = datetime.now(timezone.utc)
    duration_ms = _duration_ms(started_at, finished_at)
    status = _overall_status(task_results)
    processed_count = sum(item.processed_count for item in task_results)
    success_count = sum(item.success_count for item in task_results)
    failed_count = sum(item.failed_count for item in task_results)
    warning_count = sum(item.warning_count for item in task_results)
    if write_db and worker_run_id is not None:
        _finish_worker_run(
            postgres_dsn,
            worker_run_id,
            status,
            processed_count,
            success_count,
            failed_count,
            warning_count,
            duration_ms,
            {"window": {"start_date": start, "end_date": end}, "tasks": [_task_result_dict(item) for item in task_results]},
            run_error,
        )
    return LambdaWorkerResult(
        run_code=run_code,
        status=status,
        worker_run_id=worker_run_id,
        task_results=task_results,
        processed_count=processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        duration_ms=duration_ms,
        dry_run=dry_run,
    )


def normalize_task_names(task_names: list[str] | None) -> list[str]:
    if not task_names:
        return list(WORKER_TASKS)
    normalized: list[str] = []
    seen: set[str] = set()
    for task_name in task_names:
        if task_name not in WORKER_TASKS:
            raise QDataValidationError(f"unknown worker task: {task_name}")
        if task_name in seen:
            continue
        seen.add(task_name)
        normalized.append(task_name)
    return normalized


def format_worker_report(result: LambdaWorkerResult) -> str:
    lines = [
        (
            f"lambda_worker run_code={result.run_code} status={result.status} dry_run={result.dry_run} "
            f"tasks={len(result.task_results)} processed={result.processed_count} success={result.success_count} "
            f"warning={result.warning_count} failed={result.failed_count} duration_ms={result.duration_ms}"
        )
    ]
    for item in result.task_results:
        lines.append(
            f"task name={item.task_name} status={item.status} processed={item.processed_count} "
            f"success={item.success_count} warning={item.warning_count} failed={item.failed_count}"
        )
        if item.error_message:
            lines.append(f"task_error name={item.task_name} message={item.error_message}")
    return "\n".join(lines)


def _default_task_handlers() -> dict[str, TaskHandler]:
    return {
        "usage_rollup": _run_usage_rollup_task,
        "alert_dispatch": _run_alert_dispatch_task,
        "vendor_benchmark_schedule": _run_vendor_schedule_task,
        "free_source_recovery": _run_free_source_recovery_task,
        "free_source_recovery_execute": _run_free_source_recovery_execute_task,
        "free_source_recovery_health": _run_free_source_recovery_health_task,
        "free_source_admission_review": _run_free_source_admission_review_task,
        "vendor_contract_readiness_review": _run_vendor_contract_readiness_review_task,
        "vendor_primary_promotion_review": _run_vendor_primary_promotion_review_task,
        "vendor_post_promotion_monitor": _run_vendor_post_promotion_monitor_task,
        "vendor_primary_stability_monitor": _run_vendor_primary_stability_monitor_task,
        "vendor_cost_optimizer": _run_vendor_cost_optimizer_task,
        "vendor_route_weight_executor": _run_vendor_route_weight_executor_task,
        "vendor_production_source_closure": _run_vendor_production_source_closure_task,
        "source_route_feedback_monitor": _run_source_route_feedback_monitor_task,
        "route_incident_automation": _run_route_incident_automation_task,
        "route_incident_control": _run_route_incident_control_task,
        "route_incident_control_health": _run_route_incident_control_health_task,
        "route_incident_operations": _run_route_incident_operations_task,
        "route_incident_approval_resilience": _run_route_incident_approval_resilience_task,
        "route_incident_approval_release": _run_route_incident_approval_release_task,
    }


def _run_usage_rollup_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    if context.dry_run:
        rows = _preview_api_usage_rollup(context)
        return LambdaTaskResult("usage_rollup", "skipped", len(rows), warning_count=len(rows), details={"preview_rows": rows})
    rows = rollup_api_usage_daily(
        _require_dsn(context),
        context.start_date,
        context.end_date,
        cost_per_request=context.cost_per_request,
        cost_per_1000_rows=context.cost_per_1000_rows,
    )
    status = "success" if rows else "skipped"
    return LambdaTaskResult("usage_rollup", status, len(rows), success_count=len(rows), details={"rows": rows})


def _run_alert_dispatch_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    if context.dry_run:
        rows = _preview_alert_dispatch(context)
        return LambdaTaskResult("alert_dispatch", "skipped", len(rows), warning_count=len(rows), details={"preview_deliveries": rows})
    deliveries = dispatch_alert_notifications(
        _require_dsn(context),
        channel_code=context.channel_code,
        limit=context.alert_limit,
        dry_run=False,
    )
    failed_count = sum(1 for item in deliveries if item["status"] == "failed")
    skipped_count = sum(1 for item in deliveries if item["status"] == "skipped")
    sent_count = sum(1 for item in deliveries if item["status"] == "sent")
    status = "failed" if failed_count else "warning" if skipped_count else "success" if deliveries else "skipped"
    return LambdaTaskResult(
        "alert_dispatch",
        status,
        len(deliveries),
        success_count=sent_count,
        failed_count=failed_count,
        warning_count=skipped_count,
        details={"deliveries": deliveries},
    )


def _run_vendor_schedule_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    schedules = _fetch_due_vendor_schedules(context)
    if context.dry_run:
        return LambdaTaskResult("vendor_benchmark_schedule", "skipped", len(schedules), warning_count=len(schedules), details={"schedules": schedules})
    if not schedules:
        return LambdaTaskResult("vendor_benchmark_schedule", "skipped", 0, details={"schedules": []})
    results: list[dict[str, Any]] = []
    failed_count = 0
    warning_count = 0
    success_count = 0
    for schedule in schedules:
        try:
            result = run_vendor_benchmark_schedule(_require_dsn(context), schedule["schedule_code"])
            results.append(result)
            if result.get("status") == "warning":
                warning_count += 1
            else:
                success_count += 1
        except Exception as exc:
            failed_count += 1
            results.append({"schedule_code": schedule["schedule_code"], "status": "failed", "error_message": str(exc)})
    status = "failed" if failed_count else "warning" if warning_count else "success"
    return LambdaTaskResult(
        "vendor_benchmark_schedule",
        status,
        len(schedules),
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={"schedules": schedules, "results": results},
    )


def _run_free_source_recovery_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_free_source_recovery(
        _require_dsn(context),
        as_of_date=context.end_date,
        lookback_hours=context.free_source_lookback_hours,
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        dry_run=context.dry_run,
        max_actions=context.free_source_max_actions,
        min_retry_score=context.free_source_min_retry_score,
        write_alerts=context.free_source_write_alerts,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("action_count") or 0)
    failed_count = 1 if result.get("status") == "failed" else 0
    warning_count = max(
        int(result.get("manual_review_action_count") or 0),
        int(result.get("alert_action_count") or 0),
        int(result.get("blocked_action_count") or 0),
    )
    success_count = max(0, processed_count - warning_count - failed_count)
    if context.dry_run:
        return LambdaTaskResult("free_source_recovery", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    return LambdaTaskResult(
        "free_source_recovery",
        str(result.get("status") or "skipped"),
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={"recovery": result},
    )


def _run_free_source_recovery_execute_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = execute_free_source_recovery_actions(
        _require_dsn(context),
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        dry_run=context.dry_run,
        max_actions=context.mu5_max_actions,
        start_date=context.mu5_start_date,
        end_date=context.mu5_end_date,
        execute_retry_canary=context.mu5_execute_retry_canary,
        request_manual_review=context.mu5_request_manual_review,
        notify_wecom=context.mu5_notify_wecom,
        allow_wecom_external=context.mu5_allow_wecom_external,
        baostock_timeout_seconds=context.mu5_baostock_timeout_seconds,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("execution_count") or 0)
    failed_count = int(result.get("failed_count") or 0)
    warning_count = int(result.get("review_requested_count") or 0) + int(result.get("suppressed_count") or 0) + int(result.get("blocked_count") or 0)
    success_count = int(result.get("recovered_count") or 0) + int(result.get("notified_count") or 0)
    if context.dry_run:
        return LambdaTaskResult("free_source_recovery_execute", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    return LambdaTaskResult(
        "free_source_recovery_execute",
        str(result.get("status") or "skipped"),
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={"mu5": result},
    )


def _run_free_source_recovery_health_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_free_source_recovery_health(
        _require_dsn(context),
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        lookback_hours=context.nu5_lookback_hours,
        approval_sla_hours=context.nu5_approval_sla_hours,
        max_backlog_actions=context.nu5_max_backlog_actions,
        max_failure_rate=context.nu5_max_failure_rate,
        max_stale_minutes=context.nu5_max_stale_minutes,
        write_db=not context.dry_run,
    )
    if context.dry_run:
        return LambdaTaskResult("free_source_recovery_health", "skipped", 1, warning_count=1, details={"preview": result})
    health_status = str(result.get("status") or "skipped")
    task_status = _worker_status_from_health(health_status)
    failed_count = 1 if task_status == "failed" else 0
    warning_count = 1 if task_status == "warning" else 0
    success_count = 1 if task_status == "success" else 0
    return LambdaTaskResult(
        "free_source_recovery_health",
        task_status,
        1,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={"nu5": result},
        error_message="Nu-5 recovery health is critical" if task_status == "failed" else None,
    )


def _run_free_source_admission_review_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    rows = run_free_source_admission_review(
        _require_dsn(context),
        as_of_date=context.end_date,
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        lookback_days=context.xi5_lookback_days,
        min_validator_score=context.xi5_min_validator_score,
        min_backup_score=context.xi5_min_backup_score,
        min_primary_score=context.xi5_min_primary_score,
        min_coverage_rate=context.xi5_min_coverage_rate,
        max_conflict_rate_bps=context.xi5_max_conflict_rate_bps,
        write_db=not context.dry_run,
    )
    processed_count = len(rows)
    warning_count = sum(1 for row in rows if row.get("status") in {"review_required", "blocked", "no_data"})
    success_count = sum(1 for row in rows if row.get("status") in {"approved", "conditional"})
    status = "warning" if warning_count else "success" if success_count else "skipped"
    if context.dry_run:
        return LambdaTaskResult("free_source_admission_review", "skipped", processed_count, warning_count=processed_count, details={"preview": rows})
    return LambdaTaskResult(
        "free_source_admission_review",
        status,
        processed_count,
        success_count=success_count,
        warning_count=warning_count,
        details={
            "xi5": {
                "snapshot_count": processed_count,
                "approved_count": sum(1 for row in rows if row.get("status") == "approved"),
                "conditional_count": sum(1 for row in rows if row.get("status") == "conditional"),
                "review_required_count": sum(1 for row in rows if row.get("status") == "review_required"),
                "blocked_count": sum(1 for row in rows if row.get("status") == "blocked"),
                "no_data_count": sum(1 for row in rows if row.get("status") == "no_data"),
            }
        },
    )


def _run_vendor_contract_readiness_review_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    rows = run_vendor_contract_readiness_review(
        _require_dsn(context),
        as_of_date=context.end_date,
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        min_sla_uptime_pct=context.omicron5_min_sla_uptime_pct,
        min_rate_limit_per_min=context.omicron5_min_rate_limit_per_min,
        require_live_evidence=context.omicron5_require_live_evidence,
        write_db=not context.dry_run,
    )
    processed_count = len(rows)
    ready_count = sum(1 for row in rows if row.get("status") == "ready")
    conditional_count = sum(1 for row in rows if row.get("status") == "conditional")
    review_required_count = sum(1 for row in rows if row.get("status") == "review_required")
    blocked_count = sum(1 for row in rows if row.get("status") == "blocked")
    no_contract_count = sum(1 for row in rows if row.get("status") == "no_contract")
    warning_count = conditional_count + review_required_count + blocked_count + no_contract_count
    status = "warning" if warning_count else "success" if ready_count else "skipped"
    if context.dry_run:
        return LambdaTaskResult("vendor_contract_readiness_review", "skipped", processed_count, warning_count=processed_count, details={"preview": rows})
    return LambdaTaskResult(
        "vendor_contract_readiness_review",
        status,
        processed_count,
        success_count=ready_count,
        warning_count=warning_count,
        details={
            "omicron5": {
                "snapshot_count": processed_count,
                "ready_count": ready_count,
                "conditional_count": conditional_count,
                "review_required_count": review_required_count,
                "blocked_count": blocked_count,
                "no_contract_count": no_contract_count,
                "primary_candidate_count": sum(1 for row in rows if row.get("procurement_role") == "primary_candidate"),
            }
        },
    )


def _run_vendor_primary_promotion_review_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_vendor_primary_promotion_review(
        _require_dsn(context),
        as_of_date=context.end_date,
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        promotion_scope=context.pi5_promotion_scope,
        require_full_market=context.pi5_require_full_market,
        require_signoff=context.pi5_require_signoff,
        apply_routing=context.pi5_apply_routing,
        target_priority=context.pi5_target_priority,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("dataset_count") or len(result.get("results") or []))
    approved_count = int(result.get("approved_dataset_count") or 0)
    applied_count = int(result.get("applied_dataset_count") or 0)
    blocked_count = int(result.get("blocked_dataset_count") or 0)
    pending_count = int(result.get("pending_dataset_count") or 0)
    warning_count = blocked_count + pending_count
    success_count = approved_count + applied_count
    status = "warning" if warning_count else "success" if success_count else "skipped"
    if context.dry_run:
        return LambdaTaskResult("vendor_primary_promotion_review", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    return LambdaTaskResult(
        "vendor_primary_promotion_review",
        status,
        processed_count,
        success_count=success_count,
        warning_count=warning_count,
        details={
            "pi5": {
                "promotion_code": result.get("promotion_code"),
                "status": result.get("status"),
                "promotion_scope": result.get("promotion_scope"),
                "apply_mode": result.get("apply_mode"),
                "routing_change_allowed": result.get("routing_change_allowed"),
                "routing_change_applied": result.get("routing_change_applied"),
                "dataset_count": processed_count,
                "approved_dataset_count": approved_count,
                "applied_dataset_count": applied_count,
                "pending_dataset_count": pending_count,
                "blocked_dataset_count": blocked_count,
            }
        },
    )


def _run_vendor_post_promotion_monitor_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_post_promotion_monitor(
        _require_dsn(context),
        as_of_date=context.end_date,
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        monitor_scope=context.rho5_monitor_scope,
        require_applied_promotion=context.rho5_require_applied_promotion,
        apply_rollback=context.rho5_apply_rollback,
        shadow_window_hours=context.rho5_shadow_window_hours,
        max_conflict_rate_bps=context.rho5_max_conflict_rate_bps,
        max_failure_rate=context.rho5_max_failure_rate,
        max_stale_minutes=context.rho5_max_stale_minutes,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("dataset_count") or len(result.get("results") or []))
    healthy_count = int(result.get("healthy_dataset_count") or 0)
    warning_dataset_count = int(result.get("warning_dataset_count") or 0)
    rollback_recommended_count = int(result.get("rollback_recommended_count") or 0)
    rolled_back_count = int(result.get("rolled_back_dataset_count") or 0)
    blocked_count = int(result.get("blocked_dataset_count") or 0)
    no_applied_count = int(result.get("no_applied_dataset_count") or 0)
    warning_count = warning_dataset_count + rollback_recommended_count + blocked_count + no_applied_count
    success_count = healthy_count + rolled_back_count
    status = "warning" if warning_count else "success" if success_count else "skipped"
    if context.dry_run:
        return LambdaTaskResult("vendor_post_promotion_monitor", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    return LambdaTaskResult(
        "vendor_post_promotion_monitor",
        status,
        processed_count,
        success_count=success_count,
        warning_count=warning_count,
        details={
            "rho5": {
                "monitor_code": result.get("monitor_code"),
                "status": result.get("status"),
                "monitor_scope": result.get("monitor_scope"),
                "rollback_mode": result.get("rollback_mode"),
                "rollback_allowed": result.get("rollback_allowed"),
                "rollback_applied": result.get("rollback_applied"),
                "dataset_count": processed_count,
                "healthy_dataset_count": healthy_count,
                "warning_dataset_count": warning_dataset_count,
                "rollback_recommended_count": rollback_recommended_count,
                "rolled_back_dataset_count": rolled_back_count,
                "blocked_dataset_count": blocked_count,
                "no_applied_dataset_count": no_applied_count,
            }
        },
    )


def _run_vendor_primary_stability_monitor_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_vendor_primary_stability_monitor(
        _require_dsn(context),
        as_of_date=context.end_date,
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        monitor_scope=context.sigma5_monitor_scope,
        lookback_hours=context.sigma5_lookback_hours,
        capacity_window_days=context.sigma5_capacity_window_days,
        min_success_rate=context.sigma5_min_success_rate,
        max_error_rate=context.sigma5_max_error_rate,
        max_latency_p95_ms=context.sigma5_max_latency_p95_ms,
        max_timeout_rate=context.sigma5_max_timeout_rate,
        max_cost_units=context.sigma5_max_cost_units,
        max_scheduler_lag_minutes=context.sigma5_max_scheduler_lag_minutes,
        max_backlog_count=context.sigma5_max_backlog_count,
        max_post_promotion_no_applied_count=context.sigma5_max_post_promotion_no_applied_count,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("dataset_count") or len(result.get("results") or []))
    healthy_count = int(result.get("healthy_dataset_count") or 0)
    warning_count = int(result.get("warning_dataset_count") or 0)
    critical_count = int(result.get("critical_dataset_count") or 0)
    blocked_count = int(result.get("blocked_dataset_count") or 0)
    no_primary_count = int(result.get("no_primary_dataset_count") or 0)
    success_count = healthy_count
    failed_count = 1 if result.get("status") == "critical" else 0
    task_warning_count = warning_count + blocked_count + no_primary_count
    status = "failed" if failed_count else "warning" if task_warning_count or critical_count else "success" if success_count else "skipped"
    if context.dry_run:
        return LambdaTaskResult("vendor_primary_stability_monitor", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    return LambdaTaskResult(
        "vendor_primary_stability_monitor",
        status,
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=task_warning_count,
        details={
            "sigma5": {
                "snapshot_code": result.get("snapshot_code"),
                "status": result.get("status"),
                "stability_role": result.get("stability_role"),
                "monitor_scope": result.get("monitor_scope"),
                "dataset_count": processed_count,
                "primary_dataset_count": result.get("primary_dataset_count"),
                "healthy_dataset_count": healthy_count,
                "warning_dataset_count": warning_count,
                "critical_dataset_count": critical_count,
                "blocked_dataset_count": blocked_count,
                "no_primary_dataset_count": no_primary_count,
                "api_success_rate": result.get("api_success_rate"),
                "cost_units": result.get("cost_units"),
                "scheduler_lag_minutes": result.get("scheduler_lag_minutes"),
                "backlog_count": result.get("backlog_count"),
                "stability_score": result.get("stability_score"),
            }
        },
    )


def _run_vendor_cost_optimizer_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_vendor_cost_optimizer(
        _require_dsn(context),
        as_of_date=context.end_date,
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        optimization_scope=context.tau5_optimization_scope,
        lookback_hours=context.tau5_lookback_hours,
        forecast_window_days=context.tau5_forecast_window_days,
        monthly_budget_amount=context.tau5_monthly_budget_amount,
        max_budget_usage_pct=context.tau5_max_budget_usage_pct,
        max_daily_quota_usage_pct=context.tau5_max_daily_quota_usage_pct,
        max_monthly_quota_usage_pct=context.tau5_max_monthly_quota_usage_pct,
        min_stability_score=context.tau5_min_stability_score,
        cost_safety_margin_pct=context.tau5_cost_safety_margin_pct,
        default_unit_cost=context.tau5_default_unit_cost,
        stress_multipliers=context.tau5_stress_multipliers,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("dataset_count") or len(result.get("route_plans") or []))
    optimized_count = int(result.get("optimized_dataset_count") or 0)
    watch_count = int(result.get("watch_dataset_count") or 0)
    over_budget_count = int(result.get("over_budget_dataset_count") or 0)
    quota_risk_count = int(result.get("quota_risk_dataset_count") or 0)
    blocked_count = int(result.get("blocked_dataset_count") or 0)
    no_primary_count = int(result.get("no_primary_dataset_count") or 0)
    failed_count = 1 if result.get("status") in {"blocked", "over_budget"} else 0
    warning_count = watch_count + quota_risk_count + no_primary_count
    success_count = optimized_count
    status = "failed" if failed_count else "warning" if warning_count or blocked_count or over_budget_count else "success" if success_count else "skipped"
    if context.dry_run:
        return LambdaTaskResult("vendor_cost_optimizer", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    return LambdaTaskResult(
        "vendor_cost_optimizer",
        status,
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={
            "tau5": {
                "optimization_code": result.get("optimization_code"),
                "status": result.get("status"),
                "optimization_role": result.get("optimization_role"),
                "optimization_scope": result.get("optimization_scope"),
                "dataset_count": processed_count,
                "optimized_dataset_count": optimized_count,
                "watch_dataset_count": watch_count,
                "over_budget_dataset_count": over_budget_count,
                "quota_risk_dataset_count": quota_risk_count,
                "blocked_dataset_count": blocked_count,
                "no_primary_dataset_count": no_primary_count,
                "recommended_primary_weight_pct": result.get("recommended_primary_weight_pct"),
                "recommended_backup_weight_pct": result.get("recommended_backup_weight_pct"),
                "recommended_free_source_weight_pct": result.get("recommended_free_source_weight_pct"),
                "projected_budget_usage_pct": result.get("projected_budget_usage_pct"),
                "projected_monthly_quota_usage_pct": result.get("projected_monthly_quota_usage_pct"),
                "optimization_score": result.get("optimization_score"),
            }
        },
    )


def _run_vendor_route_weight_executor_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_vendor_route_weight_execution(
        _require_dsn(context),
        as_of_date=context.end_date,
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        execution_scope=context.upsilon5_execution_scope,
        execution_mode=context.upsilon5_execution_mode,
        approval_policy=context.upsilon5_approval_policy,
        approval_status=context.upsilon5_approval_status,
        rollout_policy=context.upsilon5_rollout_policy,
        rollout_stages=context.upsilon5_rollout_stages,
        current_stage_sequence=context.upsilon5_current_stage_sequence,
        max_initial_primary_weight_pct=context.upsilon5_max_initial_primary_weight_pct,
        allow_over_budget=context.upsilon5_allow_over_budget,
        allow_quota_risk=context.upsilon5_allow_quota_risk,
        rollback_requested=context.upsilon5_rollback_requested,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("dataset_count") or len(result.get("datasets") or []))
    pending_count = int(result.get("pending_approval_dataset_count") or 0)
    approved_count = int(result.get("approved_dataset_count") or 0)
    staged_count = int(result.get("staged_dataset_count") or 0)
    applied_count = int(result.get("applied_dataset_count") or 0)
    rollback_count = int(result.get("rollback_recommended_count") or 0)
    rolled_back_count = int(result.get("rolled_back_dataset_count") or 0)
    blocked_count = int(result.get("blocked_dataset_count") or 0)
    no_primary_count = int(result.get("no_primary_dataset_count") or 0)
    failed_count = 1 if result.get("status") in {"blocked", "rollback_recommended"} else 0
    warning_count = pending_count + staged_count + rollback_count + no_primary_count
    success_count = approved_count + applied_count + rolled_back_count
    status = "failed" if failed_count else "warning" if warning_count or blocked_count else "success" if success_count else "skipped"
    if context.dry_run:
        return LambdaTaskResult("vendor_route_weight_executor", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    return LambdaTaskResult(
        "vendor_route_weight_executor",
        status,
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={
            "upsilon5": {
                "execution_code": result.get("execution_code"),
                "status": result.get("status"),
                "approval_status": result.get("approval_status"),
                "execution_scope": result.get("execution_scope"),
                "execution_mode": result.get("execution_mode"),
                "rollout_policy": result.get("rollout_policy"),
                "dataset_count": processed_count,
                "pending_approval_dataset_count": pending_count,
                "approved_dataset_count": approved_count,
                "staged_dataset_count": staged_count,
                "applied_dataset_count": applied_count,
                "rollback_recommended_count": rollback_count,
                "rolled_back_dataset_count": rolled_back_count,
                "blocked_dataset_count": blocked_count,
                "no_primary_dataset_count": no_primary_count,
                "target_primary_weight_pct": result.get("target_primary_weight_pct"),
                "applied_primary_weight_pct": result.get("applied_primary_weight_pct"),
                "current_stage_sequence": result.get("current_stage_sequence"),
                "routing_change_allowed": result.get("routing_change_allowed"),
                "routing_change_applied": result.get("routing_change_applied"),
                "rollback_allowed": result.get("rollback_allowed"),
                "rollback_applied": result.get("rollback_applied"),
            }
        },
    )


def _run_source_route_feedback_monitor_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_source_route_feedback_monitor(
        _require_dsn(context),
        requested_by="lambda_worker",
        trigger_mode=context.trigger_mode,
        environment="local",
        lookback_hours=context.chi5_lookback_hours,
        min_request_count=context.chi5_min_request_count,
        min_success_rate=context.chi5_min_success_rate,
        max_failure_rate=context.chi5_max_failure_rate,
        max_fallback_rate=context.chi5_max_fallback_rate,
        max_empty_rate=context.chi5_max_empty_rate,
        max_latency_p95_ms=context.chi5_max_latency_p95_ms,
        circuit_open_minutes=context.chi5_circuit_open_minutes,
        recovery_probe_min_success_rate=context.chi5_recovery_probe_min_success_rate,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("snapshot_count") or 0)
    critical_count = int(result.get("degraded_count") or 0) + int(result.get("circuit_open_count") or 0)
    warning_count = int(result.get("warning_count") or 0) + int(result.get("failed_probe_count") or 0)
    success_count = int(result.get("healthy_count") or 0) + int(result.get("recovered_probe_count") or 0)
    if context.dry_run:
        return LambdaTaskResult("source_route_feedback_monitor", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    status = "warning" if critical_count or warning_count else "success" if success_count else "skipped"
    return LambdaTaskResult(
        "source_route_feedback_monitor",
        status,
        processed_count,
        success_count=success_count,
        warning_count=critical_count + warning_count,
        details={
            "chi5": {
                "status": result.get("status"),
                "snapshot_count": processed_count,
                "healthy_count": result.get("healthy_count"),
                "warning_count": result.get("warning_count"),
                "degraded_count": result.get("degraded_count"),
                "circuit_open_count": result.get("circuit_open_count"),
                "recovery_probe_count": result.get("recovery_probe_count"),
                "recovered_probe_count": result.get("recovered_probe_count"),
                "failed_probe_count": result.get("failed_probe_count"),
            }
        },
    )


def _run_route_incident_automation_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    execution_mode = "dry_run" if context.dry_run else context.psi5_route_execution_mode
    result = run_psi_automation(
        _require_dsn(context),
        as_of_date=context.end_date,
        environment="local",
        trigger_mode=context.trigger_mode,
        execution_mode=execution_mode,
        approve=context.psi5_route_approve_high_risk,
        approved_by=context.psi5_route_approved_by,
        include_phi=False,
        include_chi=False,
        include_route=True,
        route_lookback_hours=context.psi5_route_lookback_hours,
        route_max_actions=context.psi5_route_max_actions,
        route_owner=context.psi5_route_owner,
        route_include_recovered=context.psi5_route_include_recovered,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("action_count") or 0)
    approval_required_count = int(result.get("approval_required_count") or 0)
    skipped_count = int(result.get("skipped_count") or 0)
    failed_count = int(result.get("failed_count") or 0)
    success_count = int(result.get("executed_count") or 0)
    if context.dry_run:
        return LambdaTaskResult("route_incident_automation", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    status = str(result.get("status") or "skipped")
    warning_count = approval_required_count + skipped_count
    return LambdaTaskResult(
        "route_incident_automation",
        status,
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={
            "psi5": {
                "run_code": result.get("run_code"),
                "status": result.get("status"),
                "execution_mode": result.get("execution_mode"),
                "action_count": processed_count,
                "executed_count": success_count,
                "approval_required_count": approval_required_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
            }
        },
    )


def _run_route_incident_control_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    execution_mode = "dry_run" if context.dry_run else context.omega5_route_execution_mode
    result = run_route_incident_control(
        _require_dsn(context),
        lookback_hours=context.omega5_route_lookback_hours,
        max_controls=context.omega5_route_max_controls,
        execution_mode=execution_mode,
        auto_approve=context.omega5_route_auto_approve,
        approved_by=context.omega5_route_approved_by,
        requested_by=context.omega5_route_requested_by,
        approval_sla_hours=context.omega5_route_approval_sla_hours,
        notify_wecom=context.omega5_route_notify_wecom,
        allow_wecom_external=context.omega5_route_allow_wecom_external,
        create_rollback=context.omega5_route_create_rollback,
        trigger_mode=context.trigger_mode,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("control_count") or 0)
    approval_requested_count = int(result.get("approval_requested_count") or 0)
    skipped_count = int(result.get("skipped_count") or 0)
    failed_count = int(result.get("failed_count") or 0)
    success_count = int(result.get("executed_count") or 0) + int(result.get("approved_count") or 0)
    if context.dry_run:
        return LambdaTaskResult("route_incident_control", "skipped", processed_count, warning_count=processed_count, details={"preview": result})
    status = str(result.get("status") or "skipped")
    return LambdaTaskResult(
        "route_incident_control",
        status,
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=approval_requested_count + skipped_count,
        details={
            "omega5": {
                "status": result.get("status"),
                "execution_mode": result.get("execution_mode"),
                "control_count": processed_count,
                "approval_requested_count": approval_requested_count,
                "approved_count": result.get("approved_count"),
                "notification_recorded_count": result.get("notification_recorded_count"),
                "executed_count": result.get("executed_count"),
                "rollback_planned_count": result.get("rollback_planned_count"),
                "skipped_count": skipped_count,
                "failed_count": failed_count,
            }
        },
    )


def _run_route_incident_control_health_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_route_incident_control_health(
        _require_dsn(context),
        requested_by=context.alpha6_route_requested_by,
        trigger_mode=context.trigger_mode,
        environment=context.alpha6_route_environment,
        lookback_hours=context.alpha6_route_lookback_hours,
        approval_sla_hours=context.alpha6_route_approval_sla_hours,
        max_pending_controls=context.alpha6_route_max_pending_controls,
        max_failed_execution_rate=context.alpha6_route_max_failed_execution_rate,
        max_blocked_receipt_rate=context.alpha6_route_max_blocked_receipt_rate,
        max_stale_minutes=context.alpha6_route_max_stale_minutes,
        schedule_code=context.alpha6_route_control_schedule_code,
        write_db=not context.dry_run,
    )
    if context.dry_run:
        return LambdaTaskResult("route_incident_control_health", "skipped", 1, warning_count=1, details={"preview": result})
    health_status = str(result.get("status") or "skipped")
    task_status = _worker_status_from_health(health_status)
    failed_count = 1 if task_status == "failed" else 0
    warning_count = 1 if task_status == "warning" else 0
    success_count = 1 if task_status == "success" else 0
    return LambdaTaskResult(
        "route_incident_control_health",
        task_status,
        1,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={"alpha6": result},
        error_message="Alpha-6 route incident control health is critical" if task_status == "failed" else None,
    )


def _run_route_incident_operations_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    result = run_route_incident_operations(
        _require_dsn(context),
        requested_by=context.beta6_route_requested_by,
        trigger_mode=context.trigger_mode,
        environment=context.beta6_route_environment,
        operation_mode="approval_queue",
        approval_decision=context.beta6_route_approval_decision,
        notification_policy=context.beta6_route_notification_policy,
        stress_scope=context.beta6_route_stress_scope,
        lookback_hours=context.beta6_route_lookback_hours,
        max_controls=context.beta6_route_max_controls,
        dry_run=context.dry_run,
        apply_decisions=context.beta6_route_apply_decisions,
        notify_wecom=context.beta6_route_notify_wecom,
        allow_wecom_external=context.beta6_route_allow_wecom_external,
        write_db=not context.dry_run,
    )
    processed_count = int(result.get("candidate_count") or 0)
    if context.dry_run:
        return LambdaTaskResult("route_incident_operations", "skipped", processed_count, warning_count=processed_count or 1, details={"preview": result})
    status = str(result.get("status") or "skipped")
    task_status = "failed" if status == "failed" else "warning" if status == "warning" else "success" if status == "success" else "skipped"
    failed_count = int(result.get("failed_count") or 0)
    warning_count = int(result.get("held_count") or 0) + int(result.get("skipped_count") or 0) + (1 if task_status == "warning" else 0)
    success_count = int(result.get("approved_count") or 0) + int(result.get("rejected_count") or 0)
    return LambdaTaskResult(
        "route_incident_operations",
        task_status,
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={"beta6": result},
        error_message=result.get("error_message") if task_status == "failed" else None,
    )


def _run_route_incident_approval_resilience_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    dsn = _require_dsn(context)
    audit_result = (
        verify_approval_audit_chain(dsn, limit=context.epsilon6_audit_verify_limit)
        if context.epsilon6_hash_verify
        else {"status": "skipped", "checked_count": 0, "broken_count": 0, "broken_entries": []}
    )
    sla_result = (
        run_approval_sla_automation(dsn, limit=context.epsilon6_sla_limit, write_db=not context.dry_run)
        if context.epsilon6_sla_automation
        else {"status": "skipped", "checked_count": 0, "timeout_escalation_count": 0, "sla_action_count": 0, "actions": []}
    )
    drill_result: dict[str, Any] | None = None
    if context.epsilon6_recovery_drill != "none":
        drill_result = run_approval_recovery_drill(
            dsn,
            drill_type=context.epsilon6_recovery_drill,
            requested_by=context.epsilon6_requested_by,
            trigger_mode="worker",
            write_db=not context.dry_run,
        )

    audit_broken_count = int(audit_result.get("broken_count") or 0)
    sla_action_count = int(sla_result.get("sla_action_count") or 0)
    timeout_escalation_count = int(sla_result.get("timeout_escalation_count") or 0)
    drill_failed_count = int((drill_result or {}).get("failed_count") or 0)
    drill_passed_count = int((drill_result or {}).get("passed_count") or 0)
    processed_count = (
        int(audit_result.get("checked_count") or 0)
        + int(sla_result.get("checked_count") or 0)
        + int((drill_result or {}).get("check_count") or 0)
    )
    failed_count = audit_broken_count + drill_failed_count
    warning_count = sla_action_count + timeout_escalation_count
    success_count = (1 if audit_result.get("status") == "success" else 0) + drill_passed_count
    if context.dry_run:
        return LambdaTaskResult(
            "route_incident_approval_resilience",
            "skipped",
            processed_count,
            warning_count=processed_count or 1,
            details={"preview": {"audit": audit_result, "sla": sla_result, "drill": drill_result}},
        )
    task_status = "failed" if failed_count else "warning" if warning_count else "success" if processed_count or success_count else "skipped"
    return LambdaTaskResult(
        "route_incident_approval_resilience",
        task_status,
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={
            "epsilon6": {
                "status": task_status,
                "environment": context.epsilon6_environment,
                "hash_verify_enabled": context.epsilon6_hash_verify,
                "sla_automation_enabled": context.epsilon6_sla_automation,
                "recovery_drill": context.epsilon6_recovery_drill,
                "audit_checked_count": audit_result.get("checked_count"),
                "audit_broken_count": audit_broken_count,
                "timeout_escalation_count": timeout_escalation_count,
                "sla_action_count": sla_action_count,
                "drill_code": (drill_result or {}).get("drill_code"),
                "drill_status": (drill_result or {}).get("status"),
                "drill_check_count": (drill_result or {}).get("check_count"),
                "drill_failed_count": drill_failed_count,
            }
        },
        error_message="Epsilon-6 approval audit chain or recovery drill failed" if failed_count else None,
    )


def _run_route_incident_approval_release_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    dsn = _require_dsn(context)
    preflight = run_release_preflight(
        dsn,
        environment=context.zeta6_environment,
        release_version=context.zeta6_release_version,
        requested_by=context.zeta6_requested_by,
        trigger_mode="worker",
        require_dual_secret=context.zeta6_require_dual_secret,
        audit_verify_limit=context.zeta6_export_limit,
        write_db=not context.dry_run,
    )
    export: dict[str, Any] | None = None
    if context.zeta6_export_audit:
        export = export_approval_audit_package(
            dsn,
            environment=context.zeta6_environment,
            chain_scope=context.zeta6_export_chain_scope,
            control_code=context.zeta6_export_control_code,
            export_format="json",
            exported_by=context.zeta6_requested_by,
            trigger_mode="worker",
            limit=context.zeta6_export_limit,
            write_db=not context.dry_run,
        )

    preflight_failed = int(preflight.get("failed_count") or 0)
    preflight_warning = int(preflight.get("warning_count") or 0)
    export_broken = int((export or {}).get("broken_hash_count") or 0)
    export_warning = 1 if export and export.get("status") == "warning" else 0
    processed_count = int(preflight.get("check_count") or 0) + (1 if export else 0)
    failed_count = preflight_failed + export_broken
    warning_count = preflight_warning + export_warning
    success_count = int(preflight.get("passed_count") or 0) + (1 if export and export.get("status") == "success" else 0)
    if context.dry_run:
        return LambdaTaskResult(
            "route_incident_approval_release",
            "skipped",
            processed_count,
            warning_count=processed_count or 1,
            details={"preview": {"preflight": preflight, "audit_export": export}},
        )
    task_status = "failed" if failed_count else "warning" if warning_count else "success" if processed_count else "skipped"
    return LambdaTaskResult(
        "route_incident_approval_release",
        task_status,
        processed_count,
        success_count=success_count,
        failed_count=failed_count,
        warning_count=warning_count,
        details={
            "zeta6": {
                "status": task_status,
                "environment": context.zeta6_environment,
                "release_version": context.zeta6_release_version,
                "preflight_code": preflight.get("preflight_code"),
                "preflight_status": preflight.get("status"),
                "preflight_failed_count": preflight_failed,
                "preflight_warning_count": preflight_warning,
                "audit_export_code": (export or {}).get("export_code"),
                "audit_export_status": (export or {}).get("status"),
                "audit_export_broken_hash_count": export_broken,
                "audit_package_hash": (export or {}).get("package_hash"),
            }
        },
        error_message="Zeta-6 release preflight or audit export failed" if failed_count else None,
    )


def _run_vendor_production_source_closure_task(context: LambdaWorkerContext) -> LambdaTaskResult:
    row = run_vendor_production_source_closure(
        _require_dsn(context),
        as_of_date=context.end_date,
        source_code=context.eta6_source_code,
        primary_source_code=context.eta6_primary_source_code,
        dataset_codes=context.eta6_dataset_codes or None,
        requested_by=context.eta6_requested_by,
        trigger_mode="worker",
        environment=context.eta6_environment,
        closure_scope=context.eta6_closure_scope,
        closure_mode=context.eta6_closure_mode,
        require_real_vendor_env=context.eta6_require_real_vendor_env,
        external_probe_allowed=context.eta6_external_probe_allowed,
        min_stability_score=context.eta6_min_stability_score,
        allow_cost_watch=context.eta6_allow_cost_watch,
        write_db=not context.dry_run,
    )
    dataset_count = int(row.get("dataset_count") or 0)
    ready_count = int(row.get("production_ready_dataset_count") or 0)
    blocked_count = int(row.get("blocked_dataset_count") or 0)
    warning_count = max(0, dataset_count - ready_count)
    if context.dry_run:
        return LambdaTaskResult(
            "vendor_production_source_closure",
            "skipped",
            dataset_count,
            warning_count=dataset_count or 1,
            details={"preview": row},
        )
    task_status = (
        "failed"
        if row.get("status") == "failed"
        else "success"
        if row.get("status") in {"production_ready", "applied", "monitoring"}
        else "warning"
        if dataset_count
        else "skipped"
    )
    return LambdaTaskResult(
        "vendor_production_source_closure",
        task_status,
        dataset_count,
        success_count=ready_count if task_status == "success" else 0,
        failed_count=1 if row.get("status") == "failed" else 0,
        warning_count=warning_count if task_status != "success" else 0,
        details={
            "eta6": {
                "status": row.get("status"),
                "production_code": row.get("production_code"),
                "production_role": row.get("production_role"),
                "source_code": context.eta6_source_code,
                "primary_source_code": context.eta6_primary_source_code,
                "dataset_count": dataset_count,
                "production_ready_dataset_count": row.get("production_ready_dataset_count"),
                "applied_dataset_count": row.get("applied_dataset_count"),
                "blocked_dataset_count": blocked_count,
                "live_base_url_present": row.get("live_base_url_present"),
                "live_token_present": row.get("live_token_present"),
                "routing_change_allowed": row.get("routing_change_allowed"),
                "production_score": row.get("production_score"),
            }
        },
        error_message="Eta-6 production source closure failed" if row.get("status") == "failed" else None,
    )


def _preview_api_usage_rollup(context: LambdaWorkerContext) -> list[dict[str, Any]]:
    with _connect_required(_require_dsn(context)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    started_at::date AS usage_date,
                    tenant_id, project_id, principal_id, token_id, api_name,
                    COUNT(*) AS request_count,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
                    COALESCE(SUM(row_count), 0) AS row_count,
                    COALESCE(SUM(duration_ms), 0) AS duration_ms,
                    COALESCE(SUM(%s + COALESCE(row_count, 0) / 1000.0 * %s), 0) AS cost_units
                FROM qmeta.api_request_audit
                WHERE started_at::date BETWEEN %s AND %s
                GROUP BY started_at::date, tenant_id, project_id, principal_id, token_id, api_name
                ORDER BY usage_date, api_name
                """,
                (context.cost_per_request, context.cost_per_1000_rows, context.start_date, context.end_date),
            )
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _preview_alert_dispatch(context: LambdaWorkerContext) -> list[dict[str, Any]]:
    with _connect_required(_require_dsn(context)) as connection:
        with connection.cursor() as cursor:
            channel_where = ["is_active = TRUE"]
            params: list[Any] = []
            if context.channel_code:
                channel_where.append("channel_code = %s")
                params.append(context.channel_code)
            cursor.execute(
                f"""
                SELECT channel_id, channel_code, min_severity
                FROM qmeta.notification_channel
                WHERE {' AND '.join(channel_where)}
                ORDER BY channel_code
                """,
                tuple(params),
            )
            channels = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT alert_id, alert_type, severity, trade_date, message, last_seen_at
                FROM qmeta.alert_event
                WHERE status = 'open'
                ORDER BY last_seen_at DESC, alert_id DESC
                LIMIT %s
                """,
                (context.alert_limit,),
            )
            alerts = [dict(row) for row in cursor.fetchall()]
    deliveries: list[dict[str, Any]] = []
    for alert in alerts:
        for channel in channels:
            if SEVERITY_ORDER.get(alert["severity"], 0) < SEVERITY_ORDER.get(channel["min_severity"], 0):
                continue
            deliveries.append(
                {
                    "alert_id": alert["alert_id"],
                    "alert_type": alert["alert_type"],
                    "severity": alert["severity"],
                    "channel_code": channel["channel_code"],
                    "status": "preview",
                }
            )
    return normalize_rows(deliveries)


def _fetch_due_vendor_schedules(context: LambdaWorkerContext) -> list[dict[str, Any]]:
    where = ["status = 'active'"]
    params: list[Any] = []
    if context.schedule_code:
        where.append("schedule_code = %s")
        params.append(context.schedule_code)
    elif context.include_manual_schedules:
        where.append("(next_run_at IS NULL OR next_run_at <= now())")
    else:
        where.append("cadence <> 'manual'")
        where.append("next_run_at IS NOT NULL")
        where.append("next_run_at <= now()")
    with _connect_required(_require_dsn(context)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT schedule_id, schedule_code, cadence, next_run_at
                FROM qmeta.vendor_benchmark_schedule
                WHERE {' AND '.join(where)}
                ORDER BY next_run_at NULLS LAST, schedule_code
                """,
                tuple(params),
            )
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _insert_worker_run(
    postgres_dsn: str | None,
    run_code: str,
    trigger_mode: str,
    tasks: list[str],
    dry_run: bool,
    start_date: str,
    end_date: str,
) -> int:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.worker_run (run_code, trigger_mode, task_filter, dry_run, details)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                RETURNING worker_run_id
                """,
                (run_code, trigger_mode, tasks, dry_run, _json({"window": {"start_date": start_date, "end_date": end_date}})),
            )
            return int(cursor.fetchone()["worker_run_id"])


def _insert_worker_task_run(postgres_dsn: str | None, worker_run_id: int, task_name: str) -> int:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.worker_task_run (worker_run_id, task_name)
                VALUES (%s, %s)
                RETURNING task_run_id
                """,
                (worker_run_id, task_name),
            )
            return int(cursor.fetchone()["task_run_id"])


def _finish_worker_task_run(postgres_dsn: str | None, task_run_id: int, result: LambdaTaskResult, duration_ms: int) -> None:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.worker_task_run
                SET status = %s,
                    finished_at = now(),
                    duration_ms = %s,
                    processed_count = %s,
                    success_count = %s,
                    failed_count = %s,
                    warning_count = %s,
                    details = %s::jsonb,
                    error_message = %s,
                    updated_at = now()
                WHERE task_run_id = %s
                """,
                (
                    result.status,
                    duration_ms,
                    result.processed_count,
                    result.success_count,
                    result.failed_count,
                    result.warning_count,
                    _json(result.details or {}),
                    result.error_message,
                    task_run_id,
                ),
            )


def _finish_worker_run(
    postgres_dsn: str | None,
    worker_run_id: int,
    status: str,
    processed_count: int,
    success_count: int,
    failed_count: int,
    warning_count: int,
    duration_ms: int,
    details: dict[str, Any],
    error_message: str | None,
) -> None:
    with _connect_required(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qmeta.worker_run
                SET status = %s,
                    finished_at = now(),
                    duration_ms = %s,
                    processed_count = %s,
                    success_count = %s,
                    failed_count = %s,
                    warning_count = %s,
                    details = %s::jsonb,
                    error_message = %s,
                    updated_at = now()
                WHERE worker_run_id = %s
                """,
                (
                    status,
                    duration_ms,
                    processed_count,
                    success_count,
                    failed_count,
                    warning_count,
                    _json(details),
                    error_message,
                    worker_run_id,
                ),
            )


def _overall_status(results: list[LambdaTaskResult]) -> str:
    if any(item.status == "failed" for item in results):
        return "failed"
    if any(item.status == "warning" for item in results):
        return "warning"
    if any(item.status == "success" for item in results):
        return "success"
    return "skipped"


def _worker_status_from_health(status: str) -> str:
    if status in {"failed", "critical"}:
        return "failed"
    if status == "warning":
        return "warning"
    if status == "healthy":
        return "success"
    return "skipped"


def _date_window(trade_date: str | None, start_date: str | None, end_date: str | None) -> tuple[str, str]:
    if trade_date:
        date_range(trade_date, trade_date)
        return trade_date, trade_date
    if start_date and end_date:
        date_range(start_date, end_date)
        return start_date, end_date
    today = date.today().isoformat()
    return today, today


def _duration_ms(started_at: datetime, finished_at: datetime | None = None) -> int:
    finished_at = finished_at or datetime.now(timezone.utc)
    return int((finished_at - started_at).total_seconds() * 1000)


def _task_result_dict(result: LambdaTaskResult) -> dict[str, Any]:
    return {
        "task_name": result.task_name,
        "status": result.status,
        "processed_count": result.processed_count,
        "success_count": result.success_count,
        "failed_count": result.failed_count,
        "warning_count": result.warning_count,
        "details": result.details or {},
        "error_message": result.error_message,
    }


def _run_code() -> str:
    return f"lambda-worker-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _require_dsn(context: LambdaWorkerContext) -> str:
    if not context.postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Lambda worker tasks")
    return context.postgres_dsn


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def _connect_required(postgres_dsn: str | None):
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Lambda worker persistence")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Lambda worker persistence") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
