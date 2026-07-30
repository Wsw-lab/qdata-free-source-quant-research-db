#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone


def main() -> int:
    payload = _load_payload()
    if os.getenv("ALPHA2_SCRIPT_FORCE_FAIL") == "1":
        print(
            json.dumps(
                {
                    "status": "forced_failure",
                    "sandbox": True,
                    "executor_code": payload.get("executor_code"),
                    "action_code": payload.get("action_code"),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": "ok",
                "sandbox": True,
                "external_side_effect": False,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "executor_code": payload.get("executor_code"),
                "executor_type": payload.get("executor_type"),
                "action_code": payload.get("action_code"),
                "action_type": payload.get("action_type"),
                "operation": payload.get("operation"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _load_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return value if isinstance(value, dict) else {"payload": value}


if __name__ == "__main__":
    raise SystemExit(main())
