from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from http.server import ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from qdata.api.server import create_handler
from qdata.kappa import KappaResult


class ApiServerTest(unittest.TestCase):
    def setUp(self) -> None:
        handler = create_handler(tokens=["secret"], default_backend="mock")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_health_does_not_require_token(self) -> None:
        payload, _ = self._get("/health?format=json")

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"][0]["status"], "ok")

    def test_price_requires_token_and_returns_json_payload(self) -> None:
        with self.assertRaises(HTTPError) as context:
            self._get("/price?symbols=600519.SH&start_date=2024-01-02&end_date=2024-01-02", token="")
        self.assertEqual(context.exception.code, 401)

        payload, _ = self._get(
            "/price?symbols=600519.SH&start_date=2024-01-02&end_date=2024-01-02",
            token="secret",
        )

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["meta"]["row_count"], 1)
        self.assertEqual(payload["data"][0]["symbol"], "600519.SH")

    def test_matrix_endpoint_can_return_csv(self) -> None:
        body, content_type = self._get_raw(
            "/matrix?symbols=600519.SH,000001.SZ&start_date=2024-01-02&end_date=2024-01-02&field=close&format=csv",
            token="secret",
        )

        self.assertIn("text/csv", content_type)
        self.assertIn("trade_date,600519.SH,000001.SZ", body)
        self.assertIn("2024-01-02,1698.0,9.58", body)

    def test_admin_endpoint_requires_admin_scope(self) -> None:
        with self.assertRaises(HTTPError) as context:
            self._get("/admin/overview", token="secret")
        self.assertEqual(context.exception.code, 403)

    def test_admin_endpoint_returns_kappa_payload_with_admin_scope(self) -> None:
        admin_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(
                tokens=["admin-secret"],
                token_scopes=["read", "admin"],
                default_backend="mock",
                kappa_factory=lambda path, params: KappaResult(
                    "overview",
                    [{"active_tenant_count": 1, "open_alert_count": 2}],
                    {"row_count": 1},
                ),
            ),
        )
        thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{admin_server.server_port}/admin/overview",
                headers={"Authorization": "Bearer admin-secret"},
            )
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["data"][0]["active_tenant_count"], 1)
            self.assertEqual(payload["meta"]["row_count"], 1)
        finally:
            admin_server.shutdown()
            admin_server.server_close()
            thread.join(timeout=2)

    def test_admin_post_approval_command_requires_admin_scope(self) -> None:
        body = json.dumps({"decision": "approve", "control_code": "ctrl"}).encode("utf-8")
        request = Request(
            f"{self.base_url}/admin/source-route-incident-approval-commands",
            data=body,
            method="POST",
            headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=10)
        self.assertEqual(context.exception.code, 403)

    def test_admin_post_approval_command_dispatches_with_admin_scope(self) -> None:
        captured = {}
        admin_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(
                postgres_dsn="postgresql://unused",
                tokens=["admin-secret"],
                token_scopes=["read", "admin"],
                default_backend="mock",
            ),
        )
        thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
        thread.start()
        try:
            def fake_submit(postgres_dsn, **kwargs):
                captured["postgres_dsn"] = postgres_dsn
                captured.update(kwargs)
                return {
                    "command_code": "gamma6-route-approval-demo",
                    "status": "pending_quorum",
                    "decision": kwargs["decision"],
                    "quorum_status": "pending",
                }

            with patch("qdata.api.server.submit_route_incident_approval_command", side_effect=fake_submit):
                request = Request(
                    f"http://127.0.0.1:{admin_server.server_port}/admin/source-route-incident-approval-commands",
                    data=json.dumps(
                        {
                            "decision": "approve",
                            "control_code": "omega5-route-control-demo",
                            "requested_by": "operator",
                            "principal_code": "approver-a",
                            "required_approvals": 2,
                            "idempotency_key": "gamma6-test-key",
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Authorization": "Bearer admin-secret", "Content-Type": "application/json"},
                )
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["data"][0]["command_code"], "gamma6-route-approval-demo")
            self.assertEqual(captured["postgres_dsn"], "postgresql://unused")
            self.assertEqual(captured["decision"], "approve")
            self.assertEqual(captured["control_code"], "omega5-route-control-demo")
            self.assertEqual(captured["principal_code"], "approver-a")
            self.assertEqual(captured["required_approvals"], 2)
            self.assertEqual(captured["idempotency_key"], "gamma6-test-key")
        finally:
            admin_server.shutdown()
            admin_server.server_close()
            thread.join(timeout=2)

    def test_admin_post_wecom_callback_requires_admin_scope(self) -> None:
        body = json.dumps({"decision": "approve", "control_code": "ctrl", "signer_code": "approver"}).encode("utf-8")
        request = Request(
            f"{self.base_url}/admin/source-route-incident-approval-wecom-callbacks",
            data=body,
            method="POST",
            headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=10)
        self.assertEqual(context.exception.code, 403)

    def test_signed_wecom_callback_dispatches_without_bearer_token(self) -> None:
        captured = {}
        webhook_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(
                postgres_dsn="postgresql://unused",
                tokens=["admin-secret"],
                token_scopes=["read", "admin"],
                default_backend="mock",
            ),
        )
        thread = threading.Thread(target=webhook_server.serve_forever, daemon=True)
        thread.start()
        try:
            def fake_callback(postgres_dsn, **kwargs):
                captured["postgres_dsn"] = postgres_dsn
                captured.update(kwargs)
                return {
                    "callback_code": "delta6-callback-demo",
                    "signature_status": "verified",
                    "governance_status": "pending_quorum",
                    "decision": kwargs["payload"]["decision"],
                }

            with patch("qdata.api.server.submit_resilient_wecom_route_approval_callback", side_effect=fake_callback):
                request = Request(
                    f"http://127.0.0.1:{webhook_server.server_port}/webhooks/wecom/source-route-incident-approval-callbacks",
                    data=json.dumps(
                        {
                            "provider_code": "wecom",
                            "decision": "approve",
                            "control_code": "omega5-route-control-demo",
                            "signer_code": "approver-a",
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "X-QData-Timestamp": "1785312000",
                        "X-QData-Nonce": "nonce",
                        "X-QData-Signature": "sha256=demo",
                    },
                )
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["data"][0]["callback_code"], "delta6-callback-demo")
            self.assertEqual(captured["postgres_dsn"], "postgresql://unused")
            self.assertEqual(captured["payload"]["control_code"], "omega5-route-control-demo")
            self.assertIn("x-qdata-nonce", {key.lower() for key in captured["headers"]})
            self.assertIsInstance(captured["raw_body"], bytes)
        finally:
            webhook_server.shutdown()
            webhook_server.server_close()
            thread.join(timeout=2)

    def test_signed_wecom_callback_selects_next_rotation_secret(self) -> None:
        captured = {}
        webhook_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(
                postgres_dsn="postgresql://unused",
                tokens=["admin-secret"],
                token_scopes=["read", "admin"],
                default_backend="mock",
            ),
        )
        thread = threading.Thread(target=webhook_server.serve_forever, daemon=True)
        thread.start()
        try:
            body = json.dumps(
                {
                    "provider_code": "wecom",
                    "decision": "approve",
                    "control_code": "omega5-route-control-demo",
                    "signer_code": "approver-a",
                },
                sort_keys=True,
            ).encode("utf-8")
            timestamp = str(int(datetime.now(timezone.utc).timestamp()))
            nonce = "zeta6-next-secret-api"
            digest = hmac.new(b"next-secret", f"{timestamp}\n{nonce}\n".encode("utf-8") + body, hashlib.sha256).hexdigest()

            def fake_callback(postgres_dsn, **kwargs):
                captured["postgres_dsn"] = postgres_dsn
                captured.update(kwargs)
                return {
                    "callback_code": "delta6-callback-demo",
                    "signature_status": "verified",
                    "governance_status": "pending_quorum",
                    "decision": kwargs["payload"]["decision"],
                }

            with patch.dict(os.environ, {"QDATA_DELTA6_WECOM_CALLBACK_SECRET": "current-secret", "QDATA_ZETA6_WECOM_CALLBACK_SECRET_NEXT": "next-secret"}):
                with patch("qdata.api.server.submit_resilient_wecom_route_approval_callback", side_effect=fake_callback):
                    request = Request(
                        f"http://127.0.0.1:{webhook_server.server_port}/webhooks/wecom/source-route-incident-approval-callbacks",
                        data=body,
                        method="POST",
                        headers={
                            "Content-Type": "application/json",
                            "X-QData-Timestamp": timestamp,
                            "X-QData-Nonce": nonce,
                            "X-QData-Signature": f"sha256={digest}",
                        },
                    )
                    with urlopen(request, timeout=10) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "success")
            self.assertEqual(captured["secret"], "next-secret")
            self.assertEqual(payload["data"][0]["zeta6"]["secret_rotation"]["verified_secret_label"], "next")
        finally:
            webhook_server.shutdown()
            webhook_server.server_close()
            thread.join(timeout=2)

    def test_admin_console_returns_html(self) -> None:
        admin_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(
                tokens=["admin-secret"],
                token_scopes=["read", "admin"],
                default_backend="mock",
                kappa_factory=lambda path, params: KappaResult(
                    "console",
                    [{"html": "<!doctype html><title>Kappa</title>"}],
                    {"row_count": 1},
                ),
            ),
        )
        thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{admin_server.server_port}/admin/console",
                headers={"Authorization": "Bearer admin-secret"},
            )
            with urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "")
            self.assertIn("text/html", content_type)
            self.assertIn("Kappa", body)
        finally:
            admin_server.shutdown()
            admin_server.server_close()
            thread.join(timeout=2)

    def test_admin_console_accepts_browser_token_query(self) -> None:
        admin_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(
                tokens=["admin-secret"],
                token_scopes=["read", "admin"],
                default_backend="mock",
                kappa_factory=lambda path, params: KappaResult(
                    "console",
                    [{"html": "<!doctype html><title>Upsilon</title>"}],
                    {"row_count": 1},
                ),
            ),
        )
        thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{admin_server.server_port}/admin/console?token=admin-secret", timeout=10) as response:
                body = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "")
            self.assertIn("text/html", content_type)
            self.assertIn("Upsilon", body)
        finally:
            admin_server.shutdown()
            admin_server.server_close()
            thread.join(timeout=2)

    def test_root_redirects_to_browser_console(self) -> None:
        admin_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(
                tokens=["admin-secret"],
                token_scopes=["read", "admin"],
                default_backend="mock",
                kappa_factory=lambda path, params: KappaResult(
                    "console",
                    [{"html": "<!doctype html><title>Upsilon</title>"}],
                    {"row_count": 1},
                ),
            ),
        )
        thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{admin_server.server_port}/", timeout=10) as response:
                body = response.read().decode("utf-8")
                final_url = response.geturl()
            self.assertIn("/admin/console?token=admin-secret", final_url)
            self.assertIn("Upsilon", body)
        finally:
            admin_server.shutdown()
            admin_server.server_close()
            thread.join(timeout=2)

    def test_query_token_does_not_authenticate_non_console_endpoint(self) -> None:
        admin_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(
                tokens=["admin-secret"],
                token_scopes=["read", "admin"],
                default_backend="mock",
                kappa_factory=lambda path, params: KappaResult(
                    "overview",
                    [{"active_tenant_count": 1}],
                    {"row_count": 1},
                ),
            ),
        )
        thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(HTTPError) as context:
                urlopen(f"http://127.0.0.1:{admin_server.server_port}/admin/overview?token=admin-secret", timeout=10)
            self.assertEqual(context.exception.code, 401)
        finally:
            admin_server.shutdown()
            admin_server.server_close()
            thread.join(timeout=2)

    def test_price_payload_includes_route_policy_meta_when_resolved(self) -> None:
        audits = []
        decision = {
            "decision_code": "phi5-api-route-test",
            "policy_code": "phi5-api-policy-test",
            "dataset_code": "daily_bar",
            "requested_source_code": "csv",
            "selected_source_code": "csv_mirror",
            "final_source_code": "csv_mirror",
            "decision_context": "api",
            "route_mode": "policy_weighted",
            "decision_status": "selected",
            "selected_role": "primary",
            "primary_weight_pct": 100,
            "backup_weight_pct": 0,
            "free_source_weight_pct": 0,
            "selected_weight_pct": 100,
            "deterministic_bucket": 7,
            "candidate_sources": ["csv_mirror"],
            "fallback_source_codes": [],
            "attempt_sources": [],
            "request_key": "api-test",
            "source_ids_by_code": {},
            "details": {},
        }
        route_server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(tokens=["secret"], default_backend="mock", postgres_dsn="postgresql://unused"),
        )
        thread = threading.Thread(target=route_server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("qdata.api.server.resolve_source_route", return_value=decision), patch(
                "qdata.api.server.write_source_route_decision_audit",
                side_effect=lambda postgres_dsn, finalized, **kwargs: audits.append(finalized),
            ):
                request = Request(
                    f"http://127.0.0.1:{route_server.server_port}/price?symbols=600519.SH&start_date=2024-01-02&end_date=2024-01-02",
                    headers={"Authorization": "Bearer secret"},
                )
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["meta"]["route_policy"]["selected_source_code"], "csv_mirror")
            self.assertEqual(payload["meta"]["route_policy"]["decision_context"], "api")
            self.assertEqual(audits[0]["decision_status"], "success")
            self.assertEqual(audits[0]["request_id"], payload["request_id"])
        finally:
            route_server.shutdown()
            route_server.server_close()
            thread.join(timeout=2)

    def _get(self, path: str, token: str = "secret"):
        body, content_type = self._get_raw(path, token=token)
        return json.loads(body), content_type

    def _get_raw(self, path: str, token: str = "secret"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = Request(f"{self.base_url}{path}", headers=headers)
        with urlopen(request, timeout=10) as response:
            return response.read().decode("utf-8"), response.headers.get("Content-Type", "")


if __name__ == "__main__":
    unittest.main()
