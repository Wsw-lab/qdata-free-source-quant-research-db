from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


INVOICE_STATUSES = {"draft", "issued", "partially_paid", "paid", "overdue", "void"}
GENERATABLE_STATUSES = {"draft", "issued"}
LINE_METRICS = {"request", "row", "cost_unit", "export", "monthly_fee", "base_fee", "adjustment"}
AMOUNT_QUANT = Decimal("0.00000001")
UNIT_PRICE_QUANT = Decimal("0.0000000001")


def invoice_period_window(period_start: str | date, period_end: str | date) -> tuple[date, date]:
    start = parse_date(period_start, "period_start") if isinstance(period_start, str) else period_start
    end = parse_date(period_end, "period_end") if isinstance(period_end, str) else period_end
    if start > end:
        raise QDataValidationError("period_start must be less than or equal to period_end")
    return start, end


def invoice_status(
    total_amount: Decimal | int | float | str,
    paid_amount: Decimal | int | float | str,
    due_date: str | date | None,
    as_of_date: str | date,
    *,
    current_status: str = "issued",
) -> str:
    _validate_enum(current_status, INVOICE_STATUSES, "current_status")
    if current_status in {"draft", "void"}:
        return current_status
    total = _amount(total_amount)
    paid = _amount(paid_amount)
    if paid > total:
        raise QDataValidationError("paid_amount must be less than or equal to total_amount")
    current = parse_date(as_of_date, "as_of_date") if isinstance(as_of_date, str) else as_of_date
    due = parse_date(due_date, "due_date") if isinstance(due_date, str) else due_date
    outstanding = total - paid
    if total > 0 and paid >= total:
        return "paid"
    if due and current > due and outstanding > 0:
        return "overdue"
    if paid > 0:
        return "partially_paid"
    return "issued"


