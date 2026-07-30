from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import csv
import io
import json
from typing import Any

from qdata.exceptions import QDataValidationError


def format_response(payload: dict[str, Any], response_format: str) -> tuple[bytes, str]:
    rows = payload.get("data", [])
    if response_format == "json":
        return to_json_bytes(payload), "application/json; charset=utf-8"
    if response_format == "csv":
        return to_csv_bytes(rows), "text/csv; charset=utf-8"
    if response_format == "arrow":
        return to_arrow_bytes(rows), "application/vnd.apache.arrow.stream"
    raise QDataValidationError("format must be one of: json, csv, arrow")


def to_json_bytes(payload: dict[str, Any], status_code: int | None = None) -> bytes:
    body = dict(payload)
    if status_code is not None:
        body.setdefault("status_code", status_code)
    return json.dumps(body, ensure_ascii=False, default=_json_default).encode("utf-8")


def to_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO()
    fieldnames = _fieldnames(rows)
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})
    return output.getvalue().encode("utf-8")


def to_arrow_bytes(rows: list[dict[str, Any]]) -> bytes:
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise QDataValidationError("pyarrow is required for format=arrow. Install qdata[export].") from exc
    sink = pa.BufferOutputStream()
    table = pa.Table.from_pylist(rows)
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                names.append(key)
    return names


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
