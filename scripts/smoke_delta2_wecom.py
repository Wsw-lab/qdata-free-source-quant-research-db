#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdata.delta2_wecom import DEFAULT_PROFILE_CODE, run_delta2_wecom_live_validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Delta-2 WeCom live validation.")
    parser.add_argument("--profile-code", default=DEFAULT_PROFILE_CODE)
    parser.add_argument("--requested-by", default="delta2-smoke")
    parser.add_argument("--title", default="QData Delta-2 企业微信测试")
    parser.add_argument("--message", default="这是一条来自 QData Delta-2 的企业微信 live validation 测试消息。")
    parser.add_argument("--action-code", default="omega-smoke-retry-action")
    parser.add_argument("--webhook-env", default="QDATA_DELTA2_WECOM_WEBHOOK_URL")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--postgres-dsn", default=os.getenv("QDATA_POSTGRES_DSN", "postgresql://qdata:qdata@localhost:15432/qdata"))
    args = parser.parse_args()

    webhook_present = bool(os.getenv(args.webhook_env))
    if args.require_live and not webhook_present:
        raise SystemExit(f"delta2_wecom_smoke=failed reason=missing_env env={args.webhook_env}")
    allow_external = args.allow_external and webhook_present
    receipt = run_delta2_wecom_live_validation(
        args.postgres_dsn,
        profile_code=args.profile_code,
        requested_by=args.requested_by,
        title=args.title,
        message=args.message,
        action_code=args.action_code,
        trigger_mode="smoke",
        message_type="markdown",
        allow_external=allow_external,
        force=True,
    )
    if webhook_present and args.allow_external and receipt.get("status") != "success":
        raise SystemExit(
            f"delta2_wecom_smoke=failed status={receipt.get('status')} "
            f"provider_errcode={receipt.get('provider_errcode')} error={receipt.get('error_message')}"
        )
    mode = "live" if allow_external else "blocked"
    print(
        " ".join(
            [
                "delta2_wecom_smoke=ok",
                f"mode={mode}",
                f"status={receipt.get('status')}",
                f"receipt_code={receipt.get('receipt_code')}",
                f"validation_code={receipt.get('validation_code')}",
                f"provider_errcode={receipt.get('provider_errcode')}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
