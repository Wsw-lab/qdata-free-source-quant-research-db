from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.iota import ensure_iota_security_context


PRODUCT_TYPES = {"dataset_bundle", "api_bundle", "export", "package"}
PRODUCT_STATUSES = {"active", "testing", "paused", "retired"}
BILLING_UNITS = {"request", "row", "cost_unit", "export", "month"}
PLAN_CYCLES = {"daily", "monthly", "annual", "prepaid", "usage"}
PRICING_METRICS = {"request", "row", "cost_unit", "export", "monthly_fee"}
BUDGET_PERIODS = {"daily", "monthly"}
BUDGET_STATUSES = {"normal", "warning", "exceeded", "blocked"}


@dataclass(frozen=True)
class BudgetEvaluation:
    budget_id: int
    budget_code: str
    budget_name: str
    period_start: date
    period_end: date
    usage_amount: Decimal
    budget_amount: Decimal
    usage_pct: Decimal
    request_count: int
    row_count: int
    cost_units: Decimal
    status: str
    currency: str
    alert_type: str | None = None
    severity: str | None = None
    threshold_pct: Decimal | None = None
    message: str | None = None
    snapshot_id: int | None = None
    snapshot_code: str | None = None


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    status: str
    budget_code: str | None = None
    usage_amount: Decimal | None = None
    budget_amount: Decimal | None = None
    usage_pct: Decimal | None = None
    reason: str | None = None


def period_window(period: str, as_of_date: str | date) -> tuple[date, date]:
    if period not in BUDGET_PERIODS:
        raise QDataValidationError("period must be one of: daily, monthly")
    current = parse_date(as_of_date, "as_of_date") if isinstance(as_of_date, str) else as_of_date
    if period == "daily":
        return current, current
    last_day = monthrange(current.year, current.month)[1]
    return date(current.year, current.month, 1), date(current.year, current.month, last_day)


def budget_status(
    usage_amount: Decimal | int | float | str,
    budget_amount: Decimal | int | float | str,
    soft_threshold_pct: Decimal | int | float | str,
    hard_threshold_pct: Decimal | int | float | str,
    *,
    hard_limit_enabled: bool,
) -> tuple[str, Decimal]:
    usage = _decimal(usage_amount)
    budget = _decimal(budget_amount)
    if budget <= 0:
        raise QDataValidationError("budget_amount must be positive")
    usage_pct = usage / budget
    soft = _decimal(soft_threshold_pct)
    hard = _decimal(hard_threshold_pct)
    if usage_pct >= hard:
        return ("blocked" if hard_limit_enabled else "exceeded"), usage_pct
    if usage_pct >= soft:
        return "warning", usage_pct
    return "normal", usage_pct


def priced_usage_amount(
    usage_rows: list[dict[str, Any]],
    pricing_rules: list[dict[str, Any]],
    *,
    base_fee: Decimal | int | float | str = Decimal("0"),
) -> tuple[Decimal, dict[str, Any]]:
    amount = _decimal(base_fee)
    request_count = 0
    row_count = 0
    cost_units = Decimal("0")
    line_count = 0
    for row in usage_rows:
        api_name = row.get("api_name")
        request_count += int(row.get("request_count") or 0)
        row_count += int(row.get("row_count") or 0)
        cost_units += _decimal(row.get("cost_units") or 0)
        matching = _matching_rules(pricing_rules, api_name)
        if not matching:
            amount += _decimal(row.get("cost_units") or 0)
            line_count += 1
            continue
        for rule in matching:
            quantity = _metric_quantity(rule["metric_name"], row)
            billable = max(quantity - _decimal(rule.get("free_quantity") or 0), Decimal("0"))
            amount += billable * _decimal(rule.get("unit_price") or 0)
            line_count += 1
    return amount, {
        "request_count": request_count,
        "row_count": row_count,
        "cost_units": cost_units,
        "pricing_line_count": line_count,
        "base_fee": _decimal(base_fee),
    }


