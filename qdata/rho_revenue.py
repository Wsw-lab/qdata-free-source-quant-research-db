from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError
from qdata.omicron_billing import build_invoice_lines, invoice_period_window


AMOUNT_QUANT = Decimal("0.00000001")
UNIT_PRICE_QUANT = Decimal("0.0000000001")
RECONCILIATION_STATUSES = {"matched", "mismatch", "missing_invoice", "warning"}
LINE_STATUSES = {"matched", "mismatch", "missing_invoice_line", "extra_invoice_line"}
AGING_STATUSES = {"current", "watch", "overdue", "critical"}
CUSTOMER_HEALTH_STATUSES = {"active", "at_risk", "dormant", "churned"}
RETENTION_SIGNALS = {"healthy", "payment_risk", "usage_declining", "inactive", "no_usage"}


def build_reconciliation_lines(
    invoice_lines: list[dict[str, Any]],
    recomputed_lines: list[dict[str, Any]],
    *,
    tolerance_amount: Decimal | int | float | str = Decimal("0.00000001"),
) -> list[dict[str, Any]]:
    tolerance = _amount(tolerance_amount)
    expected = _aggregate_lines(recomputed_lines, side="recomputed")
    actual = _aggregate_lines(invoice_lines, side="invoice")
    rows: list[dict[str, Any]] = []
    for line_key in sorted(set(expected) | set(actual)):
        recomputed = expected.get(line_key)
        invoice = actual.get(line_key)
        recomputed_quantity = _amount(recomputed.get("quantity") if recomputed else 0)
        invoice_quantity = _amount(invoice.get("quantity") if invoice else 0)
        recomputed_amount = _amount(recomputed.get("amount") if recomputed else 0)
        invoice_amount = _amount(invoice.get("amount") if invoice else 0)
        amount_delta = _amount(invoice_amount - recomputed_amount)
        quantity_delta = _amount(invoice_quantity - recomputed_quantity)
        if invoice is None:
            status = "missing_invoice_line"
            template = recomputed or {}
        elif recomputed is None:
            status = "extra_invoice_line"
            template = invoice
        elif abs(amount_delta) > tolerance or abs(quantity_delta) > tolerance:
            status = "mismatch"
            template = recomputed
        else:
            status = "matched"
            template = recomputed
        rows.append(
            {
                "line_key": line_key,
                "invoice_line_id": (invoice or {}).get("invoice_line_id") or (invoice or {}).get("line_id"),
                "api_name": template.get("api_name"),
                "metric_name": template.get("metric_name") or "cost_unit",
                "product_id": template.get("product_id"),
                "pricing_rule_id": template.get("pricing_rule_id") or template.get("rule_id"),
                "status": status,
                "recomputed_quantity": recomputed_quantity,
                "invoice_quantity": invoice_quantity,
                "quantity_delta": quantity_delta,
                "recomputed_amount": recomputed_amount,
                "invoice_amount": invoice_amount,
                "amount_delta": amount_delta,
                "request_count": int((recomputed or invoice or {}).get("request_count") or 0),
                "row_count": int((recomputed or invoice or {}).get("row_count") or 0),
                "cost_units": _amount((recomputed or invoice or {}).get("cost_units") or 0),
                "details": {
                    "invoice_line_ids": (invoice or {}).get("line_ids") or [],
                    "invoice_line_count": (invoice or {}).get("line_count") or 0,
                    "recomputed_line_count": (recomputed or {}).get("line_count") or 0,
                },
            }
        )
    return rows


def ar_aging_status(
    *,
    outstanding_amount: Decimal | int | float | str,
    bucket_1_30_amount: Decimal | int | float | str = 0,
    bucket_31_60_amount: Decimal | int | float | str = 0,
    bucket_61_90_amount: Decimal | int | float | str = 0,
    bucket_90_plus_amount: Decimal | int | float | str = 0,
) -> str:
    outstanding = _amount(outstanding_amount)
    if outstanding <= 0:
        return "current"
    if _amount(bucket_90_plus_amount) > 0 or _amount(bucket_61_90_amount) > 0:
        return "critical"
    if _amount(bucket_31_60_amount) > 0 or _amount(bucket_1_30_amount) > 0:
        return "overdue"
    return "watch"


def customer_health_status(
    last_usage_date: str | date | None,
    as_of_date: str | date,
    *,
    overdue_invoice_count: int = 0,
) -> tuple[str, str, int, int | None]:
    current = parse_date(as_of_date, "as_of_date") if isinstance(as_of_date, str) else as_of_date
    usage_date = parse_date(last_usage_date, "last_usage_date") if isinstance(last_usage_date, str) else last_usage_date
    if usage_date is None:
        return "churned", "no_usage", 0, None
    days_since = max((current - usage_date).days, 0)
    if days_since <= 30 and overdue_invoice_count <= 0:
        return "active", "healthy", 90, days_since
    if overdue_invoice_count > 0:
        return "at_risk", "payment_risk", max(55 - min(days_since, 30), 20), days_since
    if days_since <= 60:
        return "at_risk", "usage_declining", 65, days_since
    if days_since <= 90:
        return "dormant", "inactive", 40, days_since
    return "churned", "inactive", 10, days_since


