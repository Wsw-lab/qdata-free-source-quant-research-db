from __future__ import annotations

from datetime import date, timedelta
import json
from typing import Any

from qdata.backend_utils import date_range, normalize_rows
from qdata.exceptions import QDataValidationError
from qdata.iota import authorize_dataset_access


def evaluate_access_boundary(
    postgres_dsn: str,
    *,
    dataset_code: str,
    tenant_code: str | None = None,
    project_code: str | None = None,
    principal_code: str | None = None,
    token_name: str | None = None,
    api_name: str = "manual",
    access_level: str = "read",
    fields: list[str] | None = None,
    request_id: str | None = None,
    write_audit: bool = False,
) -> dict[str, Any]:
    context = _resolve_access_context(postgres_dsn, tenant_code, project_code, principal_code, token_name)
    decision = authorize_dataset_access(
        postgres_dsn,
        tenant_id=context.get("tenant_id"),
        project_id=context.get("project_id"),
        principal_id=context.get("principal_id"),
        token_id=context.get("token_id"),
        dataset_code=dataset_code,
        access_level=access_level,
        fields=fields,
        api_name=api_name,
        request_id=request_id,
        write_audit=write_audit,
        audit_details={"source": "chi_evaluate_access"},
    )
    return {
        **{key: value for key, value in context.items() if not key.endswith("_id")},
        "dataset_code": dataset_code,
        "api_name": api_name,
        "allowed": decision.allowed,
        "decision": "allow" if decision.allowed else "deny",
        "required_access_level": access_level,
        "effective_access_level": decision.effective_access_level,
        "effective_scope": decision.effective_scope,
        "access_id": decision.access_id,
        "field_allowlist": decision.field_allowlist,
        "field_denylist": decision.field_denylist,
        "denied_fields": decision.denied_fields or [],
        "reason": decision.reason or "allowed",
    }


def collect_project_governance_snapshots(
    postgres_dsn: str,
    *,
    snapshot_date: str | None = None,
    tenant_code: str | None = None,
    project_code: str | None = None,
    write_db: bool = False,
    write_actions: bool = False,
) -> list[dict[str, Any]]:
    as_of = _parse_date(snapshot_date)
    start_date = as_of - timedelta(days=6)
    rows: list[dict[str, Any]] = []
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for project in _fetch_projects(cursor, tenant_code, project_code):
                metrics = _fetch_project_metrics(cursor, int(project["project_id"]), start_date, as_of)
                status, risk_score, recommended_action, details = score_project_governance(metrics)
                snapshot = {
                    **project,
                    **metrics,
                    "snapshot_date": as_of.isoformat(),
                    "snapshot_code": _snapshot_code(project["tenant_code"], project["project_code"], as_of),
                    "status": status,
                    "risk_score": risk_score,
                    "recommended_action": recommended_action,
                    "details": details,
                }
                if write_db:
                    snapshot["snapshot_id"] = _upsert_project_snapshot(cursor, snapshot)
                if write_db and write_actions and status in {"warning", "critical"}:
                    action = _upsert_governance_action(cursor, snapshot)
                    snapshot["governance_action_code"] = action["action_code"]
                    snapshot["governance_action_status"] = action["status"]
                rows.append(snapshot)
    return normalize_rows(rows)


