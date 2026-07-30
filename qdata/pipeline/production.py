from __future__ import annotations

from collections import Counter
from datetime import timedelta
from decimal import Decimal
from typing import Any

from qdata.backend_utils import parse_date
from qdata.exceptions import QDataValidationError
from qdata.pipeline.models import PipelineJobConfig, PipelineRunResult


def resolve_production_window(
    store,
    config: PipelineJobConfig,
    start_date: str | None,
    end_date: str,
    from_watermark: bool = False,
    watermark_lookback_days: int = 0,
) -> tuple[str, str]:
    if watermark_lookback_days < 0:
        raise QDataValidationError("watermark_lookback_days must be greater than or equal to 0")
    end = parse_date(end_date, "end_date")
    if not from_watermark:
        if not start_date:
            raise QDataValidationError("start_date is required unless from_watermark is enabled")
        return start_date, end.isoformat()

    job = store.ensure_job(config)
    watermark = store.get_watermark(job.job_id)
    if watermark and watermark.get("last_success_trade_date"):
        last_success = parse_date(str(watermark["last_success_trade_date"]), "last_success_trade_date")
        start = last_success + timedelta(days=1)
        if watermark_lookback_days:
            start -= timedelta(days=watermark_lookback_days)
        if start_date:
            start = max(start, parse_date(start_date, "start_date"))
        return start.isoformat(), end.isoformat()
    if start_date:
        return start_date, end.isoformat()
    raise QDataValidationError("from_watermark requires an existing success watermark or a bootstrap start_date")


def summarize_results(results: list[PipelineRunResult]) -> dict[str, Any]:
    statuses = Counter(result.status for result in results)
    completeness_values = [
        float(result.completeness_rate)
        for result in results
        if result.completeness_rate is not None
    ]
    return {
        "total": len(results),
        "statuses": dict(sorted(statuses.items())),
        "missing_total": sum(result.missing_count for result in results),
        "worst_completeness": min(completeness_values) if completeness_values else None,
        "repair_queued": sum(1 for result in results if result.repair_status == "queued"),
        "failed_dates": [result.trade_date for result in results if result.status == "failed"],
        "partial_dates": [result.trade_date for result in results if result.status == "partial_success"],
    }


def format_results_report(job_code: str, start_date: str, end_date: str, results: list[PipelineRunResult]) -> str:
    summary = summarize_results(results)
    lines = [
        f"production_report job={job_code} window={start_date}..{end_date}",
        "status_counts "
        + (" ".join(f"{key}={value}" for key, value in summary["statuses"].items()) or "none")
        + f" total={summary['total']}",
        f"missing_total={summary['missing_total']} repair_queued={summary['repair_queued']} "
        f"worst_completeness={_ratio(summary['worst_completeness'])}",
    ]
    for result in results:
        lines.append(
            f"date={result.trade_date} status={result.status} rows={result.row_count} "
            f"expected={result.expected_row_count} missing={result.missing_count} "
            f"completeness={_ratio(result.completeness_rate)} repair={result.repair_status}"
        )
    return "\n".join(lines)


def format_store_report(report: dict[str, Any]) -> str:
    runs = report.get("runs") or []
    statuses = Counter(row["status"] for row in runs)
    missing_total = sum(int(row.get("missing_count") or 0) for row in runs)
    completeness_values = [
        float(row["completeness_rate"])
        for row in runs
        if row.get("completeness_rate") is not None
    ]
    lines = [
        f"production_report job={report['job_code']} window={report['start_date']}..{report['end_date']}",
        "status_counts "
        + (" ".join(f"{key}={value}" for key, value in sorted(statuses.items())) or "none")
        + f" total={len(runs)}",
        f"missing_total={missing_total} worst_completeness={_ratio(min(completeness_values) if completeness_values else None)}",
    ]
    for row in report.get("repairs") or []:
        lines.append(f"repair reason={row['reason']} status={row['status']} count={row['count']}")
    for row in runs:
        lines.append(
            f"date={row['trade_date']} status={row['status']} rows={row['row_count']} "
            f"expected={row['expected_row_count']} missing={row['missing_count']} "
            f"completeness={_ratio(row['completeness_rate'])} repair={row['repair_status']}"
        )
    return "\n".join(lines)


def _ratio(value) -> str:
    if value is None:
        return "NA"
    if isinstance(value, Decimal):
        value = float(value)
    return f"{float(value):.4f}"