def reconcile_revenue(
    postgres_dsn: str,
    *,
    period_start: str | date,
    period_end: str | date,
    tenant_code: str | None = None,
    project_code: str | None = None,
    subscription_code: str | None = None,
    reconciliation_date: str | date | None = None,
    tolerance_amount: Decimal | int | float | str = Decimal("0.00000001"),
    write_db: bool = True,
) -> list[dict[str, Any]]:
    start, end = invoice_period_window(period_start, period_end)
    run_date = _coerce_optional_date(reconciliation_date, "reconciliation_date") or date.today()
    tolerance = _amount(tolerance_amount)
    rows: list[dict[str, Any]] = []
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            subscriptions = _fetch_subscriptions(
                cursor,
                period_start=start,
                period_end=end,
                tenant_code=tenant_code,
                project_code=project_code,
                subscription_code=subscription_code,
            )
            for subscription in subscriptions:
                usage_rows = _fetch_subscription_usage_rows(cursor, subscription, start, end)
                pricing_rules = _fetch_pricing_rules(cursor, subscription["plan_id"], subscription["product_id"], end)
                recomputed_lines, summary = build_invoice_lines(
                    usage_rows,
                    pricing_rules,
                    base_fee=subscription.get("base_fee") or 0,
                    product_id=subscription["product_id"],
                    period_start=start,
                    period_end=end,
                )
                invoice_code = _invoice_code(subscription, start, end)
                invoice = _fetch_invoice(cursor, invoice_code)
                invoice_lines = _fetch_invoice_lines(cursor, int(invoice["invoice_id"])) if invoice else []
                line_rows = build_reconciliation_lines(invoice_lines, recomputed_lines, tolerance_amount=tolerance)
                line_counts = _line_status_counts(line_rows)
                recomputed_total = _amount(summary["subtotal_amount"])
                invoice_total = _amount(invoice.get("total_amount") if invoice else 0)
                amount_delta = _amount(invoice_total - recomputed_total)
                status = _reconciliation_status(invoice, amount_delta, line_counts, tolerance)
                run = {
                    "reconciliation_code": _reconciliation_code(subscription, start, end, run_date),
                    "tenant_id": subscription["tenant_id"],
                    "tenant_code": subscription["tenant_code"],
                    "project_id": subscription.get("project_id"),
                    "project_code": subscription.get("project_code"),
                    "subscription_id": subscription["subscription_id"],
                    "subscription_code": subscription["subscription_code"],
                    "plan_id": subscription["plan_id"],
                    "plan_code": subscription["plan_code"],
                    "product_id": subscription["product_id"],
                    "product_code": subscription["product_code"],
                    "invoice_id": invoice.get("invoice_id") if invoice else None,
                    "invoice_code": invoice_code,
                    "period_start": start,
                    "period_end": end,
                    "reconciliation_date": run_date,
                    "currency": subscription["currency"],
                    "status": status,
                    "tolerance_amount": tolerance,
                    "recomputed_subtotal_amount": recomputed_total,
                    "recomputed_total_amount": recomputed_total,
                    "invoice_subtotal_amount": _amount(invoice.get("subtotal_amount") if invoice else 0),
                    "invoice_total_amount": invoice_total,
                    "amount_delta": amount_delta,
                    "invoice_paid_amount": _amount(invoice.get("paid_amount") if invoice else 0),
                    "invoice_outstanding_amount": _amount(invoice.get("outstanding_amount") if invoice else 0),
                    "recomputed_line_count": len(recomputed_lines),
                    "invoice_line_count": len(invoice_lines),
                    "matched_line_count": line_counts["matched"],
                    "mismatch_line_count": line_counts["mismatch"],
                    "missing_line_count": line_counts["missing_invoice_line"],
                    "extra_line_count": line_counts["extra_invoice_line"],
                    "request_count": summary["request_count"],
                    "row_count": summary["row_count"],
                    "cost_units": summary["cost_units"],
                    "details": {
                        "source": "rho_revenue_reconciliation",
                        "usage_row_count": len(usage_rows),
                        "pricing_rule_count": len(pricing_rules),
                        "invoice_found": invoice is not None,
                    },
                }
                if write_db:
                    db_run = _upsert_reconciliation_run(cursor, run)
                    run.update(db_run)
                    _replace_reconciliation_lines(cursor, int(run["reconciliation_id"]), line_rows)
                run["lines"] = [_public(row) for row in line_rows]
                rows.append(_public(run))
    return rows


def generate_ar_aging_snapshots(
    postgres_dsn: str,
    *,
    as_of_date: str | date,
    tenant_code: str | None = None,
    project_code: str | None = None,
    product_code: str | None = None,
    plan_code: str | None = None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    write_db: bool = True,
) -> list[dict[str, Any]]:
    current = parse_date(as_of_date, "as_of_date") if isinstance(as_of_date, str) else as_of_date
    start = _coerce_optional_date(start_date, "start_date")
    end = _coerce_optional_date(end_date, "end_date")
    if start and end and start > end:
        raise QDataValidationError("start_date must be less than or equal to end_date")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            invoices = _fetch_ar_invoices(
                cursor,
                as_of_date=current,
                tenant_code=tenant_code,
                project_code=project_code,
                product_code=product_code,
                plan_code=plan_code,
                start_date=start,
                end_date=end,
            )
            snapshots = _build_ar_snapshots(invoices, current)
            if write_db:
                snapshots = [_public(_upsert_ar_aging_snapshot(cursor, snapshot)) for snapshot in snapshots]
            else:
                snapshots = [_public(snapshot) for snapshot in snapshots]
    return snapshots