def score_project_governance(metrics: dict[str, Any]) -> tuple[str, float, str, dict[str, Any]]:
    request_count = int(metrics.get("request_count_7d") or 0)
    failed_count = int(metrics.get("failed_count_7d") or 0)
    denied_count = int(metrics.get("denied_access_7d_count") or 0)
    open_budget_alert_count = int(metrics.get("open_budget_alert_count") or 0)
    unpaid_invoice_count = int(metrics.get("unpaid_invoice_count") or 0)
    overdue_invoice_count = int(metrics.get("overdue_invoice_count") or 0)
    open_governance_action_count = int(metrics.get("open_governance_action_count") or 0)
    budget_status = metrics.get("budget_status")
    budget_usage_pct = _float(metrics.get("budget_usage_pct"))
    budget_usage_threshold_pct = budget_usage_pct
    if budget_usage_threshold_pct is not None and budget_usage_threshold_pct <= 5:
        budget_usage_threshold_pct *= 100
    error_rate = failed_count / request_count if request_count else 0.0

    risk_score = 0.0
    risk_score += min(30.0, error_rate * 100)
    risk_score += min(30.0, denied_count * 6.0)
    if budget_status in {"blocked", "exceeded"} or (
        budget_usage_threshold_pct is not None and budget_usage_threshold_pct >= 100
    ):
        risk_score += 35.0
    elif budget_status in {"warning", "near_limit"} or (
        budget_usage_threshold_pct is not None and budget_usage_threshold_pct >= 80
    ):
        risk_score += 15.0
    risk_score += min(25.0, overdue_invoice_count * 20.0 + unpaid_invoice_count * 5.0)
    risk_score += min(10.0, open_budget_alert_count * 6.0 + open_governance_action_count * 2.0)
    risk_score = round(min(100.0, risk_score), 4)

    if budget_status in {"blocked", "exceeded"} or overdue_invoice_count > 0 or denied_count >= 5 or risk_score >= 70:
        status = "critical"
    elif denied_count > 0 or open_budget_alert_count > 0 or failed_count > 0 or unpaid_invoice_count > 0 or risk_score >= 25:
        status = "warning"
    else:
        status = "healthy"

    if (
        budget_status in {"blocked", "exceeded"}
        or open_budget_alert_count > 0
        or (budget_usage_threshold_pct is not None and budget_usage_threshold_pct >= 80)
    ):
        recommended_action = "review_budget"
    elif denied_count > 0:
        recommended_action = "review_access_policy"
    elif error_rate >= 0.10:
        recommended_action = "rotate_token"
    elif unpaid_invoice_count > 0 or overdue_invoice_count > 0:
        recommended_action = "contact_owner"
    else:
        recommended_action = "monitor"

    details = {
        "error_rate_7d": round(error_rate, 8),
        "risk_drivers": {
            "failed_count_7d": failed_count,
            "denied_access_7d_count": denied_count,
            "budget_status": budget_status,
            "budget_usage_pct": budget_usage_pct,
            "budget_usage_threshold_pct": budget_usage_threshold_pct,
            "open_budget_alert_count": open_budget_alert_count,
            "unpaid_invoice_count": unpaid_invoice_count,
            "overdue_invoice_count": overdue_invoice_count,
            "open_governance_action_count": open_governance_action_count,
        },
    }
    return status, risk_score, recommended_action, details


