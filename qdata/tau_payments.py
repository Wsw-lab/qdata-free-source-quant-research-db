from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from qdata.backend_utils import normalize_rows, parse_date
from qdata.exceptions import QDataValidationError


AMOUNT_QUANT = Decimal("0.00000001")
FX_QUANT = Decimal("0.000000000001")
MATCH_SCORE_QUANT = Decimal("0.000001")

BATCH_SOURCE_TYPES = {"bank_csv", "alipay_csv", "wechat_csv", "manual_csv", "api", "demo"}
PAYMENT_CHANNELS = {"bank", "alipay", "wechat", "manual", "api"}
TRANSACTION_STATUSES = {"imported", "matched", "partially_matched", "overpaid", "unmatched", "ignored", "reversed"}
MATCH_STATUSES = {"matched", "partial", "overpaid", "unmatched", "reversed"}


def payment_match_decision(
    *,
    invoice_outstanding_amount: Decimal | int | float | str,
    payment_amount: Decimal | int | float | str,
    tolerance_amount: Decimal | int | float | str = Decimal("0.00000001"),
) -> dict[str, Any]:
    outstanding = _amount(invoice_outstanding_amount)
    payment = _amount(payment_amount)
    tolerance = _amount(tolerance_amount)
    if payment <= 0:
        raise QDataValidationError("payment_amount must be greater than 0")
    if outstanding <= 0:
        return {
            "status": "unmatched",
            "match_type": "rule_suggested",
            "matched_amount": Decimal("0.00000000"),
            "unmatched_amount": payment,
            "match_score": Decimal("0.000000"),
        }
    delta = payment - outstanding
    if abs(delta) <= tolerance:
        return {
            "status": "matched",
            "match_type": "auto_exact",
            "matched_amount": outstanding,
            "unmatched_amount": Decimal("0.00000000"),
            "match_score": Decimal("1.000000"),
        }
    if payment < outstanding:
        return {
            "status": "partial",
            "match_type": "auto_partial",
            "matched_amount": payment,
            "unmatched_amount": Decimal("0.00000000"),
            "match_score": Decimal("0.850000"),
        }
    return {
        "status": "overpaid",
        "match_type": "auto_overpay",
        "matched_amount": outstanding,
        "unmatched_amount": _amount(payment - outstanding),
        "match_score": Decimal("0.900000"),
    }


def extract_invoice_code(reference_text: str | None) -> str | None:
    if not reference_text:
        return None
    match = re.search(r"\binv-[0-9A-Za-z_.-]+\b", reference_text)
    return match.group(0) if match else None


def load_payment_csv(csv_path: str | Path) -> list[dict[str, Any]]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def import_payment_records(
    postgres_dsn: str,
    records: list[dict[str, Any]],
    *,
    batch_code: str,
    source_type: str = "manual_csv",
    account_code: str | None = None,
    statement_start: str | date | None = None,
    statement_end: str | date | None = None,
    currency: str = "CNY",
    base_currency: str = "CNY",
    provider: str = "manual",
    write_db: bool = True,
) -> dict[str, Any]:
    _validate_enum(source_type, BATCH_SOURCE_TYPES, "source_type")
    if not records:
        raise QDataValidationError("payment records are required")
    start = _coerce_optional_date(statement_start, "statement_start")
    end = _coerce_optional_date(statement_end, "statement_end")
    if start and end and end < start:
        raise QDataValidationError("statement_end must be greater than or equal to statement_start")
    normalized = [_normalize_payment_record(row, currency=currency, base_currency=base_currency) for row in records]
    total_amount = _amount(sum((_amount(row["amount"]) for row in normalized), Decimal("0")))
    batch = {
        "batch_code": batch_code,
        "source_type": source_type,
        "account_code": account_code,
        "statement_start": start,
        "statement_end": end,
        "currency": currency,
        "status": "imported",
        "transaction_count": len(normalized),
        "matched_count": 0,
        "unmatched_count": len(normalized),
        "total_amount": total_amount,
        "matched_amount": Decimal("0.00000000"),
        "unmatched_amount": total_amount,
        "details": {"source": "tau_payment_import", "provider": provider},
    }
    if not write_db:
        return {"batch": _public(batch), "transactions": [_public(row) for row in normalized]}
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            db_batch = _upsert_payment_batch(cursor, batch)
            transactions = [
                _upsert_payment_transaction(
                    cursor,
                    row,
                    batch_id=int(db_batch["batch_id"]),
                    source_type=source_type,
                    provider=provider,
                )
                for row in normalized
            ]
            _refresh_batch_summary(cursor, int(db_batch["batch_id"]))
            cursor.execute("SELECT * FROM qmeta.payment_import_batch WHERE batch_id = %s", (db_batch["batch_id"],))
            return {"batch": _public(dict(cursor.fetchone())), "transactions": [_public(row) for row in transactions]}


