#!/usr/bin/env python3
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import hashlib
import hmac
import json
import os
import sys
import threading
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.gamma2_external import (
    list_automation_channel_profiles,
    list_automation_channel_validations,
    list_automation_secret_rotations,
    rollback_gamma2_secret_rotation,
    run_gamma2_profile_validation,
    run_gamma2_secret_rotation,
)


class _SignedWebhookHandler(BaseHTTPRequestHandler):
    server_version = "QDataGamma2Smoke/1.0"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        expected = getattr(self.server, "expected_secret", "")
        signature = self.headers.get("X-QData-Signature", "")
        expected_signature = _signature(body, expected) if expected else ""
        if not expected or not hmac.compare_digest(signature, expected_signature):
            self._send_json(401, {"status": "failed", "reason": "signature_mismatch"})
            return
        self.server.call_count += 1
        payload = {
            "status": "ok",
            "path": self.path,
            "provider": self.path.rsplit("/", 1)[-1],
            "call_count": self.server.call_count,
            "signed": True,
            "body_sha256": hashlib.sha256(body).hexdigest()[:12],
        }
        self._send_json(200, payload)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Gamma-2 profile validation, secret rotation, and rollback.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18102)
    parser.add_argument("--profile-code", default="gamma2-local-feishu-profile")
    parser.add_argument("--action-code", default="omega-smoke-retry-action")
    parser.add_argument("--requested-by", default="gamma2-smoke")
    parser.add_argument("--secret-ref", default="gamma2-local-hmac-current")
    parser.add_argument("--next-secret-ref", default="gamma2-local-hmac-next")
    parser.add_argument("--current-secret-env", default="QDATA_GAMMA2_HMAC_SECRET_CURRENT")
    parser.add_argument("--next-secret-env", default="QDATA_GAMMA2_HMAC_SECRET_NEXT")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    os.environ.setdefault(args.current_secret_env, "gamma2-current-secret")
    os.environ.setdefault(args.next_secret_env, "gamma2-next-secret")

    current_validation = _with_server(args.host, args.port, os.environ[args.current_secret_env], lambda: run_gamma2_profile_validation(
        args.postgres_dsn,
        profile_code=args.profile_code,
        action_code=args.action_code,
        requested_by=args.requested_by,
        validation_type="dry_run_dispatch",
        trigger_mode="smoke",
        allow_external=True,
        force=True,
    ))
    _assert_status("current_validation", current_validation.get("status"), "success")

    rotation = _with_server(args.host, args.port, os.environ[args.next_secret_env], lambda: run_gamma2_secret_rotation(
        args.postgres_dsn,
        secret_ref=args.secret_ref,
        next_secret_ref=args.next_secret_ref,
        requested_by=args.requested_by,
        reason="Gamma-2 smoke rotation",
        environment="local",
        rotation_type="drill",
        profile_code=args.profile_code,
        action_code=args.action_code,
        allow_external=True,
        apply_rotation=True,
        force=True,
    ))
    _assert_status("rotation", rotation.get("status"), "applied")

    rollback = rollback_gamma2_secret_rotation(
        args.postgres_dsn,
        rotation_code=str(rotation["rotation_code"]),
        rolled_back_by=args.requested_by,
        reason="Gamma-2 smoke rollback",
    )
    _assert_status("rollback", rollback.get("status"), "rolled_back")

    post_rollback_validation = _with_server(args.host, args.port, os.environ[args.current_secret_env], lambda: run_gamma2_profile_validation(
        args.postgres_dsn,
        profile_code=args.profile_code,
        action_code=args.action_code,
        requested_by=args.requested_by,
        validation_type="rollback_drill",
        trigger_mode="smoke",
        allow_external=True,
        force=True,
    ))
    _assert_status("post_rollback_validation", post_rollback_validation.get("status"), "success")

    params: dict[str, list[str]] = {"environment": ["local"]}
    profiles = list_automation_channel_profiles(args.postgres_dsn, params, 100, 0)
    validations = list_automation_channel_validations(args.postgres_dsn, params, 100, 0)
    rotations = list_automation_secret_rotations(args.postgres_dsn, params, 100, 0)
    ready_profiles = sum(1 for row in profiles if row.get("readiness_status") in {"dry_run_ready", "live_ready"})
    print(
        " ".join(
            [
                "gamma2_smoke=ok",
                f"profiles={len(profiles)}",
                f"ready_profiles={ready_profiles}",
                f"validations={len(validations)}",
                f"rotations={len(rotations)}",
                f"current_validation={current_validation['status']}",
                f"rotation={rotation['status']}",
                f"rollback={rollback['status']}",
                f"post_rollback_validation={post_rollback_validation['status']}",
            ]
        )
    )
    return 0


def _with_server(host: str, port: int, expected_secret: str, callback):
    server = ThreadingHTTPServer((host, port), _SignedWebhookHandler)
    server.expected_secret = expected_secret
    server.call_count = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return callback()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _signature(body: bytes, secret_value: str) -> str:
    digest = hmac.new(secret_value.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _assert_status(label: str, actual: object, expected: str) -> None:
    if actual != expected:
        raise SystemExit(f"{label}=failed expected={expected} actual={actual}")


if __name__ == "__main__":
    raise SystemExit(main())
