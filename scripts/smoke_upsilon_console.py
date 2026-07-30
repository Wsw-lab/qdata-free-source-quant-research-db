#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


REQUIRED_MARKERS = [
    "QData Upsilon Ops Console",
    "QData Kappa Ops Console",
    "data-upsilon-controls",
    "data-view-button=\"runtime\"",
    "data-view-button=\"payments\"",
    "data-view-button=\"governance\"",
    "data-view-button=\"strategy\"",
    "Access Decisions",
    "Project Governance",
    "Governance Actions",
    "Automation Runs",
    "Automation Actions",
    "Automation Approvals",
    "Automation Attempts",
    "Automation Rollbacks",
    "Automation Executors",
    "Automation Allowlists",
    "Automation Secrets",
    "Automation Channels",
    "Automation Dispatches",
    "Automation Runbooks",
    "Automation Channel Profiles",
    "Automation Channel Validations",
    "Automation Secret Rotations",
    "Automation Live Receipts",
    "Vendor Primary Promotions",
    "Vendor Primary Promotion Results",
    "Vendor Post Promotion Monitors",
    "Vendor Post Promotion Results",
    "Vendor Primary Stability",
    "Vendor Primary Stability Datasets",
    "Vendor Cost Optimizations",
    "Vendor Route Weight Plans",
    "Vendor Budget Stress",
    "Vendor Route Executions",
    "Vendor Route Execution Datasets",
    "Vendor Route Rollout Stages",
    "Vendor Production Source Runs",
    "Vendor Production Source Dataset Checks",
    "Vendor Production Source Decisions",
    "Source Route Weight Policies",
    "Source Route Decisions",
    "Source Route Health",
    "Source Route Circuit Breakers",
    "Source Route Recovery Probes",
    "Source Route Incident Actions",
    "Source Route Incident Controls",
    "Source Route Incident Control Health",
    "Source Route Incident Operation Batches",
    "Source Route Incident Operation Items",
    "Source Route Incident Approval Commands",
    "Source Route Incident Approval Command Items",
    "Source Route Incident Approval Signatures",
    "Source Route Incident Approval Role Bindings",
    "Source Route Incident Approval Policies",
    "Source Route Incident Approval Callbacks",
    "Source Route Incident Approval Escalations",
    "Source Route Incident Approval Lock Events",
    "Source Route Incident Approval State Transitions",
    "Source Route Incident Approval Audit Chain",
    "Source Route Incident Approval SLA Actions",
    "Source Route Incident Approval Recovery Drills",
    "Source Route Incident Approval Release Preflights",
    "Source Route Incident Approval Secret Rotations",
    "Source Route Incident Approval Concurrency Tests",
    "Source Route Incident Approval Audit Exports",
    "data-gamma6-action",
    "Payment Batches",
    "Payment Matches",
    "Revenue Ledger",
    "Runtime Metrics",
    "Capacity Alerts",
    "Strategy Decisions",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the Upsilon admin console HTML.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    body, content_type = _get(args.base_url, args.token)
    if "text/html" not in content_type:
        raise SystemExit(f"upsilon_console=failed reason=content_type content_type={content_type}")
    missing = [marker for marker in REQUIRED_MARKERS if marker not in body]
    if missing:
        raise SystemExit(f"upsilon_console=failed missing={','.join(missing)}")
    print(f"upsilon_console=ok html_bytes={len(body)} markers={len(REQUIRED_MARKERS)}")
    return 0


def _get(base_url: str, token: str) -> tuple[str, str]:
    request = Request(
        f"{base_url.rstrip('/')}/admin/console",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8"), response.headers.get("Content-Type", "")


if __name__ == "__main__":
    raise SystemExit(main())
