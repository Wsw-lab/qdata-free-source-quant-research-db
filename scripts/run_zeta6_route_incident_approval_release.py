#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.zeta6_route_incident_approval_release import (
    export_approval_audit_package,
    format_zeta6_rows,
    list_route_incident_approval_audit_exports,
    list_route_incident_approval_concurrency_tests,
    list_route_incident_approval_release_preflights,
    list_route_incident_approval_secret_rotations,
    record_secret_rotation_check,
    run_release_preflight,
    verify_wecom_callback_signature_rotating,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Zeta-6 route incident approval release utilities.")
    parser.add_argument(
        "--resource",
        choices=[
            "preflight",
            "secret-rotation-check",
            "audit-export",
            "release-preflights",
            "secret-rotations",
            "concurrency-tests",
            "audit-exports",
        ],
        default="preflight",
    )
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--environment", choices=["local", "staging", "production"], default=os.getenv("QDATA_ZETA6_ENVIRONMENT", "local"))
    parser.add_argument("--release-version", default=os.getenv("QDATA_ZETA6_RELEASE_VERSION", "zeta6-local"))
    parser.add_argument("--requested-by", default=os.getenv("QDATA_ZETA6_REQUESTED_BY", "zeta6-cli"))
    parser.add_argument("--trigger-mode", choices=["manual", "worker", "smoke", "release"], default="manual")
    parser.add_argument("--require-dual-secret", action="store_true", default=os.getenv("QDATA_ZETA6_REQUIRE_DUAL_SECRET", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--current-secret", default=os.getenv("QDATA_DELTA6_WECOM_CALLBACK_SECRET", "delta6-local-secret"))
    parser.add_argument("--next-secret", default=os.getenv("QDATA_ZETA6_WECOM_CALLBACK_SECRET_NEXT", ""))
    parser.add_argument("--nonce", default="")
    parser.add_argument("--payload", default="")
    parser.add_argument("--chain-scope", default="")
    parser.add_argument("--control-code", default="")
    parser.add_argument("--approval-code", default="")
    parser.add_argument("--batch-code", default="")
    parser.add_argument("--export-format", choices=["json", "markdown", "csv"], default="json")
    parser.add_argument("--preflight-code", default="")
    parser.add_argument("--rotation-code", default="")
    parser.add_argument("--test-code", default="")
    parser.add_argument("--export-code", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--rotation-phase", default="")
    parser.add_argument("--verified-secret-label", default="")
    parser.add_argument("--package-hash", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.resource == "preflight":
        payload = run_release_preflight(
            args.postgres_dsn,
            environment=args.environment,
            release_version=args.release_version,
            requested_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            require_dual_secret=args.require_dual_secret,
            write_db=True,
        )
        _print_payload(payload, args.json)
        return 0

    if args.resource == "secret-rotation-check":
        body = _payload(args.payload)
        raw = json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        nonce = args.nonce or f"zeta6-rotation-{timestamp}"
        signing_secret = args.next_secret or args.current_secret
        digest = hmac.new(signing_secret.encode("utf-8"), f"{timestamp}\n{nonce}\n".encode("utf-8") + raw, hashlib.sha256).hexdigest()
        result = verify_wecom_callback_signature_rotating(
            raw,
            {
                "X-QData-Timestamp": timestamp,
                "X-QData-Nonce": nonce,
                "X-QData-Signature": f"sha256={digest}",
            },
            payload=body,
            current_secret=args.current_secret,
            next_secret=args.next_secret,
        )
        payload = record_secret_rotation_check(args.postgres_dsn, result, environment=args.environment, write_db=True)
        _print_payload(payload, args.json)
        return 0

    if args.resource == "audit-export":
        payload = export_approval_audit_package(
            args.postgres_dsn,
            environment=args.environment,
            chain_scope=args.chain_scope or None,
            control_code=args.control_code or None,
            approval_code=args.approval_code or None,
            batch_code=args.batch_code or None,
            export_format=args.export_format,
            exported_by=args.requested_by,
            trigger_mode=args.trigger_mode,
            limit=args.limit,
            write_db=True,
        )
        _print_payload(payload, args.json)
        return 0

    params = _params(args)
    if args.resource == "release-preflights":
        rows = list_route_incident_approval_release_preflights(args.postgres_dsn, params, args.limit, args.offset)
        resource_name = "release_preflights"
    elif args.resource == "secret-rotations":
        rows = list_route_incident_approval_secret_rotations(args.postgres_dsn, params, args.limit, args.offset)
        resource_name = "secret_rotations"
    elif args.resource == "concurrency-tests":
        rows = list_route_incident_approval_concurrency_tests(args.postgres_dsn, params, args.limit, args.offset)
        resource_name = "concurrency_tests"
    else:
        rows = list_route_incident_approval_audit_exports(args.postgres_dsn, params, args.limit, args.offset)
        resource_name = "audit_exports"

    if args.json:
        print(json.dumps({"resource": resource_name, "row_count": len(rows), "data": rows}, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(format_zeta6_rows(resource_name, rows))
    return 0


def _payload(raw: str) -> dict[str, object]:
    if raw:
        return json.loads(raw)
    return {
        "provider_code": "wecom",
        "decision": "approve",
        "control_code": "zeta6-rotation-drill",
        "requested_by": "zeta6-cli",
        "signer_code": "zeta6-cli",
    }


def _params(args: argparse.Namespace) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for name in (
        "preflight_code",
        "rotation_code",
        "test_code",
        "export_code",
        "status",
        "rotation_phase",
        "verified_secret_label",
        "nonce",
        "chain_scope",
        "control_code",
        "approval_code",
        "batch_code",
        "package_hash",
        "start_date",
        "end_date",
    ):
        value = getattr(args, name)
        if value:
            params[name] = [str(value)]
    return params


def _print_payload(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