def list_access_decisions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("principal_code", "pr.principal_code"),
            ("token_name", "tok.token_name"),
            ("dataset_code", "ada.dataset_code"),
            ("api_name", "ada.api_name"),
            ("decision", "ada.decision"),
            ("effective_scope", "ada.effective_scope"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "ada.evaluated_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ada.access_decision_id, ada.decision_code, ada.request_id,
            t.tenant_code, p.project_code, pr.principal_code, tok.token_name,
            ada.api_name, ada.dataset_code, ada.decision,
            ada.required_access_level, ada.effective_access_level,
            ada.effective_scope, ada.requested_fields, ada.denied_fields,
            ada.reason, ada.evaluated_at, ada.details
        FROM qmeta.access_decision_audit ada
        LEFT JOIN qmeta.tenant t ON t.tenant_id = ada.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = ada.project_id
        LEFT JOIN qmeta.principal pr ON pr.principal_id = ada.principal_id
        LEFT JOIN qmeta.api_token tok ON tok.token_id = ada.token_id
        {where}
        ORDER BY ada.evaluated_at DESC, ada.access_decision_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_project_governance(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("snapshot_code", "pgs.snapshot_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("status", "pgs.status"),
            ("recommended_action", "pgs.recommended_action"),
        ],
    )
    as_of_date = _param(params, "as_of_date")
    if as_of_date:
        date_range(as_of_date, as_of_date)
        where, values = _append_where(where, values, "pgs.snapshot_date = %s", as_of_date)
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            pgs.snapshot_id, pgs.snapshot_code, pgs.snapshot_date,
            t.tenant_code, p.project_code, p.project_name, pgs.status,
            pgs.active_principal_count, pgs.active_token_count,
            pgs.dataset_policy_count, pgs.request_count_7d,
            pgs.failed_count_7d, pgs.error_rate_7d, pgs.cost_units_7d,
            pgs.denied_access_7d_count, pgs.budget_status,
            pgs.budget_usage_pct, pgs.open_budget_alert_count,
            pgs.unpaid_invoice_count, pgs.overdue_invoice_count,
            pgs.open_governance_action_count, pgs.risk_score,
            pgs.recommended_action, pgs.details, pgs.created_at, pgs.updated_at
        FROM qmeta.project_governance_snapshot pgs
        JOIN qmeta.tenant t ON t.tenant_id = pgs.tenant_id
        JOIN qmeta.project p ON p.project_id = pgs.project_id
        {where}
        ORDER BY pgs.snapshot_date DESC, pgs.status DESC, pgs.risk_score DESC, t.tenant_code, p.project_code
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def list_governance_actions(postgres_dsn: str | None, params: dict[str, list[str]], limit: int, offset: int) -> list[dict[str, Any]]:
    where, values = _where_equal(
        params,
        [
            ("action_code", "ga.action_code"),
            ("tenant_code", "t.tenant_code"),
            ("project_code", "p.project_code"),
            ("principal_code", "pr.principal_code"),
            ("token_name", "tok.token_name"),
            ("dataset_code", "dc.dataset_code"),
            ("action_type", "ga.action_type"),
            ("severity", "ga.severity"),
            ("status", "ga.status"),
            ("owner", "ga.owner"),
        ],
    )
    where, values = _append_date_filter(where, values, params, "ga.created_at")
    return _fetch_rows(
        postgres_dsn,
        f"""
        SELECT
            ga.action_id, ga.action_code, t.tenant_code, p.project_code,
            pr.principal_code, tok.token_name, dc.dataset_code,
            pgs.snapshot_code, ga.action_type, ga.severity, ga.status,
            ga.owner, ga.reason, ga.due_at, ga.created_at, ga.resolved_at,
            ga.updated_at, ga.details
        FROM qmeta.governance_action ga
        LEFT JOIN qmeta.tenant t ON t.tenant_id = ga.tenant_id
        LEFT JOIN qmeta.project p ON p.project_id = ga.project_id
        LEFT JOIN qmeta.principal pr ON pr.principal_id = ga.principal_id
        LEFT JOIN qmeta.api_token tok ON tok.token_id = ga.token_id
        LEFT JOIN qmeta.dataset_catalog dc ON dc.dataset_id = ga.dataset_id
        LEFT JOIN qmeta.project_governance_snapshot pgs ON pgs.snapshot_id = ga.snapshot_id
        {where}
        ORDER BY ga.status, ga.severity DESC, ga.updated_at DESC, ga.action_id DESC
        LIMIT %s OFFSET %s
        """,
        values + [limit, offset],
    )


def format_chi_report(resource: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"chi resource={resource} rows={len(rows)}"]
    for row in rows:
        keys = _report_keys(resource, row)
        bits = [f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})]
        lines.append(" ".join(bits[:14]))
    return "\n".join(lines)