def build_invoice_lines(
    usage_rows: list[dict[str, Any]],
    pricing_rules: list[dict[str, Any]],
    *,
    base_fee: Decimal | int | float | str = Decimal("0"),
    product_id: int | None = None,
    period_start: str | date | None = None,
    period_end: str | date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start = _coerce_optional_date(period_start, "period_start")
    end = _coerce_optional_date(period_end, "period_end")
    if start and end and start > end:
        raise QDataValidationError("period_start must be less than or equal to period_end")

    lines: list[dict[str, Any]] = []
    request_count = 0
    row_count = 0
    cost_units = Decimal("0")
    base = _amount(base_fee)
    if base > 0:
        lines.append(
            {
                "product_id": product_id,
                "pricing_rule_id": None,
                "api_name": None,
                "metric_name": "base_fee",
                "period_start": start,
                "period_end": end,
                "quantity": Decimal("1.00000000"),
                "unit_price": _unit_price(base),
                "amount": base,
                "request_count": 0,
                "row_count": 0,
                "cost_units": Decimal("0.00000000"),
                "details": {"source": "pricing_plan.base_fee"},
            }
        )

    for row in usage_rows:
        api_name = _api_name(row.get("api_name") or "")
        row_request_count = int(row.get("request_count") or 0)
        row_count_value = int(row.get("row_count") or 0)
        row_cost_units = _amount(row.get("cost_units") or 0)
        request_count += row_request_count
        row_count += row_count_value
        cost_units += row_cost_units
        matching = _matching_rules(pricing_rules, api_name)
        if not matching:
            quantity = row_cost_units
            amount = _amount(quantity)
            lines.append(
                _usage_line(
                    product_id=product_id,
                    pricing_rule_id=None,
                    api_name=api_name,
                    metric_name="cost_unit",
                    period_start=start,
                    period_end=end,
                    quantity=quantity,
                    unit_price=Decimal("1"),
                    amount=amount,
                    request_count=row_request_count,
                    row_count=row_count_value,
                    cost_units=row_cost_units,
                    details={"fallback_pricing": True, "raw_quantity": str(row_cost_units), "free_quantity": "0"},
                )
            )
            continue
        for rule in matching:
            metric_name = str(rule.get("metric_name") or "cost_unit")
            _validate_enum(metric_name, LINE_METRICS, "metric_name")
            raw_quantity = _metric_quantity(metric_name, row)
            free_quantity = _amount(rule.get("free_quantity") or 0)
            billable_quantity = max(raw_quantity - free_quantity, Decimal("0"))
            unit_price = _unit_price(rule.get("unit_price") or 0)
            amount = _amount(billable_quantity * unit_price)
            lines.append(
                _usage_line(
                    product_id=rule.get("product_id") or product_id,
                    pricing_rule_id=rule.get("pricing_rule_id") or rule.get("rule_id"),
                    api_name=api_name,
                    metric_name=metric_name,
                    period_start=start,
                    period_end=end,
                    quantity=billable_quantity,
                    unit_price=unit_price,
                    amount=amount,
                    request_count=row_request_count,
                    row_count=row_count_value,
                    cost_units=row_cost_units,
                    details={
                        "rule_code": rule.get("rule_code"),
                        "raw_quantity": str(raw_quantity),
                        "free_quantity": str(free_quantity),
                    },
                )
            )

    subtotal = _amount(sum((_decimal(line["amount"]) for line in lines), Decimal("0")))
    return lines, {
        "line_count": len(lines),
        "request_count": request_count,
        "row_count": row_count,
        "cost_units": _amount(cost_units),
        "subtotal_amount": subtotal,
    }


def generate_invoices(
    postgres_dsn: str,
    *,
    period_start: str | date,
    period_end: str | date,
    tenant_code: str | None = None,
    project_code: str | None = None,
    subscription_code: str | None = None,
    invoice_date: str | date | None = None,
    due_days: int = 15,
    status: str = "issued",
    write_db: bool = True,
) -> list[dict[str, Any]]:
    _validate_enum(status, GENERATABLE_STATUSES, "status")
    if due_days < 0:
        raise QDataValidationError("due_days must be greater than or equal to 0")
    start, end = invoice_period_window(period_start, period_end)
    invoice_day = _coerce_optional_date(invoice_date, "invoice_date") or date.today()
    due_date = invoice_day + timedelta(days=due_days)

    invoices: list[dict[str, Any]] = []
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
                lines, usage_summary = build_invoice_lines(
                    usage_rows,
                    pricing_rules,
                    base_fee=subscription.get("base_fee") or 0,
                    product_id=subscription["product_id"],
                    period_start=start,
                    period_end=end,
                )
                subtotal = _amount(usage_summary["subtotal_amount"])
                discount = Decimal("0.00000000")
                tax = Decimal("0.00000000")
                total = _amount(subtotal - discount + tax)
                paid = Decimal("0.00000000")
                invoice_code = _invoice_code(subscription, start, end)
                planned_status = status if status == "draft" else invoice_status(total, paid, due_date, invoice_day, current_status="issued")
                invoice = {
                    "invoice_code": invoice_code,
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
                    "period_start": start,
                    "period_end": end,
                    "invoice_date": invoice_day,
                    "due_date": due_date,
                    "currency": subscription["currency"],
                    "status": planned_status,
                    "subtotal_amount": subtotal,
                    "discount_amount": discount,
                    "tax_amount": tax,
                    "total_amount": total,
                    "paid_amount": paid,
                    "outstanding_amount": total,
                    "line_count": len(lines),
                    "request_count": usage_summary["request_count"],
                    "row_count": usage_summary["row_count"],
                    "cost_units": usage_summary["cost_units"],
                    "details": {
                        "source": "omicron_invoice_generation",
                        "usage_row_count": len(usage_rows),
                        "pricing_rule_count": len(pricing_rules),
                    },
                }
                if write_db:
                    db_invoice = _upsert_invoice(cursor, invoice)
                    invoice.update(db_invoice)
                    _replace_invoice_lines(cursor, int(invoice["invoice_id"]), invoice_code, lines)
                    _write_invoice_event(
                        cursor,
                        int(invoice["invoice_id"]),
                        invoice_code=invoice_code,
                        event_type="generated",
                        status="success",
                        message=f"Generated invoice {invoice_code}",
                        details={
                            "period_start": start.isoformat(),
                            "period_end": end.isoformat(),
                            "line_count": len(lines),
                            "total_amount": str(total),
                        },
                    )
                invoice["lines"] = [_public_line(line, invoice_code, index) for index, line in enumerate(lines, start=1)]
                invoices.append(_public_invoice(invoice))
    return invoices


def mark_invoice_status(
    postgres_dsn: str,
    *,
    invoice_code: str,
    status: str,
    paid_amount: Decimal | int | float | str | None = None,
    event_message: str | None = None,
) -> dict[str, Any]:
    _validate_enum(status, INVOICE_STATUSES, "status")
    if not invoice_code:
        raise QDataValidationError("invoice_code is required")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT invoice_id, invoice_code, total_amount, paid_amount, due_date, status
                FROM qmeta.invoice
                WHERE invoice_code = %s
                FOR UPDATE
                """,
                (invoice_code,),
            )
            existing = cursor.fetchone()
            if not existing:
                raise QDataValidationError(f"invoice not found: {invoice_code}")
            total = _amount(existing["total_amount"])
            paid = _amount(paid_amount) if paid_amount is not None else _amount(existing["paid_amount"])
            target_status = status
            if status == "paid":
                paid = total
            if paid > total:
                raise QDataValidationError("paid_amount must be less than or equal to total_amount")
            if status == "void":
                outstanding = Decimal("0.00000000")
            else:
                outstanding = _amount(total - paid)
            if status in {"issued", "partially_paid"}:
                target_status = invoice_status(total, paid, existing.get("due_date"), date.today(), current_status="issued")
            elif status == "overdue" and outstanding <= 0:
                target_status = "paid" if total > 0 else "issued"

            cursor.execute(
                """
                UPDATE qmeta.invoice
                SET
                    status = %s,
                    paid_amount = %s,
                    outstanding_amount = %s,
                    issued_at = CASE WHEN %s IN ('issued', 'partially_paid', 'paid', 'overdue') THEN COALESCE(issued_at, now()) ELSE issued_at END,
                    paid_at = CASE WHEN %s = 'paid' THEN COALESCE(paid_at, now()) ELSE NULL END,
                    voided_at = CASE WHEN %s = 'void' THEN COALESCE(voided_at, now()) ELSE NULL END,
                    updated_at = now()
                WHERE invoice_code = %s
                RETURNING *
                """,
                (target_status, paid, outstanding, target_status, target_status, target_status, invoice_code),
            )
            invoice = dict(cursor.fetchone())
            _write_invoice_event(
                cursor,
                int(invoice["invoice_id"]),
                invoice_code=invoice_code,
                event_type=_event_type_for_status(target_status),
                status="success",
                message=event_message or f"Invoice {invoice_code} marked {target_status}",
                details={"paid_amount": str(paid), "outstanding_amount": str(outstanding), "previous_status": existing["status"]},
            )
            return _public_invoice(invoice)


def format_invoice_report(rows: list[dict[str, Any]]) -> str:
    lines = [f"omicron invoices rows={len(rows)}"]
    for row in rows:
        bits = [
            f"invoice={row.get('invoice_code')}",
            f"tenant={row.get('tenant_code')}",
            f"project={row.get('project_code') or 'all'}",
            f"product={row.get('product_code')}",
            f"period={row.get('period_start')}..{row.get('period_end')}",
            f"status={row.get('status')}",
            f"total={row.get('total_amount')}",
            f"paid={row.get('paid_amount')}",
            f"outstanding={row.get('outstanding_amount')}",
            f"lines={row.get('line_count')}",
        ]
        lines.append(" ".join(bit for bit in bits if bit.split("=", 1)[1] not in {"None", ""}))
    return "\n".join(lines)


def _fetch_subscriptions(
    cursor,
    *,
    period_start: date,
    period_end: date,
    tenant_code: str | None,
    project_code: str | None,
    subscription_code: str | None,
) -> list[dict[str, Any]]:
    where = [
        "ps.status = 'active'",
        "ps.starts_on <= %s",
        "(ps.ends_on IS NULL OR ps.ends_on >= %s)",
    ]
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


def _upsert_invoice(cursor, invoice: dict[str, Any]) -> dict[str, Any]:
    issued_at = datetime.now(timezone.utc) if invoice["status"] != "draft" else None
    cursor.execute(
        """
        INSERT INTO qmeta.invoice AS inv (
            invoice_code, tenant_id, project_id, subscription_id, plan_id, product_id,
            period_start, period_end, invoice_date, due_date, currency, status,
            subtotal_amount, discount_amount, tax_amount, total_amount, paid_amount,
            outstanding_amount, issued_at, details
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s::jsonb
        )
        ON CONFLICT (invoice_code) DO UPDATE SET
            tenant_id = EXCLUDED.tenant_id,
            project_id = EXCLUDED.project_id,
            subscription_id = EXCLUDED.subscription_id,
            plan_id = EXCLUDED.plan_id,
            product_id = EXCLUDED.product_id,
            period_start = EXCLUDED.period_start,
            period_end = EXCLUDED.period_end,
            invoice_date = EXCLUDED.invoice_date,
            due_date = EXCLUDED.due_date,
            currency = EXCLUDED.currency,
            status = CASE
                WHEN inv.status = 'void' THEN 'void'
                WHEN EXCLUDED.status = 'draft' AND inv.status = 'draft' THEN 'draft'
                WHEN LEAST(inv.paid_amount, EXCLUDED.total_amount) >= EXCLUDED.total_amount AND EXCLUDED.total_amount > 0 THEN 'paid'
                WHEN LEAST(inv.paid_amount, EXCLUDED.total_amount) > 0 THEN 'partially_paid'
                ELSE EXCLUDED.status
            END,
            subtotal_amount = EXCLUDED.subtotal_amount,
            discount_amount = EXCLUDED.discount_amount,
            tax_amount = EXCLUDED.tax_amount,
            total_amount = EXCLUDED.total_amount,
            paid_amount = LEAST(inv.paid_amount, EXCLUDED.total_amount),
            outstanding_amount = CASE
                WHEN inv.status = 'void' THEN 0
                ELSE GREATEST(EXCLUDED.total_amount - LEAST(inv.paid_amount, EXCLUDED.total_amount), 0)
            END,
            issued_at = CASE WHEN EXCLUDED.status <> 'draft' THEN COALESCE(inv.issued_at, EXCLUDED.issued_at, now()) ELSE inv.issued_at END,
            paid_at = CASE
                WHEN LEAST(inv.paid_amount, EXCLUDED.total_amount) >= EXCLUDED.total_amount AND EXCLUDED.total_amount > 0 THEN COALESCE(inv.paid_at, now())
                ELSE NULL
            END,
            voided_at = CASE WHEN inv.status = 'void' THEN COALESCE(inv.voided_at, now()) ELSE NULL END,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING *
        """,
        (
            invoice["invoice_code"],
            invoice["tenant_id"],
            invoice.get("project_id"),
            invoice.get("subscription_id"),
            invoice.get("plan_id"),
            invoice.get("product_id"),
            invoice["period_start"],
            invoice["period_end"],
            invoice["invoice_date"],
            invoice.get("due_date"),
            invoice["currency"],
            invoice["status"],
            invoice["subtotal_amount"],
            invoice["discount_amount"],
            invoice["tax_amount"],
            invoice["total_amount"],
            invoice["paid_amount"],
            invoice["outstanding_amount"],
            issued_at,
            _json(invoice.get("details") or {}),
        ),
    )
    return dict(cursor.fetchone())


def _replace_invoice_lines(cursor, invoice_id: int, invoice_code: str, lines: list[dict[str, Any]]) -> None:
    cursor.execute("DELETE FROM qmeta.invoice_line WHERE invoice_id = %s", (invoice_id,))
    for index, line in enumerate(lines, start=1):
        public_line = _public_line(line, invoice_code, index)
        cursor.execute(
            """
            INSERT INTO qmeta.invoice_line (
                invoice_id, line_code, product_id, pricing_rule_id, api_name, metric_name,
                period_start, period_end, quantity, unit_price, amount, request_count,
                row_count, cost_units, details
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb
            )
            """,
            (
                invoice_id,
                public_line["line_code"],
                line.get("product_id"),
                line.get("pricing_rule_id"),
                line.get("api_name"),
                line["metric_name"],
                line["period_start"],
                line["period_end"],
                line["quantity"],
                line["unit_price"],
                line["amount"],
                line["request_count"],
                line["row_count"],
                line["cost_units"],
                _json(line.get("details") or {}),
            ),
        )


def _write_invoice_event(
    cursor,
    invoice_id: int,
    *,
    invoice_code: str,
    event_type: str,
    status: str,
    message: str,
    details: dict[str, Any],
) -> None:
    created_key = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    event_code = _bounded_code(f"omicron-{event_type}-{invoice_code}-{created_key}", 220)
    cursor.execute(
        """
        INSERT INTO qmeta.invoice_event (
            invoice_id, event_code, event_type, status, message, details
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (invoice_id, event_code, event_type, status, message, _json(details)),
    )


def _public_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
    return normalize_rows([{key: _stringify_amount(value) for key, value in invoice.items()}])[0]


def _public_line(line: dict[str, Any], invoice_code: str, index: int) -> dict[str, Any]:
    api_part = line.get("api_name") or "base"
    line_code = _bounded_code(f"line-{invoice_code}-{api_part}-{line['metric_name']}-{index:03d}", 220)
    public = dict(line)
    public["line_code"] = line_code
    return normalize_rows([{key: _stringify_amount(value) for key, value in public.items()}])[0]


def _usage_line(
    *,
    product_id: int | None,
    pricing_rule_id: int | None,
    api_name: str,
    metric_name: str,
    period_start: date | None,
    period_end: date | None,
    quantity: Decimal,
    unit_price: Decimal,
    amount: Decimal,
    request_count: int,
    row_count: int,
    cost_units: Decimal,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "pricing_rule_id": pricing_rule_id,
        "api_name": api_name,
        "metric_name": metric_name,
        "period_start": period_start,
        "period_end": period_end,
        "quantity": _amount(quantity),
        "unit_price": _unit_price(unit_price),
        "amount": _amount(amount),
        "request_count": request_count,
        "row_count": row_count,
        "cost_units": _amount(cost_units),
        "details": details,
    }


def _matching_rules(pricing_rules: list[dict[str, Any]], api_name: str | None) -> list[dict[str, Any]]:
    exact = [rule for rule in pricing_rules if rule.get("api_name") == api_name]
    generic = [rule for rule in pricing_rules if not rule.get("api_name")]
    return exact or generic


def _metric_quantity(metric_name: str, row: dict[str, Any]) -> Decimal:
    if metric_name == "request":
        return _amount(row.get("request_count") or 0)
    if metric_name == "row":
        return _amount(row.get("row_count") or 0)
    if metric_name == "cost_unit":
        return _amount(row.get("cost_units") or 0)
    if metric_name == "export":
        return _amount(row.get("export_count") or 0)
    if metric_name in {"monthly_fee", "base_fee"}:
        return Decimal("1.00000000")
    raise QDataValidationError(f"unknown invoice metric: {metric_name}")


def _invoice_code(subscription: dict[str, Any], period_start: date, period_end: date) -> str:
    project_code = subscription.get("project_code") or "all"
    raw = (
        f"inv-{subscription['tenant_code']}-{project_code}-{subscription['product_code']}-"
        f"{period_start:%Y%m%d}-{period_end:%Y%m%d}"
    )
    return _bounded_code(_slug(raw), 180)


def _event_type_for_status(status: str) -> str:
    if status in {"paid", "partially_paid"}:
        return "paid"
    if status in {"issued", "overdue", "void"}:
        return status
    return "manual_note"


def _bounded_code(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{value[:max_length - 13]}-{digest}"


def _slug(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_.-]+", "-", value.strip())
    return re.sub(r"-+", "-", text).strip("-").lower()


def _api_name(value: str) -> str:
    return value.strip().strip("/")


def _coerce_optional_date(value: str | date | None, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    return parse_date(value, field_name) if isinstance(value, str) else value


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
        raise QDataValidationError("psycopg is required for Omicron billing") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
