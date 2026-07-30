#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.phi_strategy import (
    format_strategy_evaluation,
    list_strategy_decisions,
    list_strategy_escalations,
    list_strategy_runs,
    list_strategy_signals,
    run_phi_strategy,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and report Phi unified strategy decisions.")
    parser.add_argument(
        "--resource",
        choices=("run-all", "runs", "signals", "decisions", "escalations"),
        default="run-all",
    )
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--trigger-mode", default="manual")
    parser.add_argument("--run-code", default="")
    parser.add_argument("--policy-code", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--severity", default="")
    parser.add_argument("--subject-code", default="")
    parser.add_argument("--signal-type", default="")
    parser.add_argument("--decision-type", default="")
    parser.add_argument("--action", default="")
    parser.add_argument("--escalation-type", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--metric-name", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "run-all":
        payload = run_phi_strategy(
            args.postgres_dsn,
            as_of_date=args.as_of_date or None,
            environment=args.environment,
            trigger_mode=args.trigger_mode,
            write_db=not args.dry_run,
        )
        _emit(payload, format_strategy_evaluation(payload), args.json)
        return 0

    params = _params(args)
    if args.resource == "runs":
        rows = list_strategy_runs(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "signals":
        rows = list_strategy_signals(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "decisions":
        rows = list_strategy_decisions(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_strategy_escalations(args.postgres_dsn, params, args.limit, args.offset)
    payload = {"resource": f"phi.{args.resource}", "rows": rows, "row_count": len(rows)}
    _emit(payload, _format_rows(args.resource, rows), args.json)
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for name in (
        "run_code",
        "policy_code",
        "domain",
        "status",
        "severity",
        "subject_code",
        "signal_type",
        "decision_type",
        "action",
        "escalation_type",
        "owner",
        "metric_name",
        "environment",
        "trigger_mode",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


def _format_rows(resource: str, rows: list[dict]) -> str:
    lines = [f"phi_{resource} rows={len(rows)}"]
    for row in rows:
        if resource == "runs":
            keys = ["run_code", "run_date", "environment", "status", "highest_severity", "signal_count", "decision_count", "escalation_count"]
        elif resource == "signals":
            keys = ["signal_code", "domain", "subject_code", "signal_type", "severity", "metric_name", "metric_value", "message"]
        elif resource == "decisions":
            keys = ["decision_code", "domain", "subject_code", "action", "status", "severity", "priority_score", "reason"]
        else:
            keys = ["event_code", "escalation_type", "severity", "status", "owner", "message"]
        lines.append(" ".join(f"{key}={row[key]}" for key in keys if row.get(key) not in (None, "", [], {})))
    return "\n".join(lines)


def _emit(payload, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
