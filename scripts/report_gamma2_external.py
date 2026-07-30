#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.gamma2_external import (
    format_gamma2_rows,
    list_automation_channel_profiles,
    list_automation_channel_validations,
    list_automation_secret_rotations,
    rollback_gamma2_secret_rotation,
    run_gamma2_profile_validation,
    run_gamma2_secret_rotation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Gamma-2 provider profile validation and secret rotation drills.")
    parser.add_argument(
        "--resource",
        choices=["validate", "rotate", "rollback", "profiles", "validations", "rotations"],
        default="profiles",
    )
    parser.add_argument("--profile-code", default="")
    parser.add_argument("--channel-code", default="")
    parser.add_argument("--provider-code", default="")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--readiness-status", default="")
    parser.add_argument("--action-code", default="")
    parser.add_argument("--validation-code", default="")
    parser.add_argument("--validation-type", choices=["dry_run_dispatch", "live_dispatch", "secret_rotation", "rollback_drill"], default="")
    parser.add_argument("--trigger-mode", default="")
    parser.add_argument("--target-secret-ref", default="")
    parser.add_argument("--secret-ref", default="")
    parser.add_argument("--next-secret-ref", default="")
    parser.add_argument("--rotation-code", default="")
    parser.add_argument("--rotation-type", choices=["manual", "scheduled", "emergency", "drill"], default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--requested-by", default="")
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--runbook-code", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--rolled-back-by", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--apply-rotation", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    if args.resource == "validate":
        payload = run_gamma2_profile_validation(
            args.postgres_dsn,
            profile_code=args.profile_code,
            action_code=args.action_code,
            requested_by=args.requested_by or "gamma2",
            validation_type=args.validation_type or "dry_run_dispatch",
            trigger_mode=args.trigger_mode or "manual",
            allow_external=args.allow_external,
            force=args.force,
            target_secret_ref=args.target_secret_ref or None,
        )
        _emit(payload, format_gamma2_rows("validations", [payload]), args.json)
        return 0
    if args.resource == "rotate":
        payload = run_gamma2_secret_rotation(
            args.postgres_dsn,
            secret_ref=args.secret_ref,
            next_secret_ref=args.next_secret_ref,
            requested_by=args.requested_by or args.approved_by or "gamma2",
            reason=args.reason or "Gamma-2 secret rotation drill",
            environment=args.environment or "local",
            rotation_type=args.rotation_type or "manual",
            profile_code=args.profile_code or None,
            action_code=args.action_code or None,
            allow_external=args.allow_external,
            apply_rotation=args.apply_rotation,
            force=args.force,
        )
        _emit(payload, format_gamma2_rows("rotations", [payload]), args.json)
        return 0
    if args.resource == "rollback":
        payload = rollback_gamma2_secret_rotation(
            args.postgres_dsn,
            rotation_code=args.rotation_code,
            rolled_back_by=args.rolled_back_by or args.requested_by or "gamma2",
            reason=args.reason or "Gamma-2 rotation rollback drill",
        )
        _emit(payload, format_gamma2_rows("rotations", [payload]), args.json)
        return 0

    params = _params(args)
    if args.resource == "profiles":
        rows = list_automation_channel_profiles(args.postgres_dsn, params, args.limit, args.offset)
    elif args.resource == "validations":
        rows = list_automation_channel_validations(args.postgres_dsn, params, args.limit, args.offset)
    else:
        rows = list_automation_secret_rotations(args.postgres_dsn, params, args.limit, args.offset)
    payload = {"resource": f"gamma2.{args.resource}", "row_count": len(rows), "rows": rows}
    _emit(payload, format_gamma2_rows(args.resource, rows), args.json)
    return 0


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {"limit": [str(args.limit)], "offset": [str(args.offset)]}
    for name in (
        "profile_code",
        "channel_code",
        "provider_code",
        "environment",
        "readiness_status",
        "action_code",
        "validation_code",
        "validation_type",
        "trigger_mode",
        "target_secret_ref",
        "secret_ref",
        "next_secret_ref",
        "rotation_code",
        "rotation_type",
        "status",
        "requested_by",
        "approved_by",
        "owner",
        "runbook_code",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [value]
    return params


def _emit(payload: dict, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