def match_payments(
    postgres_dsn: str,
    *,
    batch_code: str | None = None,
    transaction_code: str | None = None,
    tolerance_amount: Decimal | int | float | str = Decimal("0.00000001"),
    write_db: bool = True,
) -> list[dict[str, Any]]:
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            transactions = _fetch_matchable_transactions(cursor, batch_code=batch_code, transaction_code=transaction_code)
            results: list[dict[str, Any]] = []
            for transaction in transactions:
                invoice = _find_invoice_for_transaction(cursor, transaction)
                if not invoice:
                    result = _mark_transaction_unmatched(cursor, transaction, reason="invoice_not_found", write_db=write_db)
                    results.append(result)
                    continue
                if invoice["currency"] != transaction["currency"]:
                    result = _mark_transaction_unmatched(cursor, transaction, reason="currency_mismatch", invoice=invoice, write_db=write_db)
                    results.append(result)
                    continue
                existing_match = _find_existing_active_match(cursor, transaction, invoice)
                if existing_match:
                    public = _public(existing_match)
                    public["invoice_status"] = invoice["status"]
                    public["invoice_paid_amount"] = invoice["paid_amount"]
                    public["invoice_outstanding_amount"] = invoice["outstanding_amount"]
                    results.append(public)
                    continue
                decision = payment_match_decision(
                    invoice_outstanding_amount=invoice["outstanding_amount"],
                    payment_amount=transaction["amount"],
                    tolerance_amount=tolerance_amount,
                )
                if decision["status"] == "unmatched":
                    result = _mark_transaction_unmatched(cursor, transaction, reason="invoice_already_settled", invoice=invoice, write_db=write_db)
                    results.append(result)
                    continue
                if not write_db:
                    preview = {**decision, "transaction_code": transaction["transaction_code"], "invoice_code": invoice["invoice_code"]}
                    results.append(_public(preview))
                    continue
                match_row = _upsert_invoice_match(cursor, transaction, invoice, decision)
                _update_transaction_after_match(cursor, transaction, invoice, decision)
                invoice_after = _refresh_invoice_from_matches(cursor, int(invoice["invoice_id"]))
                _write_invoice_event_for_match(cursor, invoice_after, transaction, match_row, decision)
                _write_ledger_for_match(cursor, transaction, invoice_after, match_row, decision)
                if transaction.get("batch_id") is not None:
                    _refresh_batch_summary(cursor, int(transaction["batch_id"]))
                public = _public(match_row)
                public["invoice_status"] = invoice_after["status"]
                public["invoice_paid_amount"] = invoice_after["paid_amount"]
                public["invoice_outstanding_amount"] = invoice_after["outstanding_amount"]
                results.append(public)
            return results


def bootstrap_tau_demo(
    postgres_dsn: str,
    *,
    as_of_date: str | date | None = None,
    tenant_code: str = "demo",
    project_code: str = "quant-research",
    amount: Decimal | int | float | str = Decimal("100.00000000"),
    write_db: bool = True,
) -> dict[str, Any]:
    current = _coerce_optional_date(as_of_date, "as_of_date") or date.today()
    invoice = ensure_tau_demo_invoice(
        postgres_dsn,
        as_of_date=current,
        tenant_code=tenant_code,
        project_code=project_code,
        amount=amount,
        write_db=write_db,
    )
    record = {
        "external_transaction_id": f"tau-demo-payment-{current:%Y%m%d}",
        "transaction_time": datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
        "value_date": current.isoformat(),
        "amount": amount,
        "currency": invoice["currency"],
        "payment_channel": "bank",
        "direction": "inbound",
        "counterparty_name": "Demo Quant Research",
        "reference_text": f"Payment for {invoice['invoice_code']}",
    }
    batch_code = f"tau-demo-payments-{current:%Y%m%d}"
    imported = import_payment_records(
        postgres_dsn,
        [record],
        batch_code=batch_code,
        source_type="demo",
        account_code="demo-bank-cny",
        statement_start=current,
        statement_end=current,
        currency=invoice["currency"],
        write_db=write_db,
    )
    matches = match_payments(postgres_dsn, batch_code=batch_code, write_db=write_db)
    return {"invoice": invoice, "import": imported, "matches": matches}


