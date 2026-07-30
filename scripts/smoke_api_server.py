#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test a running qdata REST API server.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--token", default="")
    parser.add_argument("--symbols", default="600519.SH,000001.SZ")
    parser.add_argument("--start-date", default="2024-01-04")
    parser.add_argument("--end-date", default="2024-01-04")
    parser.add_argument("--asof-date", default="")
    args = parser.parse_args()

    asof_date = args.asof_date or args.end_date
    calls = [
        ("health", "/health", {"format": "json"}),
        ("price", "/price", {"symbols": args.symbols, "start_date": args.start_date, "end_date": args.end_date}),
        ("constraints", "/constraints", {"symbols": args.symbols, "start_date": args.start_date, "end_date": args.end_date}),
        ("tradable", "/tradable-universe", {"symbols": args.symbols, "asof_date": asof_date}),
        ("matrix_csv", "/matrix", {"symbols": args.symbols, "start_date": args.start_date, "end_date": args.end_date, "field": "close", "format": "csv"}),
    ]
    for label, path, query in calls:
        body, content_type = _get(args.base_url, path, query, args.token)
        if content_type.startswith("application/json"):
            payload = json.loads(body)
            row_count = payload.get("meta", {}).get("row_count", len(payload.get("data", [])))
            print(f"{label}=ok rows={row_count}")
        else:
            lines = [line for line in body.splitlines() if line.strip()]
            print(f"{label}=ok lines={len(lines)}")
    return 0


def _get(base_url: str, path: str, query: dict[str, str], token: str) -> tuple[str, str]:
    url = f"{base_url.rstrip('/')}{path}?{urlencode(query)}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8"), response.headers.get("Content-Type", "")


if __name__ == "__main__":
    raise SystemExit(main())