def ensure_data_product(
    postgres_dsn: str,
    *,
    product_code: str,
    product_name: str,
    product_type: str = "dataset_bundle",
    dataset_codes: list[str] | None = None,
    api_names: list[str] | None = None,
    billing_unit: str = "cost_unit",
    status: str = "active",
    update_frequency: str | None = None,
    sla_level: str | None = None,
    license_scope: str | None = None,
    owner: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_enum(product_type, PRODUCT_TYPES, "product_type")
    _validate_enum(status, PRODUCT_STATUSES, "status")
    _validate_enum(billing_unit, BILLING_UNITS, "billing_unit")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.data_product (
                    product_code, product_name, product_type, billing_unit, status,
                    update_frequency, sla_level, license_scope, owner, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (product_code) DO UPDATE SET
                    product_name = EXCLUDED.product_name,
                    product_type = EXCLUDED.product_type,
                    billing_unit = EXCLUDED.billing_unit,
                    status = EXCLUDED.status,
                    update_frequency = EXCLUDED.update_frequency,
                    sla_level = EXCLUDED.sla_level,
                    license_scope = EXCLUDED.license_scope,
                    owner = EXCLUDED.owner,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING product_id, product_code, product_name, status, billing_unit
                """,
                (
                    product_code,
                    product_name,
                    product_type,
                    billing_unit,
                    status,
                    update_frequency,
                    sla_level,
                    license_scope,
                    owner,
                    _json(details or {}),
                ),
            )
            product = dict(cursor.fetchone())
            dataset_count = 0
            for dataset_code in dataset_codes or []:
                dataset_id = _ensure_dataset(cursor, dataset_code)
                _upsert_product_dataset(cursor, product["product_id"], dataset_id)
                dataset_count += 1
            api_count = 0
            for api_name in api_names or []:
                _upsert_product_api(cursor, product["product_id"], _api_name(api_name))
                api_count += 1
    product.update({"dataset_count": dataset_count, "api_count": api_count})
    return product


def ensure_pricing_plan(
    postgres_dsn: str,
    *,
    plan_code: str,
    plan_name: str,
    billing_cycle: str = "monthly",
    currency: str = "CNY",
    base_fee: Decimal | int | float | str = Decimal("0"),
    included_cost_units: Decimal | int | float | str = Decimal("0"),
    included_requests: int = 0,
    status: str = "active",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_enum(billing_cycle, PLAN_CYCLES, "billing_cycle")
    _validate_enum(status, PRODUCT_STATUSES, "status")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.pricing_plan (
                    plan_code, plan_name, billing_cycle, currency, base_fee,
                    included_cost_units, included_requests, status, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (plan_code) DO UPDATE SET
                    plan_name = EXCLUDED.plan_name,
                    billing_cycle = EXCLUDED.billing_cycle,
                    currency = EXCLUDED.currency,
                    base_fee = EXCLUDED.base_fee,
                    included_cost_units = EXCLUDED.included_cost_units,
                    included_requests = EXCLUDED.included_requests,
                    status = EXCLUDED.status,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING plan_id, plan_code, plan_name, billing_cycle, currency, base_fee, status
                """,
                (
                    plan_code,
                    plan_name,
                    billing_cycle,
                    currency,
                    _decimal(base_fee),
                    _decimal(included_cost_units),
                    included_requests,
                    status,
                    _json(details or {}),
                ),
            )
            return dict(cursor.fetchone())


def ensure_pricing_rule(
    postgres_dsn: str,
    *,
    plan_code: str,
    rule_code: str,
    metric_name: str = "cost_unit",
    unit_price: Decimal | int | float | str = Decimal("0"),
    product_code: str | None = None,
    api_name: str | None = None,
    free_quantity: Decimal | int | float | str = Decimal("0"),
    tier_start: Decimal | int | float | str = Decimal("0"),
    tier_end: Decimal | int | float | str | None = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
    status: str = "active",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_enum(metric_name, PRICING_METRICS, "metric_name")
    _validate_enum(status, PRODUCT_STATUSES, "status")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            plan_id = _lookup_id(cursor, "pricing_plan", "plan_id", "plan_code", plan_code)
            product_id = _lookup_id(cursor, "data_product", "product_id", "product_code", product_code) if product_code else None
            cursor.execute(
                """
                INSERT INTO qmeta.pricing_rule (
                    plan_id, product_id, rule_code, metric_name, api_name, unit_price,
                    free_quantity, tier_start, tier_end, effective_from, effective_to, status, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, CURRENT_DATE), %s, %s, %s::jsonb)
                ON CONFLICT (rule_code) DO UPDATE SET
                    plan_id = EXCLUDED.plan_id,
                    product_id = EXCLUDED.product_id,
                    metric_name = EXCLUDED.metric_name,
                    api_name = EXCLUDED.api_name,
                    unit_price = EXCLUDED.unit_price,
                    free_quantity = EXCLUDED.free_quantity,
                    tier_start = EXCLUDED.tier_start,
                    tier_end = EXCLUDED.tier_end,
                    effective_from = EXCLUDED.effective_from,
                    effective_to = EXCLUDED.effective_to,
                    status = EXCLUDED.status,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING rule_id, rule_code, metric_name, api_name, unit_price, status
                """,
                (
                    plan_id,
                    product_id,
                    rule_code,
                    metric_name,
                    _api_name(api_name) if api_name else None,
                    _decimal(unit_price),
                    _decimal(free_quantity),
                    _decimal(tier_start),
                    _decimal(tier_end) if tier_end is not None else None,
                    effective_from,
                    effective_to,
                    status,
                    _json(details or {}),
                ),
            )
            return dict(cursor.fetchone())


def ensure_product_subscription(
    postgres_dsn: str,
    *,
    subscription_code: str,
    tenant_code: str,
    project_code: str | None,
    plan_code: str,
    product_code: str,
    starts_on: str | None = None,
    ends_on: str | None = None,
    status: str = "active",
    auto_renew: bool = True,
    hard_limit_enabled: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in {"active", "paused", "cancelled", "expired"}:
        raise QDataValidationError("subscription status must be one of: active, paused, cancelled, expired")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            tenant_id = _lookup_id(cursor, "tenant", "tenant_id", "tenant_code", tenant_code)
            project_id = _lookup_project_id(cursor, tenant_id, project_code) if project_code else None
            plan_id = _lookup_id(cursor, "pricing_plan", "plan_id", "plan_code", plan_code)
            product_id = _lookup_id(cursor, "data_product", "product_id", "product_code", product_code)
            cursor.execute(
                """
                INSERT INTO qmeta.product_subscription (
                    subscription_code, tenant_id, project_id, plan_id, product_id,
                    starts_on, ends_on, status, auto_renew, hard_limit_enabled, details
                ) VALUES (%s, %s, %s, %s, %s, COALESCE(%s, CURRENT_DATE), %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (subscription_code) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    project_id = EXCLUDED.project_id,
                    plan_id = EXCLUDED.plan_id,
                    product_id = EXCLUDED.product_id,
                    starts_on = EXCLUDED.starts_on,
                    ends_on = EXCLUDED.ends_on,
                    status = EXCLUDED.status,
                    auto_renew = EXCLUDED.auto_renew,
                    hard_limit_enabled = EXCLUDED.hard_limit_enabled,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING subscription_id, subscription_code, status, starts_on, ends_on
                """,
                (
                    subscription_code,
                    tenant_id,
                    project_id,
                    plan_id,
                    product_id,
                    starts_on,
                    ends_on,
                    status,
                    auto_renew,
                    hard_limit_enabled,
                    _json(details or {}),
                ),
            )
            return dict(cursor.fetchone())


def ensure_budget_policy(
    postgres_dsn: str,
    *,
    budget_code: str,
    budget_name: str,
    budget_amount: Decimal | int | float | str,
    tenant_code: str | None = None,
    project_code: str | None = None,
    principal_code: str | None = None,
    cost_center: str | None = None,
    plan_code: str | None = None,
    product_code: str | None = None,
    period: str = "monthly",
    currency: str = "CNY",
    soft_threshold_pct: Decimal | int | float | str = Decimal("0.7"),
    hard_threshold_pct: Decimal | int | float | str = Decimal("1.0"),
    hard_limit_enabled: bool = False,
    status: str = "active",
    starts_on: str | None = None,
    ends_on: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_enum(period, BUDGET_PERIODS, "period")
    _validate_enum(status, {"active", "paused", "retired"}, "status")
    if not any([tenant_code, project_code, principal_code, cost_center]):
        raise QDataValidationError("budget scope requires tenant, project, principal or cost_center")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            tenant_id = _lookup_id(cursor, "tenant", "tenant_id", "tenant_code", tenant_code) if tenant_code else None
            project_id = _lookup_project_id(cursor, tenant_id, project_code) if project_code else None
            principal_id = _lookup_principal_id(cursor, tenant_id, principal_code) if principal_code else None
            plan_id = _lookup_id(cursor, "pricing_plan", "plan_id", "plan_code", plan_code) if plan_code else None
            product_id = _lookup_id(cursor, "data_product", "product_id", "product_code", product_code) if product_code else None
            cursor.execute(
                """
                INSERT INTO qmeta.budget_policy (
                    budget_code, budget_name, tenant_id, project_id, principal_id, cost_center,
                    plan_id, product_id, period, budget_amount, currency,
                    soft_threshold_pct, hard_threshold_pct, hard_limit_enabled,
                    status, starts_on, ends_on, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, CURRENT_DATE), %s, %s::jsonb)
                ON CONFLICT (budget_code) DO UPDATE SET
                    budget_name = EXCLUDED.budget_name,
                    tenant_id = EXCLUDED.tenant_id,
                    project_id = EXCLUDED.project_id,
                    principal_id = EXCLUDED.principal_id,
                    cost_center = EXCLUDED.cost_center,
                    plan_id = EXCLUDED.plan_id,
                    product_id = EXCLUDED.product_id,
                    period = EXCLUDED.period,
                    budget_amount = EXCLUDED.budget_amount,
                    currency = EXCLUDED.currency,
                    soft_threshold_pct = EXCLUDED.soft_threshold_pct,
                    hard_threshold_pct = EXCLUDED.hard_threshold_pct,
                    hard_limit_enabled = EXCLUDED.hard_limit_enabled,
                    status = EXCLUDED.status,
                    starts_on = EXCLUDED.starts_on,
                    ends_on = EXCLUDED.ends_on,
                    details = EXCLUDED.details,
                    updated_at = now()
                RETURNING budget_id, budget_code, budget_name, period, budget_amount, currency, status
                """,
                (
                    budget_code,
                    budget_name,
                    tenant_id,
                    project_id,
                    principal_id,
                    cost_center,
                    plan_id,
                    product_id,
                    period,
                    _decimal(budget_amount),
                    currency,
                    _decimal(soft_threshold_pct),
                    _decimal(hard_threshold_pct),
                    hard_limit_enabled,
                    status,
                    starts_on,
                    ends_on,
                    _json(details or {}),
                ),
            )
            return dict(cursor.fetchone())


def bootstrap_xi_commercial_catalog(
    postgres_dsn: str,
    *,
    tenant_code: str = "demo",
    tenant_name: str = "Demo Tenant",
    project_code: str = "quant-research",
    project_name: str = "Quant Research",
    principal_code: str = "research-bot",
    principal_name: str = "Research Bot",
    token: str = "iotatoken",
    token_name: str = "Iota Demo Token",
    cost_center: str = "research",
    budget_amount: Decimal | int | float | str = Decimal("0.15"),
    hard_limit_enabled: bool = False,
) -> dict[str, Any]:
    context = ensure_iota_security_context(
        postgres_dsn,
        tenant_code=tenant_code,
        tenant_name=tenant_name,
        project_code=project_code,
        project_name=project_name,
        principal_code=principal_code,
        principal_name=principal_name,
        token=token,
        token_name=token_name,
        datasets=["daily_bar", "adjustment_factor", "limit_price_daily", "tradable_universe"],
        scopes=["read", "admin"],
        cost_center=cost_center,
    )
    product = ensure_data_product(
        postgres_dsn,
        product_code="a_share_daily_core",
        product_name="A Share Daily Quant Core",
        product_type="dataset_bundle",
        dataset_codes=["daily_bar", "adjustment_factor", "limit_price_daily", "tradable_universe"],
        api_names=["price", "matrix", "constraints", "tradable-universe"],
        billing_unit="cost_unit",
        update_frequency="T+0/T+1 mixed",
        sla_level="local-dev",
        license_scope="internal quant research; vendor redistribution depends on source contract",
        owner="qdata-xi",
    )
    plan = ensure_pricing_plan(
        postgres_dsn,
        plan_code="quant_starter_monthly",
        plan_name="Quant Starter Monthly",
        billing_cycle="monthly",
        currency="CNY",
        base_fee=0,
        included_cost_units=0,
        included_requests=0,
    )
    rule = ensure_pricing_rule(
        postgres_dsn,
        plan_code="quant_starter_monthly",
        product_code="a_share_daily_core",
        rule_code="quant_starter_core_cost_unit",
        metric_name="cost_unit",
        unit_price="0.01",
        details={"formula": "api_usage_daily.cost_units * 0.01"},
    )
    subscription = ensure_product_subscription(
        postgres_dsn,
        subscription_code=f"{tenant_code}_{project_code}_a_share_daily_core",
        tenant_code=tenant_code,
        project_code=project_code,
        plan_code="quant_starter_monthly",
        product_code="a_share_daily_core",
        hard_limit_enabled=hard_limit_enabled,
    )
    budget = ensure_budget_policy(
        postgres_dsn,
        budget_code=f"{tenant_code}_{project_code}_monthly_budget",
        budget_name=f"{project_name} Monthly Budget",
        tenant_code=tenant_code,
        project_code=project_code,
        cost_center=cost_center,
        plan_code="quant_starter_monthly",
        product_code="a_share_daily_core",
        period="monthly",
        budget_amount=budget_amount,
        soft_threshold_pct="0.7",
        hard_threshold_pct="1.0",
        hard_limit_enabled=hard_limit_enabled,
        details={"created_by": "bootstrap_xi_commercial"},
    )
    return {
        "context": context,
        "product": product,
        "plan": plan,
        "rule": rule,
        "subscription": subscription,
        "budget": budget,
    }


def evaluate_budget_policies(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    budget_code: str | None = None,
    write_db: bool = False,
    write_alerts: bool = False,
) -> list[dict[str, Any]]:
    current = _coerce_date(as_of_date) if as_of_date else date.today()
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            budgets = _fetch_budget_policies(cursor, current, budget_code)
            evaluations: list[BudgetEvaluation] = []
            for budget in budgets:
                evaluation = _evaluate_budget(cursor, budget, current)
                if write_db:
                    evaluation = _write_budget_snapshot(cursor, evaluation, budget)
                    if write_alerts:
                        _write_budget_alert(cursor, evaluation, budget)
                evaluations.append(evaluation)
    return [budget_evaluation_to_dict(evaluation) for evaluation in evaluations]


def budget_evaluation_to_dict(evaluation: BudgetEvaluation) -> dict[str, Any]:
    return {
        "budget_id": evaluation.budget_id,
        "budget_code": evaluation.budget_code,
        "budget_name": evaluation.budget_name,
        "period_start": evaluation.period_start.isoformat(),
        "period_end": evaluation.period_end.isoformat(),
        "usage_amount": str(evaluation.usage_amount),
        "budget_amount": str(evaluation.budget_amount),
        "usage_pct": str(evaluation.usage_pct),
        "request_count": evaluation.request_count,
        "row_count": evaluation.row_count,
        "cost_units": str(evaluation.cost_units),
        "status": evaluation.status,
        "currency": evaluation.currency,
        "alert_type": evaluation.alert_type,
        "severity": evaluation.severity,
        "threshold_pct": str(evaluation.threshold_pct) if evaluation.threshold_pct is not None else None,
        "message": evaluation.message,
        "snapshot_id": evaluation.snapshot_id,
        "snapshot_code": evaluation.snapshot_code,
    }


def format_budget_evaluations(rows: list[dict[str, Any]]) -> str:
    lines = [f"xi_budget_evaluation rows={len(rows)}"]
    for row in rows:
        lines.append(
            f"budget={row['budget_code']} status={row['status']} usage={row['usage_amount']}/{row['budget_amount']} "
            f"usage_pct={row['usage_pct']} requests={row['request_count']} alert={row.get('alert_type') or 'none'}"
        )
    return "\n".join(lines)


def check_budget_allowed(
    postgres_dsn: str | None,
    *,
    identity: Any,
    api_name: str,
    as_of_date: str | date | None = None,
) -> BudgetDecision:
    if not postgres_dsn:
        return BudgetDecision(True, "not_configured")
    if not any([getattr(identity, "tenant_id", None), getattr(identity, "project_id", None), getattr(identity, "principal_id", None), getattr(identity, "cost_center", None)]):
        return BudgetDecision(True, "no_budget_scope")
    current = _coerce_date(as_of_date) if as_of_date else date.today()
    try:
        with _connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                budgets = _fetch_budget_policies_for_identity(cursor, identity, current, _api_name(api_name))
                for budget in budgets:
                    if not budget.get("hard_limit_enabled"):
                        continue
                    evaluation = _evaluate_budget(cursor, budget, current)
                    projected = evaluation.usage_amount + _estimate_next_request_amount(cursor, budget, _api_name(api_name), current)
                    projected_status, projected_pct = budget_status(
                        projected,
                        evaluation.budget_amount,
                        budget["soft_threshold_pct"],
                        budget["hard_threshold_pct"],
                        hard_limit_enabled=True,
                    )
                    if projected_status == "blocked":
                        return BudgetDecision(
                            False,
                            projected_status,
                            budget_code=budget["budget_code"],
                            usage_amount=projected,
                            budget_amount=evaluation.budget_amount,
                            usage_pct=projected_pct,
                            reason=f"budget hard limit exceeded: {budget['budget_code']}",
                        )
    except Exception:
        return BudgetDecision(True, "check_unavailable")
    return BudgetDecision(True, "allowed")


def _evaluate_budget(cursor, budget: dict[str, Any], as_of_date: date) -> BudgetEvaluation:
    period_start, period_end = period_window(budget["period"], as_of_date)
    usage_rows = _fetch_budget_usage_rows(cursor, budget, period_start, min(period_end, as_of_date))
    pricing_rules = _fetch_pricing_rules(cursor, budget.get("plan_id"), budget.get("product_id"), as_of_date)
    base_fee = _fetch_plan_base_fee(cursor, budget.get("plan_id"))
    usage_amount, usage_details = priced_usage_amount(usage_rows, pricing_rules, base_fee=base_fee)
    status, usage_pct = budget_status(
        usage_amount,
        budget["budget_amount"],
        budget["soft_threshold_pct"],
        budget["hard_threshold_pct"],
        hard_limit_enabled=bool(budget["hard_limit_enabled"]),
    )
    alert_type, severity, threshold_pct = _alert_for_budget_status(status, budget)
    message = None
    if alert_type:
        message = (
            f"Budget {budget['budget_code']} is {status}: "
            f"{usage_amount:.6f}/{_decimal(budget['budget_amount']):.6f} {budget['currency']}"
        )
    return BudgetEvaluation(
        budget_id=int(budget["budget_id"]),
        budget_code=budget["budget_code"],
        budget_name=budget["budget_name"],
        period_start=period_start,
        period_end=period_end,
        usage_amount=usage_amount,
        budget_amount=_decimal(budget["budget_amount"]),
        usage_pct=usage_pct,
        request_count=int(usage_details["request_count"]),
        row_count=int(usage_details["row_count"]),
        cost_units=_decimal(usage_details["cost_units"]),
        status=status,
        currency=budget["currency"],
        alert_type=alert_type,
        severity=severity,
        threshold_pct=threshold_pct,
        message=message,
        snapshot_code=_snapshot_code(budget["budget_code"], period_start, period_end),
    )


def _write_budget_snapshot(cursor, evaluation: BudgetEvaluation, budget: dict[str, Any]) -> BudgetEvaluation:
    details = {
        "source": "xi_budget_evaluation",
        "plan_code": budget.get("plan_code"),
        "product_code": budget.get("product_code"),
        "tenant_code": budget.get("tenant_code"),
        "project_code": budget.get("project_code"),
        "cost_center": budget.get("cost_center"),
    }
    cursor.execute(
        """
        INSERT INTO qmeta.budget_usage_snapshot (
            snapshot_code, budget_id, period_start, period_end, usage_amount,
            budget_amount, usage_pct, request_count, row_count, cost_units, status, details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (budget_id, period_start, period_end) DO UPDATE SET
            snapshot_code = EXCLUDED.snapshot_code,
            usage_amount = EXCLUDED.usage_amount,
            budget_amount = EXCLUDED.budget_amount,
            usage_pct = EXCLUDED.usage_pct,
            request_count = EXCLUDED.request_count,
            row_count = EXCLUDED.row_count,
            cost_units = EXCLUDED.cost_units,
            status = EXCLUDED.status,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING snapshot_id
        """,
        (
            evaluation.snapshot_code,
            evaluation.budget_id,
            evaluation.period_start,
            evaluation.period_end,
            evaluation.usage_amount,
            evaluation.budget_amount,
            evaluation.usage_pct,
            evaluation.request_count,
            evaluation.row_count,
            evaluation.cost_units,
            evaluation.status,
            _json(details),
        ),
    )
    snapshot_id = int(cursor.fetchone()["snapshot_id"])
    return BudgetEvaluation(**{**evaluation.__dict__, "snapshot_id": snapshot_id})


def _write_budget_alert(cursor, evaluation: BudgetEvaluation, budget: dict[str, Any]) -> None:
    if not evaluation.alert_type:
        cursor.execute(
            """
            UPDATE qmeta.budget_alert
            SET status = 'resolved', resolved_at = now(), updated_at = now()
            WHERE budget_id = %s
              AND status = 'open'
              AND details->>'period_start' = %s
              AND details->>'period_end' = %s
            """,
            (evaluation.budget_id, evaluation.period_start.isoformat(), evaluation.period_end.isoformat()),
        )
        cursor.execute(
            """
            UPDATE qmeta.alert_event
            SET status = 'resolved',
                resolved_at = now(),
                updated_at = now()
            WHERE status = 'open'
              AND alert_type IN ('budget_threshold_warning', 'budget_exceeded', 'budget_blocked', 'budget_usage_spike')
              AND details->>'budget_code' = %s
              AND details->>'period_start' = %s
              AND details->>'period_end' = %s
            """,
            (evaluation.budget_code, evaluation.period_start.isoformat(), evaluation.period_end.isoformat()),
        )
        return
    alert_key = f"xi-budget:{evaluation.budget_code}:{evaluation.period_start}:{evaluation.period_end}:{evaluation.alert_type}"
    details = {
        "source": "xi_budget_evaluation",
        "period_start": evaluation.period_start.isoformat(),
        "period_end": evaluation.period_end.isoformat(),
        "budget_code": evaluation.budget_code,
        "snapshot_code": evaluation.snapshot_code,
    }
    cursor.execute(
        """
        UPDATE qmeta.budget_alert
        SET status = 'resolved',
            resolved_at = now(),
            updated_at = now()
        WHERE budget_id = %s
          AND status = 'open'
          AND alert_type <> %s
          AND details->>'period_start' = %s
          AND details->>'period_end' = %s
        """,
        (evaluation.budget_id, evaluation.alert_type, evaluation.period_start.isoformat(), evaluation.period_end.isoformat()),
    )
    cursor.execute(
        """
        UPDATE qmeta.alert_event
        SET status = 'resolved',
            resolved_at = now(),
            updated_at = now()
        WHERE status = 'open'
          AND alert_type IN ('budget_threshold_warning', 'budget_exceeded', 'budget_blocked', 'budget_usage_spike')
          AND alert_type <> %s
          AND details->>'budget_code' = %s
          AND details->>'period_start' = %s
          AND details->>'period_end' = %s
        """,
        (evaluation.alert_type, evaluation.budget_code, evaluation.period_start.isoformat(), evaluation.period_end.isoformat()),
    )
    cursor.execute(
        """
        INSERT INTO qmeta.budget_alert (
            alert_key, budget_id, snapshot_id, alert_type, severity, status,
            threshold_pct, usage_pct, message, details, last_seen_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, 'open', %s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (alert_key) DO UPDATE SET
            snapshot_id = EXCLUDED.snapshot_id,
            severity = EXCLUDED.severity,
            status = 'open',
            threshold_pct = EXCLUDED.threshold_pct,
            usage_pct = EXCLUDED.usage_pct,
            message = EXCLUDED.message,
            details = EXCLUDED.details,
            last_seen_at = now(),
            updated_at = now()
        RETURNING budget_alert_id
        """,
        (
            alert_key,
            evaluation.budget_id,
            evaluation.snapshot_id,
            evaluation.alert_type,
            evaluation.severity,
            evaluation.threshold_pct,
            evaluation.usage_pct,
            evaluation.message,
            _json(details),
        ),
    )
    cursor.fetchone()
    cursor.execute(
        """
        INSERT INTO qmeta.alert_event (
            alert_key, trade_date, alert_type, severity, status, metric_name,
            metric_value, threshold_value, message, details, last_seen_at, updated_at
        ) VALUES (%s, %s, %s, %s, 'open', 'budget_usage_pct', %s, %s, %s, %s::jsonb, now(), now())
        ON CONFLICT (alert_key) DO UPDATE SET
            severity = EXCLUDED.severity,
            status = 'open',
            metric_name = EXCLUDED.metric_name,
            metric_value = EXCLUDED.metric_value,
            threshold_value = EXCLUDED.threshold_value,
            message = EXCLUDED.message,
            details = EXCLUDED.details,
            last_seen_at = now(),
            updated_at = now()
        """,
        (
            alert_key,
            evaluation.period_end,
            evaluation.alert_type,
            evaluation.severity,
            evaluation.usage_pct,
            evaluation.threshold_pct,
            evaluation.message,
            _json({**details, "budget_id": evaluation.budget_id, "snapshot_id": evaluation.snapshot_id}),
        ),
    )


def _fetch_budget_policies(cursor, as_of_date: date, budget_code: str | None) -> list[dict[str, Any]]:
    where = ["bp.status = 'active'", "bp.starts_on <= %s", "(bp.ends_on IS NULL OR bp.ends_on >= %s)"]
    values: list[Any] = [as_of_date, as_of_date]
    if budget_code:
        where.append("bp.budget_code = %s")
        values.append(budget_code)
    cursor.execute(
        f"""
        SELECT
            bp.*, t.tenant_code, p.project_code, pr.principal_code,
            pp.plan_code, pp.base_fee, dp.product_code
        FROM qmeta.budget_policy bp
        LEFT JOIN qmeta.tenant t ON t.tenant_id = bp.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = bp.project_id
        LEFT JOIN qmeta.principal pr ON pr.principal_id = bp.principal_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = bp.plan_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = bp.product_id
        WHERE {' AND '.join(where)}
        ORDER BY bp.budget_code
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_budget_policies_for_identity(cursor, identity: Any, as_of_date: date, api_name: str) -> list[dict[str, Any]]:
    clauses = ["bp.status = 'active'", "bp.starts_on <= %s", "(bp.ends_on IS NULL OR bp.ends_on >= %s)"]
    values: list[Any] = [as_of_date, as_of_date]
    scoped = []
    for attr, column in (
        ("principal_id", "bp.principal_id"),
        ("project_id", "bp.project_id"),
        ("tenant_id", "bp.tenant_id"),
        ("cost_center", "bp.cost_center"),
    ):
        value = getattr(identity, attr, None)
        if value is not None:
            scoped.append(f"{column} = %s")
            values.append(value)
    if not scoped:
        return []
    clauses.append("(" + " OR ".join(scoped) + ")")
    clauses.append(
        """
        (
            bp.product_id IS NULL
            OR EXISTS (
                SELECT 1
                FROM qmeta.data_product_api dpa
                WHERE dpa.product_id = bp.product_id
                  AND dpa.api_name = %s
                  AND dpa.is_billable = TRUE
            )
        )
        """
    )
    values.append(api_name)
    cursor.execute(
        f"""
        SELECT
            bp.*, t.tenant_code, p.project_code, pr.principal_code,
            pp.plan_code, pp.base_fee, dp.product_code
        FROM qmeta.budget_policy bp
        LEFT JOIN qmeta.tenant t ON t.tenant_id = bp.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = bp.project_id
        LEFT JOIN qmeta.principal pr ON pr.principal_id = bp.principal_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = bp.plan_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = bp.product_id
        WHERE {' AND '.join(clauses)}
        ORDER BY
            CASE
                WHEN bp.principal_id IS NOT NULL THEN 1
                WHEN bp.project_id IS NOT NULL THEN 2
                WHEN bp.tenant_id IS NOT NULL THEN 3
                ELSE 4
            END,
            bp.budget_code
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_budget_usage_rows(cursor, budget: dict[str, Any], period_start: date, period_end: date) -> list[dict[str, Any]]:
    where = ["aud.usage_date BETWEEN %s AND %s"]
    values: list[Any] = [period_start, period_end]
    for key, column in (
        ("tenant_id", "aud.tenant_id"),
        ("project_id", "aud.project_id"),
        ("principal_id", "aud.principal_id"),
    ):
        if budget.get(key) is not None:
            where.append(f"{column} = %s")
            values.append(budget[key])
    if budget.get("cost_center"):
        where.append("tok.cost_center = %s")
        values.append(budget["cost_center"])
    if budget.get("product_id") is not None:
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM qmeta.data_product_api dpa
                WHERE dpa.product_id = %s
                  AND dpa.api_name = aud.api_name
                  AND dpa.is_billable = TRUE
            )
            """
        )
        values.append(budget["product_id"])
    cursor.execute(
        f"""
        SELECT
            aud.api_name,
            COALESCE(SUM(aud.request_count), 0) AS request_count,
            COALESCE(SUM(aud.row_count), 0) AS row_count,
            COALESCE(SUM(aud.cost_units), 0) AS cost_units
        FROM qmeta.api_usage_daily aud
        LEFT JOIN qmeta.api_token tok ON tok.token_id = aud.token_id
        WHERE {' AND '.join(where)}
        GROUP BY aud.api_name
        ORDER BY aud.api_name
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_pricing_rules(cursor, plan_id: int | None, product_id: int | None, as_of_date: date) -> list[dict[str, Any]]:
    if plan_id is None:
        return []
    where = [
        "pr.plan_id = %s",
        "pr.status = 'active'",
        "pr.effective_from <= %s",
        "(pr.effective_to IS NULL OR pr.effective_to >= %s)",
    ]
    values: list[Any] = [plan_id, as_of_date, as_of_date]
    if product_id is not None:
        where.append("(pr.product_id IS NULL OR pr.product_id = %s)")
        values.append(product_id)
    cursor.execute(
        f"""
        SELECT rule_code, metric_name, api_name, unit_price, free_quantity, product_id
        FROM qmeta.pricing_rule pr
        WHERE {' AND '.join(where)}
        ORDER BY pr.product_id NULLS LAST, pr.api_name NULLS LAST, pr.rule_id
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_plan_base_fee(cursor, plan_id: int | None) -> Decimal:
    if plan_id is None:
        return Decimal("0")
    cursor.execute("SELECT base_fee FROM qmeta.pricing_plan WHERE plan_id = %s", (plan_id,))
    row = cursor.fetchone()
    return _decimal(row["base_fee"] if row else 0)


def _estimate_next_request_amount(cursor, budget: dict[str, Any], api_name: str, as_of_date: date) -> Decimal:
    rules = _fetch_pricing_rules(cursor, budget.get("plan_id"), budget.get("product_id"), as_of_date)
    amount, _ = priced_usage_amount(
        [{"api_name": api_name, "request_count": 1, "row_count": 0, "cost_units": Decimal("1")}],
        rules,
    )
    return amount


def _alert_for_budget_status(status: str, budget: dict[str, Any]) -> tuple[str | None, str | None, Decimal | None]:
    if status == "blocked":
        return "budget_blocked", "critical", _decimal(budget["hard_threshold_pct"])
    if status == "exceeded":
        return "budget_exceeded", "high", _decimal(budget["hard_threshold_pct"])
    if status == "warning":
        return "budget_threshold_warning", "medium", _decimal(budget["soft_threshold_pct"])
    return None, None, None


def _upsert_product_dataset(cursor, product_id: int, dataset_id: int) -> None:
    cursor.execute(
        """
        INSERT INTO qmeta.data_product_dataset (product_id, dataset_id, access_level)
        VALUES (%s, %s, 'read')
        ON CONFLICT (product_id, dataset_id) DO UPDATE SET
            access_level = EXCLUDED.access_level,
            updated_at = now()
        """,
        (product_id, dataset_id),
    )


def _upsert_product_api(cursor, product_id: int, api_name: str) -> None:
    cursor.execute(
        """
        INSERT INTO qmeta.data_product_api (product_id, api_name, required_scope, is_billable)
        VALUES (%s, %s, 'read', TRUE)
        ON CONFLICT (product_id, api_name) DO UPDATE SET
            required_scope = EXCLUDED.required_scope,
            is_billable = EXCLUDED.is_billable,
            updated_at = now()
        """,
        (product_id, api_name),
    )


def _ensure_dataset(cursor, dataset_code: str) -> int:
    cursor.execute("SELECT dataset_id FROM qmeta.dataset_catalog WHERE dataset_code = %s", (dataset_code,))
    row = cursor.fetchone()
    if row:
        return int(row["dataset_id"])
    cursor.execute(
        """
        INSERT INTO qmeta.dataset_catalog (dataset_code, dataset_name, storage_layer, pit_required)
        VALUES (%s, %s, 'postgresql', FALSE)
        ON CONFLICT (dataset_code) DO UPDATE SET dataset_name = EXCLUDED.dataset_name
        RETURNING dataset_id
        """,
        (dataset_code, dataset_code),
    )
    return int(cursor.fetchone()["dataset_id"])


def _lookup_id(cursor, table: str, id_column: str, code_column: str, code: str | None) -> int:
    if not code:
        raise QDataValidationError(f"{code_column} is required")
    cursor.execute(f"SELECT {id_column} AS id FROM qmeta.{table} WHERE {code_column} = %s", (code,))
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"{table} not found: {code}")
    return int(row["id"])


def _lookup_project_id(cursor, tenant_id: int | None, project_code: str | None) -> int:
    if not project_code:
        raise QDataValidationError("project_code is required")
    if tenant_id is None:
        cursor.execute("SELECT project_id FROM qmeta.project WHERE project_code = %s ORDER BY project_id LIMIT 1", (project_code,))
    else:
        cursor.execute("SELECT project_id FROM qmeta.project WHERE tenant_id = %s AND project_code = %s", (tenant_id, project_code))
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"project not found: {project_code}")
    return int(row["project_id"])


def _lookup_principal_id(cursor, tenant_id: int | None, principal_code: str | None) -> int:
    if not principal_code:
        raise QDataValidationError("principal_code is required")
    if tenant_id is None:
        cursor.execute("SELECT principal_id FROM qmeta.principal WHERE principal_code = %s ORDER BY principal_id LIMIT 1", (principal_code,))
    else:
        cursor.execute("SELECT principal_id FROM qmeta.principal WHERE tenant_id = %s AND principal_code = %s", (tenant_id, principal_code))
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"principal not found: {principal_code}")
    return int(row["principal_id"])


def _matching_rules(pricing_rules: list[dict[str, Any]], api_name: str | None) -> list[dict[str, Any]]:
    exact = [rule for rule in pricing_rules if rule.get("api_name") == api_name]
    generic = [rule for rule in pricing_rules if not rule.get("api_name")]
    return exact or generic


def _metric_quantity(metric_name: str, row: dict[str, Any]) -> Decimal:
    if metric_name == "request":
        return _decimal(row.get("request_count") or 0)
    if metric_name == "row":
        return _decimal(row.get("row_count") or 0)
    if metric_name == "cost_unit":
        return _decimal(row.get("cost_units") or 0)
    if metric_name == "export":
        return _decimal(row.get("export_count") or 0)
    if metric_name == "monthly_fee":
        return Decimal("1")
    raise QDataValidationError(f"unknown pricing metric: {metric_name}")


def _snapshot_code(budget_code: str, period_start: date, period_end: date) -> str:
    return f"xi-budget-{budget_code}-{period_start:%Y%m%d}-{period_end:%Y%m%d}"


def _api_name(value: str) -> str:
    return value.strip().strip("/")


def _coerce_date(value: str | date) -> date:
    return parse_date(value, "as_of_date") if isinstance(value, str) else value


def _decimal(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _validate_enum(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        raise QDataValidationError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")


def _json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Xi billing") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
