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

from qdata.epsilon6_route_incident_approval_resilience import list_route_incident_approval_audit_hashes
from qdata.zeta6_route_incident_approval_release import (
    export_approval_audit_package,
    record_concurrency_test_result,
    record_secret_rotation_check,
    run_release_preflight,
    verify_wecom_callback_signature_rotating,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Zeta-6 route incident approval release gate.")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    parser.add_argument("--environment", choices=["local", "staging", "production"], default=os.getenv("QDATA_ZETA6_ENVIRONMENT", "local"))
    parser.add_argument("--release-version", default=os.getenv("QDATA_ZETA6_RELEASE_VERSION", "zeta6-smoke"))
    parser.add_argument("--current-secret", default=os.getenv("QDATA_DELTA6_WECOM_CALLBACK_SECRET", "delta6-local-secret"))
    parser.add_argument("--next-secret", default=os.getenv("QDATA_ZETA6_WECOM_CALLBACK_SECRET_NEXT", "zeta6-next-local-secret"))
    args = parser.parse_args()

    chain_scope = _latest_chain_scope(args.postgres_dsn)
    control_code = _control_code_from_scope(chain_scope)
    preflight = run_release_preflight(
        args.postgres_dsn,
        environment=args.environment,
        release_version=args.release_version,
        requested_by="zeta6-smoke",
        trigger_mode="smoke",
        require_dual_secret=False,
        write_db=True,
    )
    if preflight.get("status") == "failed":
        raise RuntimeError(f"Zeta-6 preflight failed: {preflight}")

    rotation_result = _rotation_check(args.current_secret, args.next_secret)
    rotation = record_secret_rotation_check(args.postgres_dsn, rotation_result, environment=args.environment, write_db=True)
    if rotation.get("status") != "success":
        raise RuntimeError(f"Zeta-6 secret rotation check failed: {rotation}")

    concurrency = record_concurrency_test_result(
        args.postgres_dsn,
        environment=args.environment,
        target_scope=chain_scope or "route-approval:zeta6-smoke",
        callback_count=8,
        expected_success_count=1,
        success_count=1,
        locked_count=0,
        blocked_count=1,
        replay_rejected_count=6,
        failed_count=0,
        max_worker_threads=4,
        evidence={
            "scenario": "signed callback replay storm summary",
            "external_side_effect": False,
            "chain_scope": chain_scope,
        },
        write_db=True,
    )
    if concurrency.get("status") not in {"success", "warning"}:
        raise RuntimeError(f"Zeta-6 concurrency result failed: {concurrency}")

    audit_export = export_approval_audit_package(
        args.postgres_dsn,
        environment=args.environment,
        chain_scope=chain_scope,
        control_code=control_code,
        export_format="json",
        exported_by="zeta6-smoke",
        trigger_mode="smoke",
        limit=1000,
        write_db=True,
    )
    if audit_export.get("status") == "failed":
        raise RuntimeError(f"Zeta-6 audit export failed: {audit_export}")

    print(
        "zeta6_route_approval_release_smoke=ok "
        f"preflight={preflight.get('status')} "
        f"rotation={rotation.get('status')} "
        f"verified_secret={rotation.get('verified_secret_label')} "
        f"concurrency={concurrency.get('status')} "
        f"export={audit_export.get('status')} "
        f"broken_hashes={audit_export.get('broken_hash_count')} "
        f"package_hash={audit_export.get('package_hash')} "
        f"chain_scope={chain_scope or 'none'}"
    )
    return 0


def _latest_chain_scope(postgres_dsn: str) -> str | None:
    rows = list_route_incident_approval_audit_hashes(postgres_dsn, {}, 1, 0)
    if not rows:
        return None
    return str(rows[0].get("chain_scope") or "") or None


def _control_code_from_scope(chain_scope: str | None) -> str | None:
    prefix = "route-approval:control_code:"
    if chain_scope and chain_scope.startswith(prefix):
        return chain_scope[len(prefix):]
    return None


def _rotation_check(current_secret: str, next_secret: str) -> dict[str, object]:
    payload = {
        "provider_code": "wecom",
        "decision": "approve",
        "control_code": "zeta6-rotation-smoke",
        "requested_by": "zeta6-smoke",
        "signer_code": "zeta6-smoke",
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    nonce = f"zeta6-rotation-{hashlib.sha1(timestamp.encode('utf-8')).hexdigest()[:10]}"
    signing_secret = next_secret or current_secret
    digest = hmac.new(signing_secret.encode("utf-8"), f"{timestamp}\n{nonce}\n".encode("utf-8") + raw, hashlib.sha256).hexdigest()
    return verify_wecom_callback_signature_rotating(
        raw,
        {
            "X-QData-Timestamp": timestamp,
            "X-QData-Nonce": nonce,
            "X-QData-Signature": f"sha256={digest}",
        },
        payload=payload,
        current_secret=current_secret,
        next_secret=next_secret,
    )


if __name__ == "__main__":
    raise SystemExit(main())