def ensure_tau_demo_invoice(
    postgres_dsn: str,
    *,
    as_of_date: str | date,
    tenant_code: str,
    project_code: str,
    amount: Decimal | int | float | str,
    write_db: bool = True,
) -> dict[str, Any]:
    current = _coerce_optional_date(as_of_date, "as_of_date")
    assert current is not None
    total = _amount(amount)
    invoice_code = f"inv-{tenant_code}-{project_code}-a_share_daily_core-tau-{current:%Y%m%d}"
    if not write_db:
        return {
            "invoice_code": invoice_code,
            "tenant_code": tenant_code,
            "project_code": project_code,
            "currency": "CNY",
            "total_amount": str(total),
            "paid_amount": "0.00000000",
            "outstanding_amount": str(total),
            "status": "issued",
        }
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            subscription = _fetch_demo_subscription(cursor, tenant_code, project_code)
            cursor.execute(
                """
                INSERT INTO qmeta.invoice AS inv (
                    invoice_code, tenant_id, project_id, subscription_id, plan_id, product_id,
                    period_start, period_end, invoice_date, due_date, currency, status,
                    subtotal_amount, discount_amount, tax_amount, total_amount, paid_amount,
                    outstanding_amount, issued_at, details
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, 'issued',
                    %s, 0, 0, %s, 0,
                    %s, now(), %s::jsonb
                )
                ON CONFLICT (invoice_code) DO NOTHING
                RETURNING *
                """,
                (
                    invoice_code,
                    subscription["tenant_id"],
                    subscription.get("project_id"),
                    subscription.get("subscription_id"),
                    subscription.get("plan_id"),
                    subscription.get("product_id"),
                    current,
                    current,
                    current,
                    current + timedelta(days=15),
                    subscription["currency"],
                    total,
                    total,
                    total,
                    _json({"source": "tau_payment_demo", "purpose": "payment_matching_acceptance"}),
                ),
            )
            inserted = cursor.fetchone()
            if inserted:
                invoice = dict(inserted)
                _insert_demo_invoice_line(cursor, invoice, total)
                _insert_demo_invoice_event(cursor, invoice, total)
            else:
                cursor.execute("SELECT * FROM qmeta.invoice WHERE invoice_code = %s", (invoice_code,))
                invoice = dict(cursor.fetchone())
            invoice["tenant_code"] = subscription["tenant_code"]
            invoice["project_code"] = subscription.get("project_code")
            invoice["product_code"] = subscription.get("product_code")
            return _public(invoice)


def format_tau_demo_report(payload: dict[str, Any]) -> str:
    invoice = payload.get("invoice") or {}
    imported = payload.get("import") or {}
    batch = imported.get("batch") or {}
    matches = payload.get("matches") or []
    lines = [
        (
            f"tau_demo invoice={invoice.get('invoice_code')} batch={batch.get('batch_code')} "
            f"transactions={batch.get('transaction_count')} matches={len(matches)}"
        )
    ]
    for match in matches:
        lines.append(
            f"match code={match.get('match_code')} status={match.get('status')} "
            f"matched_amount={match.get('matched_amount')} invoice_status={match.get('invoice_status')}"
        )
    return "\n".join(lines)


def format_payment_import(payload: dict[str, Any]) -> str:
    batch = payload.get("batch") or {}
    return (
        f"tau_import batch={batch.get('batch_code')} status={batch.get('status')} "
        f"transactions={batch.get('transaction_count')} total={batch.get('total_amount')}"
    )


def format_payment_matches(rows: list[dict[str, Any]]) -> str:
    lines = [f"tau_matches rows={len(rows)}"]
    for row in rows:
        lines.append(
            f"match={row.get('match_code')} status={row.get('status')} "
            f"matched_amount={row.get('matched_amount')} invoice_status={row.get('invoice_status')}"
        )
    return "\n".join(lines)


def _normalize_payment_record(row: dict[str, Any], *, currency: str, base_currency: str) -> dict[str, Any]:
    amount = _amount(row.get("amount"))
    if amount <= 0:
        raise QDataValidationError("payment amount must be greater than 0")
    row_currency = str(row.get("currency") or currency).upper()
    value_date = _coerce_optional_date(row.get("value_date") or _date_part(row.get("transaction_time")), "value_date") or date.today()
    transaction_time = _coerce_datetime(row.get("transaction_time"), value_date)
    fx_rate = _fx(row.get("fx_rate_to_base") or (1 if row_currency == base_currency else None))
    if fx_rate is None:
        raise QDataValidationError("fx_rate_to_base is required when currency differs from base_currency")
    external_id = _blank_to_none(row.get("external_transaction_id"))
    reference_text = _blank_to_none(row.get("reference_text") or row.get("memo") or row.get("remark"))
    transaction_code = _blank_to_none(row.get("transaction_code")) or _bounded_code(
        "tau-pay-" + _slug(external_id or f"{transaction_time.isoformat()}-{amount}-{reference_text or ''}"),
        220,
    )
    payment_channel = str(row.get("payment_channel") or "bank")
    _validate_enum(payment_channel, PAYMENT_CHANNELS, "payment_channel")
    direction = str(row.get("direction") or "inbound")
    if direction not in {"inbound", "outbound"}:
        raise QDataValidationError("direction must be one of: inbound, outbound")
    return {
        "transaction_code": transaction_code,
        "external_transaction_id": external_id,
        "payment_channel": payment_channel,
        "counterparty_name": _blank_to_none(row.get("counterparty_name")),
        "counterparty_account": _blank_to_none(row.get("counterparty_account")),
        "transaction_time": transaction_time,
        "value_date": value_date,
        "direction": direction,
        "currency": row_currency,
        "amount": amount,
        "base_currency": base_currency,
        "fx_rate_to_base": fx_rate,
        "base_amount": _amount(amount * fx_rate),
        "status": "imported",
        "reference_text": reference_text,
        "raw_payload": {key: str(value) for key, value in row.items()},
        "details": {"source": "tau_payment_record", "invoice_code_hint": extract_invoice_code(reference_text)},
    }