def generate_customer_health_snapshots(
    postgres_dsn: str,
    *,
    as_of_date: str | date,
    tenant_code: str | None = None,
    project_code: str | None = None,
    product_code: str | None = None,
    subscription_code: str | None = None,
    write_db: bool = True,
) -> list[dict[str, Any]]:
    current = parse_date(as_of_date, "as_of_date") if isinstance(as_of_date, str) else as_of_date
    rows: list[dict[str, Any]] = []
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            subscriptions = _fetch_health_subscriptions(
                cursor,
                as_of_date=current,
                tenant_code=tenant_code,
                project_code=project_code,
                product_code=product_code,
                subscription_code=subscription_code,
            )
            for subscription in subscriptions:
                usage = _fetch_subscription_health_usage(cursor, subscription, current)
                invoices = _fetch_subscription_health_invoices(cursor, subscription, current)
                status, signal, base_score, days_since = customer_health_status(
                    usage.get("last_usage_date"),
                    current,
                    overdue_invoice_count=int(invoices.get("overdue_invoice_count") or 0),
                )
                score = _health_score(
                    base_score=base_score,
                    request_count_7d=int(usage.get("request_count_7d") or 0),
                    paid_amount=_amount(invoices.get("paid_amount_90d") or 0),
                    total_amount=_amount(invoices.get("total_amount_90d") or 0),
                    overdue_invoice_count=int(invoices.get("overdue_invoice_count") or 0),
                )
                snapshot = {
                    "health_code": _health_code(subscription, current),
                    "tenant_id": subscription["tenant_id"],
                    "tenant_code": subscription["tenant_code"],
                    "project_id": subscription.get("project_id"),
                    "project_code": subscription.get("project_code"),
                    "subscription_id": subscription["subscription_id"],
                    "subscription_code": subscription["subscription_code"],
                    "product_id": subscription["product_id"],
                    "product_code": subscription["product_code"],
                    "plan_id": subscription["plan_id"],
                    "plan_code": subscription["plan_code"],
                    "as_of_date": current,
                    "status": status,
                    "retention_signal": signal,
                    "health_score": score,
                    "last_usage_date": usage.get("last_usage_date"),
                    "days_since_last_usage": days_since,
                    "request_count_7d": int(usage.get("request_count_7d") or 0),
                    "request_count_30d": int(usage.get("request_count_30d") or 0),
                    "request_count_90d": int(usage.get("request_count_90d") or 0),
                    "cost_units_30d": _amount(usage.get("cost_units_30d") or 0),
                    "invoice_count_90d": int(invoices.get("invoice_count_90d") or 0),
                    "paid_amount_90d": _amount(invoices.get("paid_amount_90d") or 0),
                    "total_amount_90d": _amount(invoices.get("total_amount_90d") or 0),
                    "outstanding_amount": _amount(invoices.get("outstanding_amount") or 0),
                    "overdue_amount": _amount(invoices.get("overdue_amount") or 0),
                    "overdue_invoice_count": int(invoices.get("overdue_invoice_count") or 0),
                    "details": {"source": "rho_customer_health"},
                }
                if write_db:
                    snapshot = _upsert_customer_health_snapshot(cursor, snapshot)
                rows.append(_public(snapshot))
    return rows


def format_reconciliation_report(rows: list[dict[str, Any]]) -> str:
    lines = [f"rho reconciliation rows={len(rows)}"]
    for row in rows:
        lines.append(
            " ".join(
                bit
                for bit in [
                    f"reconciliation={row.get('reconciliation_code')}",
                    f"tenant={row.get('tenant_code')}",
                    f"project={row.get('project_code') or 'all'}",
                    f"product={row.get('product_code')}",
                    f"period={row.get('period_start')}..{row.get('period_end')}",
                    f"status={row.get('status')}",
                    f"invoice_total={row.get('invoice_total_amount')}",
                    f"recomputed_total={row.get('recomputed_total_amount')}",
                    f"delta={row.get('amount_delta')}",
                    f"mismatches={row.get('mismatch_line_count')}",
                ]
            )
        )
    return "\n".join(lines)


def format_ar_aging_report(rows: list[dict[str, Any]]) -> str:
    lines = [f"rho ar-aging rows={len(rows)}"]
    for row in rows:
        lines.append(
            " ".join(
                [
                    f"aging={row.get('aging_code')}",
                    f"tenant={row.get('tenant_code')}",
                    f"project={row.get('project_code') or 'all'}",
                    f"product={row.get('product_code') or 'all'}",
                    f"as_of={row.get('as_of_date')}",
                    f"status={row.get('status')}",
                    f"outstanding={row.get('outstanding_amount')}",
                    f"overdue={row.get('overdue_invoice_count')}",
                    f"max_days={row.get('max_days_past_due')}",
                ]
            )
        )
    return "\n".join(lines)


def format_customer_health_report(rows: list[dict[str, Any]]) -> str:
    lines = [f"rho customer-health rows={len(rows)}"]
    for row in rows:
        lines.append(
            " ".join(
                [
                    f"health={row.get('health_code')}",
                    f"tenant={row.get('tenant_code')}",
                    f"project={row.get('project_code') or 'all'}",
                    f"product={row.get('product_code')}",
                    f"as_of={row.get('as_of_date')}",
                    f"status={row.get('status')}",
                    f"signal={row.get('retention_signal')}",
                    f"score={row.get('health_score')}",
                    f"requests_30d={row.get('request_count_30d')}",
                ]
            )
        )
    return "\n".join(lines)


