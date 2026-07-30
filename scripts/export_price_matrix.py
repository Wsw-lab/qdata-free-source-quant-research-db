#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import csv
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata import Client
from qdata.exceptions import QDataValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a date x symbol price matrix as CSV or Parquet.")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--universe", default="")
    parser.add_argument("--tradable", action="store_true")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--field", default="close")
    parser.add_argument("--adjust", choices=["none", "forward", "backward"], default="none")
    parser.add_argument("--output", required=True)
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--clickhouse-dsn", default=os.getenv("QDATA_CLICKHOUSE_DSN", "http://qdata:qdata@localhost:18123/default"))
    args = parser.parse_args()

    with Client(
        backend="sql",
        postgres_dsn=args.postgres_dsn,
        clickhouse_dsn=args.clickhouse_dsn,
        default_format="records",
    ) as client:
        symbols = _resolve_symbols(client, args)
        rows = client.get_price(
            symbols=symbols,
            start_date=args.start_date,
            end_date=args.end_date,
            adjust=args.adjust,
            fields=[args.field],
        )
    matrix = _to_matrix(rows, symbols, args.field)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".parquet":
        _write_parquet(output, matrix)
        output_format = "parquet"
    else:
        _write_csv(output, matrix, symbols)
        output_format = "csv"
    _write_audit(
        postgres_dsn=args.postgres_dsn,
        field_name=args.field,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=symbols,
        row_count=len(matrix),
        output=output,
        output_format=output_format,
        adjust=args.adjust,
    )
    print(f"matrix_output={output} rows={len(matrix)} symbols={len(symbols)} field={args.field}")
    return 0


def _resolve_symbols(client: Client, args) -> list[str]:
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if args.tradable:
        rows = client.get_tradable_universe(
            asof_date=args.end_date,
            symbols=symbols or None,
            universe=args.universe or None,
        )
        return [row["symbol"] for row in rows]
    if args.universe:
        rows = client.get_universe(args.universe, args.end_date)
        return [row["symbol"] for row in rows]
    if not symbols:
        raise SystemExit("--symbols, --universe or --tradable is required")
    return symbols


def _to_matrix(rows: list[dict], symbols: list[str], field: str) -> list[dict]:
    by_date: dict[str, dict] = {}
    for row in rows:
        item = by_date.setdefault(row["trade_date"], {"trade_date": row["trade_date"]})
        item[row["symbol"]] = row.get(field)
    return [
        {"trade_date": trade_date, **{symbol: by_date[trade_date].get(symbol) for symbol in symbols}}
        for trade_date in sorted(by_date)
    ]


def _write_csv(path: Path, matrix: list[dict], symbols: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["trade_date"] + symbols)
        writer.writeheader()
        writer.writerows(matrix)


def _write_parquet(path: Path, matrix: list[dict]) -> None:
    try:
        import pandas as pd
    except ImportError as exc:
        raise QDataValidationError("pandas is required for parquet export") from exc
    pd.DataFrame(matrix).to_parquet(path, index=False)


def _write_audit(
    postgres_dsn: str,
    field_name: str,
    start_date: str,
    end_date: str,
    symbols: list[str],
    row_count: int,
    output: Path,
    output_format: str,
    adjust: str,
) -> None:
    try:
        import json
        import psycopg
    except ImportError:
        return
    with psycopg.connect(postgres_dsn) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qmeta.matrix_export_audit (
                    dataset_code, field_name, start_date, end_date, symbol_count,
                    row_count, output_uri, output_format, request_summary
                ) VALUES ('daily_bar', %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    field_name,
                    start_date,
                    end_date,
                    len(symbols),
                    row_count,
                    str(output),
                    output_format,
                    json.dumps({"symbols": symbols, "adjust": adjust}, ensure_ascii=False),
                ),
            )


if __name__ == "__main__":
    raise SystemExit(main())
