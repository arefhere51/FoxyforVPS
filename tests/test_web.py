import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class WebTests(unittest.TestCase):
    def test_browser_login_bridge_same_origin_verification_and_panel_password_rotation(self):
        root = Path(tempfile.mkdtemp(prefix="foxyforvps-test-"))
        os.environ["FOXY_STATE_DIR"] = str(root / "state")
        os.environ["FOXY_ETC_DIR"] = str(root / "etc")
        os.environ["FOXY_CORE_CONFIG"] = str(root / "etc" / "sing-box.json")
        os.environ["FOXY_TOKEN_FILE"] = str(root / "state" / "bearer.token")
        os.environ["FOXY_ADMIN_PASSWORD_FILE"] = str(root / "etc" / "admin-password")
        os.environ["FOXY_PUBLIC_IPS_FILE"] = str(root / "etc" / "public-ips")
        os.environ["FOXY_ADMIN_PASSWORD"] = "test-password-123"
        (root / "etc").mkdir(parents=True)
        (root / "etc" / "admin-password").write_text("test-password-123")
        (root / "etc" / "public-ips").write_text("8.8.8.8\n")
        (root / "state").mkdir(parents=True)
        old_state = {"locations": {"US": {"enabled": True, "port": 2020,
                                             "username": "old-proxy-user", "password": "old-proxy-secret"}}}
        (root / "state" / "settings.json").write_text(json.dumps(old_state))

        from fastapi.testclient import TestClient
        from foxyforvps.app import app, _normalize_public_domain, _state, browser_login_attempts

        self.assertEqual(_normalize_public_domain("Alias.Example.com."), "alias.example.com")
        self.assertIsNone(_normalize_public_domain("127.0.0.1"))
        self.assertIsNone(_normalize_public_domain("bad host.example"))
        migrated = _state()
        self.assertNotIn("username", migrated["locations"]["US"])
        self.assertNotIn("password", migrated["locations"]["US"])
        self.assertNotIn("old-proxy-secret", (root / "state" / "settings.json").read_text())
        browser_login_attempts.clear()

        with patch("foxyforvps.app._directory", new_callable=AsyncMock, return_value=[]):
            with TestClient(app, client=("127.0.0.1", 12345)) as client:
                with patch("foxyforvps.app._lookup_public_ips", new_callable=AsyncMock,
                           return_value=frozenset({"8.8.8.8"})):
                    authorized = client.get("/api/tls/authorize?domain=alias.example.com")
                self.assertEqual(authorized.status_code, 204)
                with patch("foxyforvps.app._lookup_public_ips", new_callable=AsyncMock,
                           return_value=frozenset({"1.1.1.1"})):
                    wrong_ip = client.get("/api/tls/authorize?domain=other.example.com")
                self.assertEqual(wrong_ip.status_code, 403)
                self.assertEqual(client.get("/api/tls/authorize?domain=127.0.0.1").status_code, 403)

                headers = {"origin": "http://testserver"}
                no_origin = client.post(
                    "/api/account/browser-login/start", auth=("admin", "test-password-123"), json={},
                )
                self.assertEqual(no_origin.status_code, 403)
                csrf = client.post(
                    "/api/account/browser-login/start", auth=("admin", "test-password-123"),
                    headers={"origin": "https://attacker.example"}, json={},
                )
                self.assertEqual(csrf.status_code, 403)
                self.assertEqual(client.get("/api/state", auth=("admin", "wrong")).status_code, 401)
                self.assertEqual(client.post(
                    "/api/account/login-password", auth=("admin", "test-password-123"),
                    headers=headers, json={"email": "user@example.com", "password": "temporary-secret"},
                ).status_code, 404)

                started = client.post(
                    "/api/account/browser-login/start", auth=("admin", "test-password-123"),
                    headers=headers, json={},
                )
                self.assertEqual(started.status_code, 200)
                start_data = started.json()
                attempt_id, nonce = start_data["attempt_id"], start_data["nonce"]
                self.assertEqual(start_data["login_url"],
                    "https://accounts.firefox.com/?context=fx_desktop_v3&service=sync&action=email")
                token = "a" * 64

                bad_nonce = client.post(
                    f"/api/account/browser-login/{attempt_id}/session",
                    auth=("admin", "test-password-123"), headers=headers,
                    json={"nonce": "z" * len(nonce), "email": "user@example.com", "session_token": token},
                )
                self.assertEqual(bad_nonce.status_code, 403)

                with patch("foxyforvps.app.account.session_status", new_callable=AsyncMock,
                           return_value={"verified": False, "email": "user@example.com"}):
                    pending = client.post(
                        f"/api/account/browser-login/{attempt_id}/session",
                        auth=("admin", "test-password-123"), headers=headers,
                        json={"nonce": nonce, "email": "user@example.com", "session_token": token},
                    )
                    self.assertEqual(pending.status_code, 200)
                    self.assertEqual(pending.json()["stage"], "waiting_verification")
                    self.assertNotIn(token, pending.text)
                    self.assertNotIn("session_token", pending.text)
                    self.assertEqual(client.get(
                        f"/api/account/browser-login/{attempt_id}", auth=("admin", "test-password-123"),
                    ).json()["stage"], "waiting_verification")

                with patch("foxyforvps.app.account.session_status", new_callable=AsyncMock,
                           return_value={"verified": True, "email": "user@example.com"}), \
                     patch("foxyforvps.app.account.sign_in_with_session_token", new_callable=AsyncMock,
                           return_value={"quota_remaining": 400}), \
                     patch("foxyforvps.app.account.proxy_pass", new_callable=AsyncMock,
                           return_value={"token": "proxy-pass", "quota_remaining": 400}), \
                     patch("foxyforvps.app._save_json"), patch("foxyforvps.app._write_bearer"), \
                     patch("foxyforvps.app._apply_core"):
                    completed = client.get(
                        f"/api/account/browser-login/{attempt_id}", auth=("admin", "test-password-123"),
                    )
                self.assertEqual(completed.status_code, 200)
                self.assertTrue(completed.json()["ok"])
                self.assertNotIn(token, completed.text)
                self.assertNotIn(attempt_id, browser_login_attempts)

                with patch("foxyforvps.app._directory", new_callable=AsyncMock, return_value=[]):
                    changed = client.post(
                        "/api/admin/password", auth=("admin", "test-password-123"),
                        headers=headers, json={"new_password": "x"},
                    )
                self.assertEqual(changed.status_code, 200)
                stored = (root / "etc" / "admin-password").read_text()
                self.assertTrue(stored.startswith("pbkdf2_sha256$"))
                self.assertNotIn("x", stored)
                self.assertEqual(client.get("/api/state", auth=("admin", "test-password-123")).status_code, 401)
                self.assertEqual(client.get("/api/state", auth=("admin", "x")).status_code, 200)

            with TestClient(app, client=("192.0.2.10", 43210)) as external_client:
                self.assertEqual(external_client.get("/api/tls/authorize?domain=alias.example.com").status_code, 403)


if __name__ == "__main__":
    unittest.main()