def _aggregate_lines(lines: list[dict[str, Any]], *, side: str) -> dict[str, dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}
    for line in lines:
        key = _line_key(line)
        existing = aggregates.setdefault(
            key,
            {
                "line_key": key,
                "api_name": line.get("api_name"),
                "metric_name": line.get("metric_name") or "cost_unit",
                "product_id": line.get("product_id"),
                "pricing_rule_id": line.get("pricing_rule_id") or line.get("rule_id"),
                "quantity": Decimal("0"),
                "amount": Decimal("0"),
                "request_count": 0,
                "row_count": 0,
                "cost_units": Decimal("0"),
                "line_ids": [],
                "line_count": 0,
            },
        )
        existing["quantity"] += _amount(line.get("quantity") or 0)
        existing["amount"] += _amount(line.get("amount") or 0)
        existing["request_count"] += int(line.get("request_count") or 0)
        existing["row_count"] += int(line.get("row_count") or 0)
        existing["cost_units"] += _amount(line.get("cost_units") or 0)
        existing["line_count"] += 1
        line_id = line.get("line_id") or line.get("invoice_line_id")
        if side == "invoice" and line_id is not None:
            existing["line_ids"].append(line_id)
            existing["invoice_line_id"] = existing.get("invoice_line_id") or line_id
    return aggregates


def _line_key(line: dict[str, Any]) -> str:
    product_id = line.get("product_id") or "none"
    rule_id = line.get("pricing_rule_id") or line.get("rule_id") or "none"
    api_name = line.get("api_name") or "base"
    metric_name = line.get("metric_name") or "cost_unit"
    unit_price = _unit_price(line.get("unit_price") or 0)
    return _bounded_code(f"p:{product_id}|r:{rule_id}|api:{api_name}|m:{metric_name}|u:{unit_price}", 220)


def _line_status_counts(lines: list[dict[str, Any]]) -> defaultdict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for line in lines:
        counts[str(line.get("status") or "matched")] += 1
    for status in LINE_STATUSES:
        counts[status] += 0
    return counts


def _reconciliation_status(invoice: dict[str, Any] | None, amount_delta: Decimal, line_counts: dict[str, int], tolerance: Decimal) -> str:
    if invoice is None:
        return "missing_invoice"
    if abs(amount_delta) > tolerance:
        return "mismatch"
    if line_counts.get("mismatch", 0) or line_counts.get("missing_invoice_line", 0) or line_counts.get("extra_invoice_line", 0):
        return "mismatch"
    if invoice.get("status") in {"draft", "void"}:
        return "warning"
    return "matched"


def _build_ar_snapshots(invoices: list[dict[str, Any]], as_of_date: date) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for invoice in invoices:
        key = (
            invoice["tenant_id"],
            invoice.get("project_id"),
            invoice.get("product_id"),
            invoice.get("plan_id"),
            invoice["currency"],
        )
        group = grouped.setdefault(
            key,
            {
                "tenant_id": invoice["tenant_id"],
                "tenant_code": invoice["tenant_code"],
                "project_id": invoice.get("project_id"),
                "project_code": invoice.get("project_code"),
                "product_id": invoice.get("product_id"),
                "product_code": invoice.get("product_code"),
                "plan_id": invoice.get("plan_id"),
                "plan_code": invoice.get("plan_code"),
                "as_of_date": as_of_date,
                "currency": invoice["currency"],
                "invoice_count": 0,
                "overdue_invoice_count": 0,
                "outstanding_amount": Decimal("0"),
                "current_amount": Decimal("0"),
                "bucket_1_30_amount": Decimal("0"),
                "bucket_31_60_amount": Decimal("0"),
                "bucket_61_90_amount": Decimal("0"),
                "bucket_90_plus_amount": Decimal("0"),
                "max_days_past_due": 0,
                "details": {"source": "rho_ar_aging"},
            },
        )
        group["invoice_count"] += 1
        outstanding = _amount(invoice.get("outstanding_amount") or 0)
        group["outstanding_amount"] += outstanding
        due_date = invoice.get("due_date")
        days_past_due = 0 if not due_date else max((as_of_date - due_date).days, 0)
        if outstanding > 0 and days_past_due > 0:
            group["overdue_invoice_count"] += 1
            group["max_days_past_due"] = max(group["max_days_past_due"], days_past_due)
            if days_past_due <= 30:
                group["bucket_1_30_amount"] += outstanding
            elif days_past_due <= 60:
                group["bucket_31_60_amount"] += outstanding
            elif days_past_due <= 90:
                group["bucket_61_90_amount"] += outstanding
            else:
                group["bucket_90_plus_amount"] += outstanding
        elif outstanding > 0:
            group["current_amount"] += outstanding
    snapshots: list[dict[str, Any]] = []
    for group in grouped.values():
        group["aging_code"] = _aging_code(group)
        group["status"] = ar_aging_status(
            outstanding_amount=group["outstanding_amount"],
            bucket_1_30_amount=group["bucket_1_30_amount"],
            bucket_31_60_amount=group["bucket_31_60_amount"],
            bucket_61_90_amount=group["bucket_61_90_amount"],
            bucket_90_plus_amount=group["bucket_90_plus_amount"],
        )
        snapshots.append(group)
    return snapshots


def _health_score(
    *,
    base_score: int,
    request_count_7d: int,
    paid_amount: Decimal,
    total_amount: Decimal,
    overdue_invoice_count: int,
) -> int:
    score = base_score
    if request_count_7d > 0:
        score += 10
    if total_amount > 0 and paid_amount >= total_amount:
        score += 5
    if overdue_invoice_count > 0:
        score -= 20
    return max(0, min(100, score))


