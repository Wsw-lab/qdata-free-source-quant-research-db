from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from qdata.exceptions import QDataValidationError


def response(
    rows: list[dict[str, Any]],
    data_versions: list[str],
    query_mode: str,
    asof_time: str | None = None,
    data_version: str | None = None,
) -> dict[str, Any]:
    return {
        "request_id": f"req_{uuid4().hex[:12]}",
        "status": "success",
        "data": rows,
        "meta": {
            "query_mode": query_mode,
            "data_versions": data_versions,
            "row_count": len(rows),
            "asof_time": asof_time,
            "data_version": data_version,
        },
        "errors": [],
    }


def project(rows: list[dict[str, Any]], fields: list[str] | None) -> list[dict[str, Any]]:
    if not fields:
        return [dict(row) for row in rows]
    seen: set[str] = set()
    ordered_fields = [field for field in fields if not (field in seen or seen.add(field))]
    return [{field: row.get(field) for field in ordered_fields} for row in rows]


def parse_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise QDataValidationError(f"{field_name} must use YYYY-MM-DD format") from exc


def date_range(start_date: str, end_date: str) -> tuple[date, date]:
    start = parse_date(start_date, "start_date")
    end = parse_date(end_date, "end_date")
    if start > end:
        raise QDataValidationError("start_date must be less than or equal to end_date")
    return start, end


def validate_enum(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise QDataValidationError(f"{field_name} must be one of: {allowed_text}")


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            normalized[key] = value.isoformat()
        else:
            normalized[key] = value
    return normalized


def normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_row(row) for row in rows]


def ensure_required_dates(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    if not start_date or not end_date:
        raise QDataValidationError("start_date and end_date are required")
    date_range(start_date, end_date)
    return start_date, end_date


def unique(items: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