def _fetch_projects(cursor: Any, tenant_code: str | None, project_code: str | None) -> list[dict[str, Any]]:
    where, values = _where_equal(
        {"tenant_code": [tenant_code] if tenant_code else [], "project_code": [project_code] if project_code else []},
        [("tenant_code", "t.tenant_code"), ("project_code", "p.project_code")],
    )
    if where:
        where = f"{where} AND p.status = 'active'"
    else:
        where = "WHERE p.status = 'active'"
    cursor.execute(
        f"""
        SELECT
            t.tenant_id, t.tenant_code, p.project_id, p.project_code,
            p.project_name, p.status AS project_status, COALESCE(p.owner, t.owner) AS owner
        FROM qmeta.project p
        JOIN qmeta.tenant t ON t.tenant_id = p.tenant_id
        {where}
        ORDER BY t.tenant_code, p.project_code
        """,
        tuple(values),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_project_metrics(cursor: Any, project_id: int, start_date: date, end_date: date) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT
            (SELECT COUNT(DISTINCT pm.principal_id)
             FROM qmeta.project_member pm
             JOIN qmeta.principal pr ON pr.principal_id = pm.principal_id
             WHERE pm.project_id = %s AND pm.status = 'active' AND pr.status = 'active') AS active_principal_count,
            (SELECT COUNT(*) FROM qmeta.api_token tok WHERE tok.project_id = %s AND tok.is_active = TRUE) AS active_token_count,
            (SELECT COUNT(*) FROM qmeta.dataset_access_policy dap WHERE dap.project_id = %s AND dap.status = 'active') AS dataset_policy_count,
            (SELECT COUNT(*) FROM qmeta.api_request_audit ara WHERE ara.project_id = %s AND ara.started_at::date BETWEEN %s AND %s) AS request_count_7d,
            (SELECT COUNT(*) FROM qmeta.api_request_audit ara WHERE ara.project_id = %s AND ara.started_at::date BETWEEN %s AND %s AND ara.status = 'failed') AS failed_count_7d,
            (SELECT COALESCE(SUM(ara.cost_units), 0) FROM qmeta.api_request_audit ara WHERE ara.project_id = %s AND ara.started_at::date BETWEEN %s AND %s) AS cost_units_7d,
            (SELECT COUNT(*) FROM qmeta.access_decision_audit ada WHERE ada.project_id = %s AND ada.evaluated_at::date BETWEEN %s AND %s AND ada.decision = 'deny') AS denied_access_7d_count,
            (SELECT bus.status FROM qmeta.budget_usage_snapshot bus JOIN qmeta.budget_policy bp ON bp.budget_id = bus.budget_id WHERE bp.project_id = %s ORDER BY bus.period_end DESC, bus.updated_at DESC LIMIT 1) AS budget_status,
            (SELECT bus.usage_pct FROM qmeta.budget_usage_snapshot bus JOIN qmeta.budget_policy bp ON bp.budget_id = bus.budget_id WHERE bp.project_id = %s ORDER BY bus.period_end DESC, bus.updated_at DESC LIMIT 1) AS budget_usage_pct,
            (SELECT COUNT(*) FROM qmeta.budget_alert ba JOIN qmeta.budget_policy bp ON bp.budget_id = ba.budget_id WHERE bp.project_id = %s AND ba.status = 'open') AS open_budget_alert_count,
            (SELECT COUNT(*) FROM qmeta.invoice i WHERE i.project_id = %s AND i.status IN ('issued', 'partially_paid', 'overdue') AND i.outstanding_amount > 0) AS unpaid_invoice_count,
            (SELECT COUNT(*) FROM qmeta.invoice i WHERE i.project_id = %s AND (i.status = 'overdue' OR (i.status IN ('issued', 'partially_paid') AND i.due_date < %s AND i.outstanding_amount > 0))) AS overdue_invoice_count,
            (SELECT COUNT(*) FROM qmeta.governance_action ga WHERE ga.project_id = %s AND ga.status IN ('open', 'in_progress')) AS open_governance_action_count
        """,
        (
            project_id,
            project_id,
            project_id,
            project_id,
            start_date,
            end_date,
            project_id,
            start_date,
            end_date,
            project_id,
            start_date,
            end_date,
            project_id,
            start_date,
            end_date,
            project_id,
            project_id,
            project_id,
            project_id,
            project_id,
            end_date,
            project_id,
        ),
    )
    row = dict(cursor.fetchone())
    request_count = int(row.get("request_count_7d") or 0)
    failed_count = int(row.get("failed_count_7d") or 0)
    row["error_rate_7d"] = round(failed_count / request_count, 8) if request_count else 0
    return row


def _upsert_project_snapshot(cursor: Any, snapshot: dict[str, Any]) -> int:
    cursor.execute(
        """
        INSERT INTO qmeta.project_governance_snapshot (
            snapshot_code, snapshot_date, tenant_id, project_id, status,
            active_principal_count, active_token_count, dataset_policy_count,
            request_count_7d, failed_count_7d, error_rate_7d, cost_units_7d,
            denied_access_7d_count, budget_status, budget_usage_pct,
            open_budget_alert_count, unpaid_invoice_count, overdue_invoice_count,
            open_governance_action_count, risk_score, recommended_action, details
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
        )
        ON CONFLICT (snapshot_date, project_id) DO UPDATE SET
            snapshot_code = EXCLUDED.snapshot_code,
            status = EXCLUDED.status,
            active_principal_count = EXCLUDED.active_principal_count,
            active_token_count = EXCLUDED.active_token_count,
            dataset_policy_count = EXCLUDED.dataset_policy_count,
            request_count_7d = EXCLUDED.request_count_7d,
            failed_count_7d = EXCLUDED.failed_count_7d,
            error_rate_7d = EXCLUDED.error_rate_7d,
            cost_units_7d = EXCLUDED.cost_units_7d,
            denied_access_7d_count = EXCLUDED.denied_access_7d_count,
            budget_status = EXCLUDED.budget_status,
            budget_usage_pct = EXCLUDED.budget_usage_pct,
            open_budget_alert_count = EXCLUDED.open_budget_alert_count,
            unpaid_invoice_count = EXCLUDED.unpaid_invoice_count,
            overdue_invoice_count = EXCLUDED.overdue_invoice_count,
            open_governance_action_count = EXCLUDED.open_governance_action_count,
            risk_score = EXCLUDED.risk_score,
            recommended_action = EXCLUDED.recommended_action,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING snapshot_id
        """,
        (
            snapshot["snapshot_code"],
            snapshot["snapshot_date"],
            snapshot["tenant_id"],
            snapshot["project_id"],
            snapshot["status"],
            snapshot["active_principal_count"],
            snapshot["active_token_count"],
            snapshot["dataset_policy_count"],
            snapshot["request_count_7d"],
            snapshot["failed_count_7d"],
            snapshot["error_rate_7d"],
            snapshot["cost_units_7d"],
            snapshot["denied_access_7d_count"],
            snapshot.get("budget_status"),
            snapshot.get("budget_usage_pct"),
            snapshot["open_budget_alert_count"],
            snapshot["unpaid_invoice_count"],
            snapshot["overdue_invoice_count"],
            snapshot["open_governance_action_count"],
            snapshot["risk_score"],
            snapshot["recommended_action"],
            _json(snapshot["details"]),
        ),
    )
    return int(cursor.fetchone()["snapshot_id"])


def _upsert_governance_action(cursor: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    action_type = snapshot["recommended_action"]
    severity = "high" if snapshot["status"] == "critical" else "medium"
    action_code = f"chi-action-{snapshot['tenant_code']}-{snapshot['project_code']}-{snapshot['snapshot_date'].replace('-', '')}-{action_type}"
    reason = (
        f"project {snapshot['tenant_code']}/{snapshot['project_code']} governance status "
        f"{snapshot['status']} risk={snapshot['risk_score']}"
    )
    cursor.execute(
        """
        INSERT INTO qmeta.governance_action (
            action_code, tenant_id, project_id, snapshot_id, action_type,
            severity, status, owner, reason, details
        ) VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, %s, %s::jsonb)
        ON CONFLICT (action_code) DO UPDATE SET
            snapshot_id = EXCLUDED.snapshot_id,
            severity = EXCLUDED.severity,
            owner = EXCLUDED.owner,
            reason = EXCLUDED.reason,
            details = EXCLUDED.details,
            updated_at = now()
        RETURNING action_code, status
        """,
        (
            action_code,
            snapshot["tenant_id"],
            snapshot["project_id"],
            snapshot.get("snapshot_id"),
            action_type,
            severity,
            snapshot.get("owner") or "platform-governance",
            reason,
            _json({"snapshot_code": snapshot["snapshot_code"], "risk_drivers": snapshot["details"].get("risk_drivers", {})}),
        ),
    )
    return dict(cursor.fetchone())


def _resolve_access_context(
    postgres_dsn: str,
    tenant_code: str | None,
    project_code: str | None,
    principal_code: str | None,
    token_name: str | None,
) -> dict[str, Any]:
    if not any([tenant_code, project_code, principal_code, token_name]):
        raise QDataValidationError("at least one of tenant_code, project_code, principal_code or token_name is required")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            context: dict[str, Any] = {
                "tenant_code": tenant_code,
                "project_code": project_code,
                "principal_code": principal_code,
                "token_name": token_name,
                "tenant_id": None,
                "project_id": None,
                "principal_id": None,
                "token_id": None,
            }
            if tenant_code:
                cursor.execute("SELECT tenant_id, tenant_code FROM qmeta.tenant WHERE tenant_code = %s", (tenant_code,))
                row = cursor.fetchone()
                if not row:
                    raise QDataValidationError(f"tenant not found: {tenant_code}")
                context["tenant_id"] = row["tenant_id"]
                context["tenant_code"] = row["tenant_code"]
            if project_code:
                if context["tenant_id"]:
                    cursor.execute("SELECT project_id, project_code FROM qmeta.project WHERE tenant_id = %s AND project_code = %s", (context["tenant_id"], project_code))
                else:
                    cursor.execute("SELECT project_id, project_code, tenant_id FROM qmeta.project WHERE project_code = %s ORDER BY project_id LIMIT 1", (project_code,))
                row = cursor.fetchone()
                if not row:
                    raise QDataValidationError(f"project not found: {project_code}")
                context["project_id"] = row["project_id"]
                context["project_code"] = row["project_code"]
                context["tenant_id"] = context["tenant_id"] or row.get("tenant_id")
            if principal_code:
                if context["tenant_id"]:
                    cursor.execute("SELECT principal_id, principal_code FROM qmeta.principal WHERE tenant_id = %s AND principal_code = %s", (context["tenant_id"], principal_code))
                else:
                    cursor.execute("SELECT principal_id, principal_code, tenant_id FROM qmeta.principal WHERE principal_code = %s ORDER BY principal_id LIMIT 1", (principal_code,))
                row = cursor.fetchone()
                if not row:
                    raise QDataValidationError(f"principal not found: {principal_code}")
                context["principal_id"] = row["principal_id"]
                context["principal_code"] = row["principal_code"]
                context["tenant_id"] = context["tenant_id"] or row.get("tenant_id")
            if token_name:
                cursor.execute(
                    """
                    SELECT token_id, token_name, tenant_id, project_id, principal_id
                    FROM qmeta.api_token
                    WHERE token_name = %s
                    ORDER BY is_active DESC, token_id DESC
                    LIMIT 1
                    """,
                    (token_name,),
                )
                row = cursor.fetchone()
                if not row:
                    raise QDataValidationError(f"token not found: {token_name}")
                context["token_id"] = row["token_id"]
                context["token_name"] = row["token_name"]
                context["tenant_id"] = context["tenant_id"] or row.get("tenant_id")
                context["project_id"] = context["project_id"] or row.get("project_id")
                context["principal_id"] = context["principal_id"] or row.get("principal_id")
            return context


def _fetch_rows(postgres_dsn: str | None, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    if not postgres_dsn:
        raise QDataValidationError("postgres_dsn is required for Chi governance queries")
    with _connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return normalize_rows([dict(row) for row in cursor.fetchall()])


def _where_equal(params: dict[str, list[str]], fields: list[tuple[str, str]], *, include_where: bool = True) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for param_name, column_name in fields:
        value = _param(params, param_name)
        if value in (None, ""):
            continue
        clauses.append(f"{column_name} = %s")
        values.append(value)
    if not clauses:
        return "", values
    prefix = "WHERE " if include_where else ""
    return prefix + " AND ".join(clauses), values


def _append_where(where: str, values: list[Any], clause: str, value: Any) -> tuple[str, list[Any]]:
    if where:
        where = f"{where} AND {clause}"
    else:
        where = f"WHERE {clause}"
    return where, values + [value]


def _append_date_filter(where: str, values: list[Any], params: dict[str, list[str]], column_name: str) -> tuple[str, list[Any]]:
    start_date = _param(params, "start_date")
    end_date = _param(params, "end_date")
    if start_date and end_date:
        date_range(start_date, end_date)
        clause = f"{column_name}::date BETWEEN %s AND %s"
        values = values + [start_date, end_date]
    elif start_date:
        date_range(start_date, start_date)
        clause = f"{column_name}::date >= %s"
        values = values + [start_date]
    elif end_date:
        date_range(end_date, end_date)
        clause = f"{column_name}::date <= %s"
        values = values + [end_date]
    else:
        return where, values
    return (f"{where} AND {clause}" if where else f"WHERE {clause}"), values


def _report_keys(resource: str, row: dict[str, Any]) -> list[str]:
    preferred = {
        "evaluate-access": [
            "tenant_code",
            "project_code",
            "principal_code",
            "token_name",
            "dataset_code",
            "api_name",
            "decision",
            "effective_scope",
            "effective_access_level",
            "reason",
        ],
        "project-governance": [
            "snapshot_code",
            "tenant_code",
            "project_code",
            "snapshot_date",
            "status",
            "risk_score",
            "recommended_action",
            "request_count_7d",
            "denied_access_7d_count",
            "budget_status",
            "budget_usage_pct",
            "open_budget_alert_count",
        ],
        "access-audit": [
            "decision_code",
            "tenant_code",
            "project_code",
            "principal_code",
            "token_name",
            "api_name",
            "dataset_code",
            "decision",
            "effective_scope",
            "reason",
            "evaluated_at",
        ],
        "governance-actions": [
            "action_code",
            "tenant_code",
            "project_code",
            "action_type",
            "severity",
            "status",
            "owner",
            "reason",
        ],
    }.get(resource, [])
    return [key for key in preferred if key in row] + [key for key in row if key not in preferred]


def _snapshot_code(tenant_code: str, project_code: str, snapshot_date: date) -> str:
    return f"chi-gov-{tenant_code}-{project_code}-{snapshot_date:%Y%m%d}"


def _parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    date_range(value, value)
    return date.fromisoformat(value)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[-1]


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)


def _connect(postgres_dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise QDataValidationError("psycopg is required for Chi governance") from exc
    return psycopg.connect(postgres_dsn, row_factory=dict_row)