def _fetch_subscriptions(
    cursor,
    *,
    period_start: date,
    period_end: date,
    tenant_code: str | None,
    project_code: str | None,
    subscription_code: str | None,
) -> list[dict[str, Any]]:
    where = ["ps.status = 'active'", "ps.starts_on <= %s", "(ps.ends_on IS NULL OR ps.ends_on >= %s)"]
    values: list[Any] = [period_end, period_start]
    for value, column in (
        (tenant_code, "t.tenant_code"),
        (project_code, "p.project_code"),
        (subscription_code, "ps.subscription_code"),
    ):
        if value:
            where.append(f"{column} = %s")
            values.append(value)
    cursor.execute(
        f"""
        SELECT
            ps.subscription_id, ps.subscription_code, ps.tenant_id, ps.project_id,
            ps.plan_id, ps.product_id, t.tenant_code, p.project_code,
            pp.plan_code, pp.currency, pp.base_fee, dp.product_code
        FROM qmeta.product_subscription ps
        JOIN qmeta.tenant t ON t.tenant_id = ps.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = ps.project_id
        JOIN qmeta.pricing_plan pp ON pp.plan_id = ps.plan_id
        JOIN qmeta.data_product dp ON dp.product_id = ps.product_id
        WHERE {' AND '.join(where)}
        ORDER BY t.tenant_code, p.project_code NULLS LAST, dp.product_code, ps.subscription_code
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_subscription_usage_rows(cursor, subscription: dict[str, Any], period_start: date, period_end: date) -> list[dict[str, Any]]:
    where = [
        "aud.usage_date BETWEEN %s AND %s",
        "aud.tenant_id = %s",
        """
        EXISTS (
            SELECT 1
            FROM qmeta.data_product_api dpa
            WHERE dpa.product_id = %s
              AND dpa.api_name = aud.api_name
              AND dpa.is_billable = TRUE
        )
        """,
    ]
    values: list[Any] = [period_start, period_end, subscription["tenant_id"], subscription["product_id"]]
    if subscription.get("project_id") is not None:
        where.append("aud.project_id = %s")
        values.append(subscription["project_id"])
    cursor.execute(
        f"""
        SELECT
            aud.api_name,
            COALESCE(SUM(aud.request_count), 0) AS request_count,
            COALESCE(SUM(aud.row_count), 0) AS row_count,
            COALESCE(SUM(aud.cost_units), 0) AS cost_units
        FROM qmeta.api_usage_daily aud
        WHERE {' AND '.join(where)}
        GROUP BY aud.api_name
        ORDER BY aud.api_name
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_pricing_rules(cursor, plan_id: int, product_id: int, as_of_date: date) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            pr.rule_id AS pricing_rule_id, pr.rule_code, pr.metric_name, pr.api_name,
            pr.unit_price, pr.free_quantity, pr.product_id
        FROM qmeta.pricing_rule pr
        WHERE pr.plan_id = %s
          AND pr.status = 'active'
          AND pr.effective_from <= %s
          AND (pr.effective_to IS NULL OR pr.effective_to >= %s)
          AND (pr.product_id IS NULL OR pr.product_id = %s)
        ORDER BY pr.product_id NULLS LAST, pr.api_name NULLS LAST, pr.rule_id
        """,
        (plan_id, as_of_date, as_of_date, product_id),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_invoice(cursor, invoice_code: str) -> dict[str, Any] | None:
    cursor.execute("SELECT * FROM qmeta.invoice WHERE invoice_code = %s", (invoice_code,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _fetch_invoice_lines(cursor, invoice_id: int) -> list[dict[str, Any]]:
    cursor.execute("SELECT * FROM qmeta.invoice_line WHERE invoice_id = %s ORDER BY line_id", (invoice_id,))
    return [dict(row) for row in cursor.fetchall()]


def _fetch_ar_invoices(
    cursor,
    *,
    as_of_date: date,
    tenant_code: str | None,
    project_code: str | None,
    product_code: str | None,
    plan_code: str | None,
    start_date: date | None,
    end_date: date | None,
) -> list[dict[str, Any]]:
    where = ["i.status <> 'void'", "i.invoice_date <= %s"]
    values: list[Any] = [as_of_date]
    for value, column in (
        (tenant_code, "t.tenant_code"),
        (project_code, "p.project_code"),
        (product_code, "dp.product_code"),
        (plan_code, "pp.plan_code"),
    ):
        if value:
            where.append(f"{column} = %s")
            values.append(value)
    if start_date:
        where.append("i.period_end >= %s")
        values.append(start_date)
    if end_date:
        where.append("i.period_start <= %s")
        values.append(end_date)
    cursor.execute(
        f"""
        SELECT
            i.invoice_id, i.invoice_code, i.tenant_id, i.project_id,
            i.product_id, i.plan_id, i.currency, i.status, i.period_start,
            i.period_end, i.invoice_date, i.due_date, i.total_amount,
            i.paid_amount, i.outstanding_amount, t.tenant_code, p.project_code,
            dp.product_code, pp.plan_code
        FROM qmeta.invoice i
        JOIN qmeta.tenant t ON t.tenant_id = i.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = i.project_id
        LEFT JOIN qmeta.data_product dp ON dp.product_id = i.product_id
        LEFT JOIN qmeta.pricing_plan pp ON pp.plan_id = i.plan_id
        WHERE {' AND '.join(where)}
        ORDER BY t.tenant_code, p.project_code NULLS LAST, dp.product_code NULLS LAST, i.invoice_date
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_health_subscriptions(
    cursor,
    *,
    as_of_date: date,
    tenant_code: str | None,
    project_code: str | None,
    product_code: str | None,
    subscription_code: str | None,
) -> list[dict[str, Any]]:
    where = ["ps.status = 'active'", "ps.starts_on <= %s", "(ps.ends_on IS NULL OR ps.ends_on >= %s)"]
    values: list[Any] = [as_of_date, as_of_date]
    for value, column in (
        (tenant_code, "t.tenant_code"),
        (project_code, "p.project_code"),
        (product_code, "dp.product_code"),
        (subscription_code, "ps.subscription_code"),
    ):
        if value:
            where.append(f"{column} = %s")
            values.append(value)
    cursor.execute(
        f"""
        SELECT
            ps.subscription_id, ps.subscription_code, ps.tenant_id, ps.project_id,
            ps.plan_id, ps.product_id, t.tenant_code, p.project_code,
            pp.plan_code, dp.product_code
        FROM qmeta.product_subscription ps
        JOIN qmeta.tenant t ON t.tenant_id = ps.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = ps.project_id
        JOIN qmeta.pricing_plan pp ON pp.plan_id = ps.plan_id
        JOIN qmeta.data_product dp ON dp.product_id = ps.product_id
        WHERE {' AND '.join(where)}
        ORDER BY t.tenant_code, p.project_code NULLS LAST, dp.product_code, ps.subscription_code
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_subscription_health_usage(cursor, subscription: dict[str, Any], as_of_date: date) -> dict[str, Any]:
    start_90 = as_of_date - timedelta(days=89)
    start_30 = as_of_date - timedelta(days=29)
    start_7 = as_of_date - timedelta(days=6)
    where = [
        "aud.usage_date BETWEEN %s AND %s",
        "aud.tenant_id = %s",
        """
        EXISTS (
            SELECT 1
            FROM qmeta.data_product_api dpa
            WHERE dpa.product_id = %s
              AND dpa.api_name = aud.api_name
              AND dpa.is_billable = TRUE
        )
        """,
    ]
    values: list[Any] = [start_90, as_of_date, subscription["tenant_id"], subscription["product_id"]]
    if subscription.get("project_id") is not None:
        where.append("aud.project_id = %s")
        values.append(subscription["project_id"])
    cursor.execute(
        f"""
        SELECT
            MAX(aud.usage_date) AS last_usage_date,
            COALESCE(SUM(CASE WHEN aud.usage_date >= %s THEN aud.request_count ELSE 0 END), 0) AS request_count_7d,
            COALESCE(SUM(CASE WHEN aud.usage_date >= %s THEN aud.request_count ELSE 0 END), 0) AS request_count_30d,
            COALESCE(SUM(aud.request_count), 0) AS request_count_90d,
            COALESCE(SUM(CASE WHEN aud.usage_date >= %s THEN aud.cost_units ELSE 0 END), 0) AS cost_units_30d
        FROM qmeta.api_usage_daily aud
        WHERE {' AND '.join(where)}
        """,
        tuple([start_7, start_30, start_30] + values),
    )
    row = cursor.fetchone()
    return dict(row) if row else {}


def _fetch_subscription_health_invoices(cursor, subscription: dict[str, Any], as_of_date: date) -> dict[str, Any]:
    start_90 = as_of_date - timedelta(days=89)
    where = ["i.status <> 'void'", "i.invoice_date <= %s", "i.tenant_id = %s", "i.product_id = %s", "i.plan_id = %s"]
    values: list[Any] = [as_of_date, subscription["tenant_id"], subscription["product_id"], subscription["plan_id"]]
    if subscription.get("project_id") is not None:
        where.append("i.project_id = %s")
        values.append(subscription["project_id"])
    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN i.invoice_date >= %s THEN 1 ELSE 0 END), 0) AS invoice_count_90d,
            COALESCE(SUM(CASE WHEN i.invoice_date >= %s THEN i.paid_amount ELSE 0 END), 0) AS paid_amount_90d,
            COALESCE(SUM(CASE WHEN i.invoice_date >= %s THEN i.total_amount ELSE 0 END), 0) AS total_amount_90d,
            COALESCE(SUM(i.outstanding_amount), 0) AS outstanding_amount,
            COALESCE(SUM(CASE WHEN i.outstanding_amount > 0 AND i.due_date < %s THEN i.outstanding_amount ELSE 0 END), 0) AS overdue_amount,
            COALESCE(SUM(CASE WHEN i.outstanding_amount > 0 AND i.due_date < %s THEN 1 ELSE 0 END), 0) AS overdue_invoice_count
        FROM qmeta.invoice i
        WHERE {' AND '.join(where)}
        """,
        tuple([start_90, start_90, start_90, as_of_date, as_of_date] + values),
    )
    row = cursor.fetchone()
    return dict(row) if row else {}


def _upsert_reconciliation_run(cursor, run: dict[str, Any]) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO qmeta.revenue_reconciliation_run (
            reconciliation_code, tenant_id, project_id, subscription_id, plan_id,
            product_id, invoice_id, period_start, period_end, reconciliation_date,
            currency, status, tolerance_amount, recomputed_subtotal_amount,
            recomputed_total_amount, invoice_subtotal_amount, invoice_total_amount,
            amount_delta, invoice_paid_amount, invoice_outstanding_amount,
            recomputed_line_count, invoice_line_count, matched_line_count,
            mismatch_line_count, missing_line_count, extra_line_count,
            request_count, row_count, cost_units, details
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s::jsonb
        )
        ON CONFLICT (reconciliation_code) DO UPDATE SET
            tenant_id = EXCLUDED.tenant_id,
            project_id = EXCLUDED.project_id,
            subscription_id = EXCLUDED.subscription_id,
            plan_id = EXCLUDED.plan_id,
            product_id = EXCLUDED.product_id,
            invoice_id = EXCLUDED.invoice_id,
            period_start = EXCLUDED.period_start,
            period_end = EXCLUDED.period_end,
            reconciliation_date = EXCLUDED.reconciliation_date,
            currency = EXCLUDED.currency,
            status = EXCLUDED.status,
            tolerance_amount = EXCLUDED.tolerance_amount,
            recomputed_subtotal_amount = EXCLUDED.recomputed_subtotal_amount,
            recomputed_total_amount = EXCLUDED.recomputed_total_amount,
            invoice_subtotal_amount = EXCLUDED.invoice_subtotal_amount,
            invoice_total_amount = EXCLUDED.invoice_total_amount,
            amount_delta = EXCLUDED.amount_delta,
            invoice_paid_amount = EXCLUDED.invoice_paid_amount,
            invoice_outstanding_amount = EXCLUDED.invoice_outstanding_amount,
            recomputed_line_count = EXCLUDED.recomputed_line_count,
            invoice_line_count = EXCLUDED.invoice_line_count,
            matched_line_count = EXCLUDED.matched_line_count,
            mismatch_line_count = EXCLUDED.mismatch_line_count,
            missing_line_count = EXCLUDED.missing_line_count,
            extra_line_count = EXCLUDED.extra_line_count,
            request_count = EXCLUDED.request_count,
            row_count = EXCLUDED.row_count,
            cost_units = EXCLUDED.cost_units,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING *
        """,
        (
            run["reconciliation_code"],
            run["tenant_id"],
            run.get("project_id"),
            run.get("subscription_id"),
            run.get("plan_id"),
            run.get("product_id"),
            run.get("invoice_id"),
            run["period_start"],
            run["period_end"],
            run["reconciliation_date"],
            run["currency"],
            run["status"],
            run["tolerance_amount"],
            run["recomputed_subtotal_amount"],
            run["recomputed_total_amount"],
            run["invoice_subtotal_amount"],
            run["invoice_total_amount"],
            run["amount_delta"],
            run["invoice_paid_amount"],
            run["invoice_outstanding_amount"],
            run["recomputed_line_count"],
            run["invoice_line_count"],
            run["matched_line_count"],
            run["mismatch_line_count"],
            run["missing_line_count"],
            run["extra_line_count"],
            run["request_count"],
            run["row_count"],
            run["cost_units"],
            _json(run.get("details") or {}),
        ),
    )
    return dict(cursor.fetchone())


def _replace_reconciliation_lines(cursor, reconciliation_id: int, lines: list[dict[str, Any]]) -> None:
    cursor.execute("DELETE FROM qmeta.revenue_reconciliation_line WHERE reconciliation_id = %s", (reconciliation_id,))
    for line in lines:
        cursor.execute(
            """
            INSERT INTO qmeta.revenue_reconciliation_line (
                reconciliation_id, invoice_line_id, line_key, api_name, metric_name,
                product_id, pricing_rule_id, status, recomputed_quantity,
                invoice_quantity, quantity_delta, recomputed_amount, invoice_amount,
                amount_delta, request_count, row_count, cost_units, details
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s::jsonb
            )
            """,
            (
                reconciliation_id,
                line.get("invoice_line_id"),
                line["line_key"],
                line.get("api_name"),
                line["metric_name"],
                line.get("product_id"),
                line.get("pricing_rule_id"),
                line["status"],
                line["recomputed_quantity"],
                line["invoice_quantity"],
                line["quantity_delta"],
                line["recomputed_amount"],
                line["invoice_amount"],
                line["amount_delta"],
                line["request_count"],
                line["row_count"],
                line["cost_units"],
                _json(line.get("details") or {}),
            ),
        )


def _upsert_ar_aging_snapshot(cursor, snapshot: dict[str, Any]) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO qmeta.ar_aging_snapshot (
            aging_code, tenant_id, project_id, product_id, plan_id, as_of_date,
            currency, status, invoice_count, overdue_invoice_count,
            outstanding_amount, current_amount, bucket_1_30_amount,
            bucket_31_60_amount, bucket_61_90_amount, bucket_90_plus_amount,
            max_days_past_due, details
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s::jsonb
        )
        ON CONFLICT (aging_code) DO UPDATE SET
            tenant_id = EXCLUDED.tenant_id,
            project_id = EXCLUDED.project_id,
            product_id = EXCLUDED.product_id,
            plan_id = EXCLUDED.plan_id,
            as_of_date = EXCLUDED.as_of_date,
            currency = EXCLUDED.currency,
            status = EXCLUDED.status,
            invoice_count = EXCLUDED.invoice_count,
            overdue_invoice_count = EXCLUDED.overdue_invoice_count,
            outstanding_amount = EXCLUDED.outstanding_amount,
            current_amount = EXCLUDED.current_amount,
            bucket_1_30_amount = EXCLUDED.bucket_1_30_amount,
            bucket_31_60_amount = EXCLUDED.bucket_31_60_amount,
            bucket_61_90_amount = EXCLUDED.bucket_61_90_amount,
            bucket_90_plus_amount = EXCLUDED.bucket_90_plus_amount,
            max_days_past_due = EXCLUDED.max_days_past_due,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING *
        """,
        (
            snapshot["aging_code"],
            snapshot["tenant_id"],
            snapshot.get("project_id"),
            snapshot.get("product_id"),
            snapshot.get("plan_id"),
            snapshot["as_of_date"],
            snapshot["currency"],
            snapshot["status"],
            snapshot["invoice_count"],
            snapshot["overdue_invoice_count"],
            _amount(snapshot["outstanding_amount"]),
            _amount(snapshot["current_amount"]),
            _amount(snapshot["bucket_1_30_amount"]),
            _amount(snapshot["bucket_31_60_amount"]),
            _amount(snapshot["bucket_61_90_amount"]),
            _amount(snapshot["bucket_90_plus_amount"]),
            snapshot["max_days_past_due"],
            _json(snapshot.get("details") or {}),
        ),
    )
    row = dict(cursor.fetchone())
    row.update({key: snapshot.get(key) for key in ("tenant_code", "project_code", "product_code", "plan_code")})
    return row