def _upsert_payment_batch(cursor, batch: dict[str, Any]) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO qmeta.payment_import_batch (
            batch_code, source_type, account_code, statement_start, statement_end,
            currency, status, transaction_count, matched_count, unmatched_count,
            total_amount, matched_amount, unmatched_amount, details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (batch_code) DO UPDATE SET
            source_type = EXCLUDED.source_type,
            account_code = EXCLUDED.account_code,
            statement_start = EXCLUDED.statement_start,
            statement_end = EXCLUDED.statement_end,
            currency = EXCLUDED.currency,
            transaction_count = EXCLUDED.transaction_count,
            total_amount = EXCLUDED.total_amount,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING *
        """,
        (
            batch["batch_code"],
            batch["source_type"],
            batch.get("account_code"),
            batch.get("statement_start"),
            batch.get("statement_end"),
            batch["currency"],
            batch["status"],
            batch["transaction_count"],
            batch["matched_count"],
            batch["unmatched_count"],
            batch["total_amount"],
            batch["matched_amount"],
            batch["unmatched_amount"],
            _json(batch.get("details") or {}),
        ),
    )
    return dict(cursor.fetchone())


def _upsert_payment_transaction(cursor, row: dict[str, Any], *, batch_id: int, source_type: str, provider: str) -> dict[str, Any]:
    cursor.execute(
        """
        INSERT INTO qmeta.payment_transaction (
            transaction_code, batch_id, payment_channel, external_transaction_id,
            counterparty_name, counterparty_account, transaction_time, value_date,
            direction, currency, amount, base_currency, fx_rate_to_base, base_amount,
            status, reference_text, raw_payload, details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'imported', %s, %s::jsonb, %s::jsonb)
        ON CONFLICT (transaction_code) DO UPDATE SET
            batch_id = EXCLUDED.batch_id,
            payment_channel = EXCLUDED.payment_channel,
            external_transaction_id = EXCLUDED.external_transaction_id,
            counterparty_name = EXCLUDED.counterparty_name,
            counterparty_account = EXCLUDED.counterparty_account,
            transaction_time = EXCLUDED.transaction_time,
            value_date = EXCLUDED.value_date,
            direction = EXCLUDED.direction,
            currency = EXCLUDED.currency,
            amount = EXCLUDED.amount,
            base_currency = EXCLUDED.base_currency,
            fx_rate_to_base = EXCLUDED.fx_rate_to_base,
            base_amount = EXCLUDED.base_amount,
            status = CASE WHEN payment_transaction.status IN ('matched', 'partially_matched', 'overpaid') THEN payment_transaction.status ELSE 'imported' END,
            reference_text = EXCLUDED.reference_text,
            raw_payload = EXCLUDED.raw_payload,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING *
        """,
        (
            row["transaction_code"],
            batch_id,
            row["payment_channel"],
            row.get("external_transaction_id"),
            row.get("counterparty_name"),
            row.get("counterparty_account"),
            row["transaction_time"],
            row["value_date"],
            row["direction"],
            row["currency"],
            row["amount"],
            row["base_currency"],
            row["fx_rate_to_base"],
            row["base_amount"],
            row.get("reference_text"),
            _json(row.get("raw_payload") or {}),
            _json({**(row.get("details") or {}), "source_type": source_type, "provider": provider}),
        ),
    )
    transaction = dict(cursor.fetchone())
    _write_ledger_for_payment(cursor, transaction)
    return transaction


def _fetch_matchable_transactions(cursor, *, batch_code: str | None, transaction_code: str | None) -> list[dict[str, Any]]:
    where = ["pt.direction = 'inbound'", "pt.status IN ('imported', 'unmatched', 'matched', 'partially_matched', 'overpaid')"]
    values: list[Any] = []
    if batch_code:
        where.append("pib.batch_code = %s")
        values.append(batch_code)
    if transaction_code:
        where.append("pt.transaction_code = %s")
        values.append(transaction_code)
    cursor.execute(
        f"""
        SELECT pt.*, pib.batch_code
        FROM qmeta.payment_transaction pt
        LEFT JOIN qmeta.payment_import_batch pib ON pib.batch_id = pt.batch_id
        WHERE {' AND '.join(where)}
        ORDER BY pt.value_date, pt.transaction_id
        FOR UPDATE OF pt
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _find_invoice_for_transaction(cursor, transaction: dict[str, Any]) -> dict[str, Any] | None:
    if transaction.get("invoice_id") is not None:
        cursor.execute(
            """
            SELECT i.*, t.tenant_code, p.project_code
            FROM qmeta.invoice i
            JOIN qmeta.tenant t ON t.tenant_id = i.tenant_id
            LEFT JOIN qmeta.project p ON p.project_id = i.project_id
            WHERE i.invoice_id = %s
            FOR UPDATE OF i
            """,
            (transaction["invoice_id"],),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
    invoice_code = extract_invoice_code(transaction.get("reference_text"))
    if invoice_code:
        cursor.execute(
            """
            SELECT i.*, t.tenant_code, p.project_code
            FROM qmeta.invoice i
            JOIN qmeta.tenant t ON t.tenant_id = i.tenant_id
            LEFT JOIN qmeta.project p ON p.project_id = i.project_id
            WHERE i.invoice_code = %s
            FOR UPDATE OF i
            """,
            (invoice_code,),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
    cursor.execute(
        """
        SELECT i.*, t.tenant_code, p.project_code
        FROM qmeta.invoice i
        JOIN qmeta.tenant t ON t.tenant_id = i.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = i.project_id
        WHERE i.currency = %s
          AND i.status IN ('issued', 'partially_paid', 'overdue')
          AND i.outstanding_amount > 0
          AND ABS(i.outstanding_amount - %s) <= 0.00000001
        ORDER BY i.due_date NULLS LAST, i.invoice_date, i.invoice_id
        LIMIT 1
        FOR UPDATE OF i
        """,
        (transaction["currency"], transaction["amount"]),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _find_existing_active_match(cursor, transaction: dict[str, Any], invoice: dict[str, Any]) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT *
        FROM qmeta.payment_invoice_match
        WHERE transaction_id = %s
          AND invoice_id = %s
          AND status IN ('matched', 'partial', 'overpaid')
        ORDER BY matched_at DESC, match_id DESC
        LIMIT 1
        """,
        (transaction["transaction_id"], invoice["invoice_id"]),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _upsert_invoice_match(cursor, transaction: dict[str, Any], invoice: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    match_code = _bounded_code(f"tau-match-{transaction['transaction_code']}-{invoice['invoice_code']}", 240)
    cursor.execute(
        """
        INSERT INTO qmeta.payment_invoice_match (
            match_code, transaction_id, invoice_id, tenant_id, project_id,
            match_type, status, currency, matched_amount, base_currency,
            fx_rate_to_base, base_matched_amount, unmatched_amount, match_score, details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (transaction_id, invoice_id) DO UPDATE SET
            match_type = EXCLUDED.match_type,
            status = EXCLUDED.status,
            matched_amount = EXCLUDED.matched_amount,
            base_matched_amount = EXCLUDED.base_matched_amount,
            unmatched_amount = EXCLUDED.unmatched_amount,
            match_score = EXCLUDED.match_score,
            details = EXCLUDED.details,
            matched_at = now(),
            updated_at = now()
        RETURNING *
        """,
        (
            match_code,
            transaction["transaction_id"],
            invoice["invoice_id"],
            invoice["tenant_id"],
            invoice.get("project_id"),
            decision["match_type"],
            decision["status"],
            transaction["currency"],
            decision["matched_amount"],
            transaction["base_currency"],
            transaction["fx_rate_to_base"],
            _amount(decision["matched_amount"] * transaction["fx_rate_to_base"]),
            decision["unmatched_amount"],
            decision["match_score"],
            _json(
                {
                    "source": "tau_payment_match",
                    "invoice_code": invoice["invoice_code"],
                    "transaction_code": transaction["transaction_code"],
                    "invoice_outstanding_before_match": str(invoice["outstanding_amount"]),
                }
            ),
        ),
    )
    return dict(cursor.fetchone())


def _update_transaction_after_match(cursor, transaction: dict[str, Any], invoice: dict[str, Any], decision: dict[str, Any]) -> None:
    status = {"matched": "matched", "partial": "partially_matched", "overpaid": "overpaid"}[decision["status"]]
    cursor.execute(
        """
        UPDATE qmeta.payment_transaction
        SET invoice_id = %s,
            tenant_id = %s,
            project_id = %s,
            status = %s,
            details = details || %s::jsonb,
            updated_at = now()
        WHERE transaction_id = %s
        """,
        (
            invoice["invoice_id"],
            invoice["tenant_id"],
            invoice.get("project_id"),
            status,
            _json({"latest_match_status": decision["status"], "matched_amount": str(decision["matched_amount"])}),
            transaction["transaction_id"],
        ),
    )


def _refresh_invoice_from_matches(cursor, invoice_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        WITH matched AS (
            SELECT COALESCE(SUM(matched_amount), 0) AS matched_amount
            FROM qmeta.payment_invoice_match
            WHERE invoice_id = %s
              AND status IN ('matched', 'partial', 'overpaid')
        )
        UPDATE qmeta.invoice i
        SET paid_amount = LEAST(i.total_amount, GREATEST(i.paid_amount, matched.matched_amount)),
            outstanding_amount = GREATEST(i.total_amount - LEAST(i.total_amount, GREATEST(i.paid_amount, matched.matched_amount)), 0),
            status = CASE
                WHEN i.total_amount > 0 AND LEAST(i.total_amount, GREATEST(i.paid_amount, matched.matched_amount)) >= i.total_amount THEN 'paid'
                WHEN LEAST(i.total_amount, GREATEST(i.paid_amount, matched.matched_amount)) > 0 THEN 'partially_paid'
                WHEN i.due_date IS NOT NULL AND i.due_date < current_date THEN 'overdue'
                ELSE 'issued'
            END,
            paid_at = CASE
                WHEN i.total_amount > 0 AND LEAST(i.total_amount, GREATEST(i.paid_amount, matched.matched_amount)) >= i.total_amount THEN COALESCE(i.paid_at, now())
                ELSE i.paid_at
            END,
            updated_at = now()
        FROM matched
        WHERE i.invoice_id = %s
        RETURNING i.*
        """,
        (invoice_id, invoice_id),
    )
    return dict(cursor.fetchone())


def _mark_transaction_unmatched(
    cursor,
    transaction: dict[str, Any],
    *,
    reason: str,
    invoice: dict[str, Any] | None = None,
    write_db: bool,
) -> dict[str, Any]:
    result = {
        "transaction_code": transaction["transaction_code"],
        "status": "unmatched",
        "reason": reason,
        "invoice_code": invoice.get("invoice_code") if invoice else None,
        "matched_amount": "0.00000000",
        "unmatched_amount": str(_amount(transaction["amount"])),
    }
    if not write_db:
        return result
    cursor.execute(
        """
        UPDATE qmeta.payment_transaction
        SET status = 'unmatched',
            details = details || %s::jsonb,
            updated_at = now()
        WHERE transaction_id = %s
        RETURNING *
        """,
        (_json({"unmatched_reason": reason}), transaction["transaction_id"]),
    )
    updated = dict(cursor.fetchone())
    _write_ledger_for_unmatched(cursor, updated, reason=reason)
    if updated.get("batch_id") is not None:
        _refresh_batch_summary(cursor, int(updated["batch_id"]))
    return _public({**updated, **result})


def _refresh_batch_summary(cursor, batch_id: int) -> None:
    cursor.execute(
        """
        WITH summary AS (
            SELECT
                COUNT(*) AS transaction_count,
                COUNT(*) FILTER (WHERE status IN ('matched', 'partially_matched', 'overpaid')) AS matched_count,
                COUNT(*) FILTER (WHERE status IN ('imported', 'unmatched')) AS unmatched_count,
                COALESCE(SUM(amount), 0) AS total_amount,
                COALESCE((
                    SELECT SUM(pim.matched_amount)
                    FROM qmeta.payment_invoice_match pim
                    JOIN qmeta.payment_transaction pt2 ON pt2.transaction_id = pim.transaction_id
                    WHERE pt2.batch_id = %s
                      AND pim.status IN ('matched', 'partial', 'overpaid')
                ), 0) AS matched_amount
            FROM qmeta.payment_transaction
            WHERE batch_id = %s
        )
        UPDATE qmeta.payment_import_batch b
        SET transaction_count = summary.transaction_count,
            matched_count = summary.matched_count,
            unmatched_count = summary.unmatched_count,
            total_amount = summary.total_amount,
            matched_amount = summary.matched_amount,
            unmatched_amount = GREATEST(summary.total_amount - summary.matched_amount, 0),
            status = CASE
                WHEN summary.transaction_count = 0 THEN 'imported'
                WHEN summary.unmatched_count = 0 THEN 'matched'
                WHEN summary.matched_count > 0 THEN 'partially_matched'
                ELSE 'imported'
            END,
            updated_at = now()
        FROM summary
        WHERE b.batch_id = %s
        """,
        (batch_id, batch_id, batch_id),
    )


def _write_invoice_event_for_match(cursor, invoice: dict[str, Any], transaction: dict[str, Any], match_row: dict[str, Any], decision: dict[str, Any]) -> None:
    event_type = "paid" if invoice["status"] == "paid" else "manual_note"
    event_code = _bounded_code(f"tau-invoice-{event_type}-{match_row['match_code']}", 220)
    cursor.execute(
        """
        INSERT INTO qmeta.invoice_event (
            invoice_id, event_code, event_type, status, message, details
        ) VALUES (%s, %s, %s, 'success', %s, %s::jsonb)
        ON CONFLICT (event_code) DO NOTHING
        """,
        (
            invoice["invoice_id"],
            event_code,
            event_type,
            f"Tau matched payment {transaction['transaction_code']} to invoice {invoice['invoice_code']}",
            _json({"match_code": match_row["match_code"], "matched_amount": str(decision["matched_amount"])}),
        ),
    )


def _write_ledger_for_payment(cursor, transaction: dict[str, Any]) -> None:
    entry_type = "payment_received" if transaction["direction"] == "inbound" else "refund"
    ledger_code = _bounded_code(f"tau-ledger-{entry_type}-{transaction['transaction_code']}", 240)
    cursor.execute(
        """
        INSERT INTO qmeta.revenue_ledger_entry (
            ledger_code, tenant_id, project_id, invoice_id, transaction_id,
            entry_date, entry_type, currency, debit_amount, credit_amount,
            balance_amount, base_currency, base_debit_amount, base_credit_amount,
            base_balance_amount, details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, 0, %s, %s, %s::jsonb)
        ON CONFLICT (ledger_code) DO UPDATE SET
            credit_amount = EXCLUDED.credit_amount,
            balance_amount = EXCLUDED.balance_amount,
            base_credit_amount = EXCLUDED.base_credit_amount,
            base_balance_amount = EXCLUDED.base_balance_amount,
            details = EXCLUDED.details,
            updated_at = now()
        """,
        (
            ledger_code,
            transaction.get("tenant_id"),
            transaction.get("project_id"),
            transaction.get("invoice_id"),
            transaction["transaction_id"],
            transaction["value_date"],
            entry_type,
            transaction["currency"],
            transaction["amount"],
            transaction["amount"],
            transaction["base_currency"],
            transaction["base_amount"],
            transaction["base_amount"],
            _json({"source": "tau_payment_import", "transaction_code": transaction["transaction_code"]}),
        ),
    )


def _write_ledger_for_match(cursor, transaction: dict[str, Any], invoice: dict[str, Any], match_row: dict[str, Any], decision: dict[str, Any]) -> None:
    ledger_code = _bounded_code(f"tau-ledger-payment-matched-{match_row['match_code']}", 240)
    cursor.execute(
        """
        INSERT INTO qmeta.revenue_ledger_entry (
            ledger_code, tenant_id, project_id, invoice_id, transaction_id, match_id,
            entry_date, entry_type, currency, debit_amount, credit_amount,
            balance_amount, base_currency, base_debit_amount, base_credit_amount,
            base_balance_amount, details
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'payment_matched', %s, %s, 0, %s, %s, %s, 0, %s, %s::jsonb)
        ON CONFLICT (ledger_code) DO UPDATE SET
            debit_amount = EXCLUDED.debit_amount,
            balance_amount = EXCLUDED.balance_amount,
            base_debit_amount = EXCLUDED.base_debit_amount,
            base_balance_amount = EXCLUDED.base_balance_amount,
            details = EXCLUDED.details,
            updated_at = now()
        """,
        (
            ledger_code,
            invoice["tenant_id"],
            invoice.get("project_id"),
            invoice["invoice_id"],
            transaction["transaction_id"],
            match_row["match_id"],
            transaction["value_date"],
            transaction["currency"],
            decision["matched_amount"],
            decision["matched_amount"],
            transaction["base_currency"],
            _amount(decision["matched_amount"] * transaction["fx_rate_to_base"]),
            _amount(decision["matched_amount"] * transaction["fx_rate_to_base"]),
            _json({"source": "tau_payment_match", "match_code": match_row["match_code"], "status": decision["status"]}),
        ),
    )


def _write_ledger_for_unmatched(cursor, transaction: dict[str, Any], *, reason: str) -> None:
    ledger_code = _bounded_code(f"tau-ledger-payment-unmatched-{transaction['transaction_code']}", 240)
    cursor.execute(
        """
        INSERT INTO qmeta.revenue_ledger_entry (
            ledger_code, tenant_id, project_id, invoice_id, transaction_id,
            entry_date, entry_type, currency, debit_amount, credit_amount,
            balance_amount, base_currency, base_debit_amount, base_credit_amount,
            base_balance_amount, details
        ) VALUES (%s, %s, %s, %s, %s, %s, 'payment_unmatched', %s, 0, 0, %s, %s, 0, 0, %s, %s::jsonb)
        ON CONFLICT (ledger_code) DO UPDATE SET
            balance_amount = EXCLUDED.balance_amount,
            base_balance_amount = EXCLUDED.base_balance_amount,
            details = EXCLUDED.details,
            updated_at = now()
        """,
        (
            ledger_code,
            transaction.get("tenant_id"),
            transaction.get("project_id"),
            transaction.get("invoice_id"),
            transaction["transaction_id"],
            transaction["value_date"],
            transaction["currency"],
            transaction["amount"],
            transaction["base_currency"],
            transaction["base_amount"],
            _json({"source": "tau_payment_match", "unmatched_reason": reason}),
        ),
    )


def _fetch_demo_subscription(cursor, tenant_code: str, project_code: str) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
            ps.subscription_id, ps.subscription_code, ps.tenant_id, ps.project_id,
            ps.plan_id, ps.product_id, t.tenant_code, p.project_code,
            pp.plan_code, pp.currency, dp.product_code
        FROM qmeta.product_subscription ps
        JOIN qmeta.tenant t ON t.tenant_id = ps.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = ps.project_id
        JOIN qmeta.pricing_plan pp ON pp.plan_id = ps.plan_id
        JOIN qmeta.data_product dp ON dp.product_id = ps.product_id
        WHERE ps.status = 'active'
          AND t.tenant_code = %s
          AND p.project_code = %s
        ORDER BY ps.subscription_id
        LIMIT 1
        """,
        (tenant_code, project_code),
    )
    row = cursor.fetchone()
    if not row:
        raise QDataValidationError(f"active subscription not found for {tenant_code}/{project_code}")
    return dict(row)


def _insert_demo_invoice_line(cursor, invoice: dict[str, Any], total: Decimal) -> None:
    line_code = _bounded_code(f"line-{invoice['invoice_code']}-tau-demo-adjustment-001", 220)
    cursor.execute(
        """
        INSERT INTO qmeta.invoice_line (
            invoice_id, line_code, product_id, pricing_rule_id, api_name, metric_name,
            period_start, period_end, quantity, unit_price, amount, request_count,
            row_count, cost_units, details
        ) VALUES (%s, %s, %s, NULL, 'tau-payment-demo', 'adjustment', %s, %s, 1, %s, %s, 0, 0, 0, %s::jsonb)
        ON CONFLICT (line_code) DO NOTHING
        """,
        (
            invoice["invoice_id"],
            line_code,
            invoice.get("product_id"),
            invoice["period_start"],
            invoice["period_end"],
            total,
            total,
            _json({"source": "tau_payment_demo"}),
        ),
    )


def _insert_demo_invoice_event(cursor, invoice: dict[str, Any], total: Decimal) -> None:
    event_code = _bounded_code(f"tau-generated-{invoice['invoice_code']}", 220)
    cursor.execute(
        """
        INSERT INTO qmeta.invoice_event (
            invoice_id, event_code, event_type, status, message, details
        ) VALUES (%s, %s, 'generated', 'success', %s, %s::jsonb)
        ON CONFLICT (event_code) DO NOTHING
        """,
        (
            invoice["invoice_id"],
            event_code,
            f"Generated Tau demo invoice {invoice['invoice_code']}",
            _json({"source": "tau_payment_demo", "total_amount": str(total)}),
        ),
    )


def _coerce_optional_date(value: str | date | None, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    return parse_date(value, field_name) if isinstance(value, str) else value


def _coerce_datetime(value: Any, fallback_date: date) -> datetime:
    if isinstance(value, datetime):
        return value
    if value not in (None, ""):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise QDataValidationError("transaction_time must use ISO datetime format") from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.combine(fallback_date, datetime.min.time(), tzinfo=timezone.utc)


def _date_part(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)[:10]


def _amount(value: Decimal | int | float | str | None) -> Decimal:
    if value in (None, ""):
        return Decimal("0").quantize(AMOUNT_QUANT)
    if isinstance(value, Decimal):
        return value.quantize(AMOUNT_QUANT)
    return Decimal(str(value)).quantize(AMOUNT_QUANT)


def _fx(value: Decimal | int | float | str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value.quantize(FX_QUANT)
    return Decimal(str(value)).quantize(FX_QUANT)


def _blank_to_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _bounded_code(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{value[:max_length - 13]}-{digest}"


def _slug(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_.-]+", "-", value.strip())
    return re.sub(r"-+", "-", text).strip("-").lower()


def _validate_enum(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        raise QDataValidationError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")


def _json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return normalize_rows([{key: _stringify(value) for key, value in row.items()}])[0]


def _stringify(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _stringify(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify(item) for item in value]
    return value


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Tau payments") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