def _upsert_customer_health_snapshot(cursor, snapshot: dict[str, Any]) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO qmeta.customer_health_snapshot (
            health_code, tenant_id, project_id, subscription_id, product_id, plan_id,
            as_of_date, status, retention_signal, health_score, last_usage_date,
            days_since_last_usage, request_count_7d, request_count_30d,
            request_count_90d, cost_units_30d, invoice_count_90d,
            paid_amount_90d, total_amount_90d, outstanding_amount,
            overdue_amount, overdue_invoice_count, details
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s::jsonb
        )
        ON CONFLICT (health_code) DO UPDATE SET
            tenant_id = EXCLUDED.tenant_id,
            project_id = EXCLUDED.project_id,
            subscription_id = EXCLUDED.subscription_id,
            product_id = EXCLUDED.product_id,
            plan_id = EXCLUDED.plan_id,
            as_of_date = EXCLUDED.as_of_date,
            status = EXCLUDED.status,
            retention_signal = EXCLUDED.retention_signal,
            health_score = EXCLUDED.health_score,
            last_usage_date = EXCLUDED.last_usage_date,
            days_since_last_usage = EXCLUDED.days_since_last_usage,
            request_count_7d = EXCLUDED.request_count_7d,
            request_count_30d = EXCLUDED.request_count_30d,
            request_count_90d = EXCLUDED.request_count_90d,
            cost_units_30d = EXCLUDED.cost_units_30d,
            invoice_count_90d = EXCLUDED.invoice_count_90d,
            paid_amount_90d = EXCLUDED.paid_amount_90d,
            total_amount_90d = EXCLUDED.total_amount_90d,
            outstanding_amount = EXCLUDED.outstanding_amount,
            overdue_amount = EXCLUDED.overdue_amount,
            overdue_invoice_count = EXCLUDED.overdue_invoice_count,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING *
        """,
        (
            snapshot["health_code"],
            snapshot["tenant_id"],
            snapshot.get("project_id"),
            snapshot.get("subscription_id"),
            snapshot.get("product_id"),
            snapshot.get("plan_id"),
            snapshot["as_of_date"],
            snapshot["status"],
            snapshot["retention_signal"],
            snapshot["health_score"],
            snapshot.get("last_usage_date"),
            snapshot.get("days_since_last_usage"),
            snapshot["request_count_7d"],
            snapshot["request_count_30d"],
            snapshot["request_count_90d"],
            snapshot["cost_units_30d"],
            snapshot["invoice_count_90d"],
            snapshot["paid_amount_90d"],
            snapshot["total_amount_90d"],
            snapshot["outstanding_amount"],
            snapshot["overdue_amount"],
            snapshot["overdue_invoice_count"],
            _json(snapshot.get("details") or {}),
        ),
    )
    row = dict(cursor.fetchone())
    row.update({key: snapshot.get(key) for key in ("tenant_code", "project_code", "subscription_code", "product_code", "plan_code")})
    return row


def _invoice_code(subscription: dict[str, Any], period_start: date, period_end: date) -> str:
    project_code = subscription.get("project_code") or "all"
    raw = f"inv-{subscription['tenant_code']}-{project_code}-{subscription['product_code']}-{period_start:%Y%m%d}-{period_end:%Y%m%d}"
    return _bounded_code(_slug(raw), 180)


def _reconciliation_code(subscription: dict[str, Any], period_start: date, period_end: date, reconciliation_date: date) -> str:
    project_code = subscription.get("project_code") or "all"
    raw = (
        f"rho-recon-{subscription['tenant_code']}-{project_code}-{subscription['product_code']}-"
        f"{period_start:%Y%m%d}-{period_end:%Y%m%d}-{reconciliation_date:%Y%m%d}"
    )
    return _bounded_code(_slug(raw), 200)


def _aging_code(snapshot: dict[str, Any]) -> str:
    project_code = snapshot.get("project_code") or "all"
    product_code = snapshot.get("product_code") or "all"
    plan_code = snapshot.get("plan_code") or "all"
    raw = f"rho-ar-{snapshot['tenant_code']}-{project_code}-{product_code}-{plan_code}-{snapshot['currency']}-{snapshot['as_of_date']:%Y%m%d}"
    return _bounded_code(_slug(raw), 200)


def _health_code(subscription: dict[str, Any], as_of_date: date) -> str:
    raw = f"rho-health-{subscription['tenant_code']}-{subscription.get('project_code') or 'all'}-{subscription['subscription_code']}-{as_of_date:%Y%m%d}"
    return _bounded_code(_slug(raw), 220)


def _coerce_optional_date(value: str | date | None, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    return parse_date(value, field_name) if isinstance(value, str) else value


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return normalize_rows([{key: _stringify_amount(value) for key, value in row.items() if key != "lines"}])[0]


def _decimal(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _amount(value: Decimal | int | float | str | None) -> Decimal:
    return _decimal(value).quantize(AMOUNT_QUANT)


def _unit_price(value: Decimal | int | float | str | None) -> Decimal:
    return _decimal(value).quantize(UNIT_PRICE_QUANT)


def _stringify_amount(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _bounded_code(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{value[:max_length - 13]}-{digest}"


def _slug(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_.-]+", "-", value.strip())
    return re.sub(r"-+", "-", text).strip("-").lower()


def _json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Rho revenue reconciliation") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
