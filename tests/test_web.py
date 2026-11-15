import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class WebTests(unittest.TestCase):
    def test_api_login_verification_same_origin_and_panel_password_rotation(self):
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
        from foxyforvps.app import app, _normalize_public_domain, _state, login_attempts

        self.assertEqual(_normalize_public_domain("Alias.Example.com."), "alias.example.com")
        self.assertIsNone(_normalize_public_domain("127.0.0.1"))
        self.assertIsNone(_normalize_public_domain("bad host.example"))
        migrated = _state()
        self.assertNotIn("username", migrated["locations"]["US"])
        self.assertNotIn("password", migrated["locations"]["US"])
        self.assertNotIn("old-proxy-secret", (root / "state" / "settings.json").read_text())

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

                no_origin = client.post(
                    "/api/account/login-password", auth=("admin", "test-password-123"),
                    json={"email": "user@example.com", "password": "temporary-secret"},
                )
                self.assertEqual(no_origin.status_code, 403)
                csrf = client.post(
                    "/api/account/login-password", auth=("admin", "test-password-123"),
                    headers={"origin": "https://attacker.example"},
                    json={"email": "user@example.com", "password": "temporary-secret"},
                )
                self.assertEqual(csrf.status_code, 403)
                self.assertEqual(client.get("/api/state", auth=("admin", "wrong")).status_code, 401)

                with patch("foxyforvps.app.start_password_login", new_callable=AsyncMock,
                           return_value={"stage": "verified", "email": "user@example.com", "session_token": "a" * 64}) as start, \
                     patch("foxyforvps.app.account.sign_in_with_session_token", new_callable=AsyncMock,
                           return_value={"quota_remaining": 500}), \
                     patch("foxyforvps.app.account.proxy_pass", new_callable=AsyncMock,
                           return_value={"token": "proxy-pass", "quota_remaining": 500}), \
                     patch("foxyforvps.app._save_json"), patch("foxyforvps.app._write_bearer"), \
                     patch("foxyforvps.app._apply_core"):
                    login = client.post(
                        "/api/account/login-password", auth=("admin", "test-password-123"),
                        headers={"origin": "http://testserver"},
                        json={"email": "user@example.com", "password": "temporary-secret"},
                    )
                self.assertEqual(login.status_code, 200)
                self.assertNotIn("temporary-secret", login.text)
                start.assert_awaited_once()
                self.assertEqual(start.await_args.args[2], "temporary-secret")

                login_attempts.clear()
                with patch("foxyforvps.app.start_password_login", new_callable=AsyncMock,
                           return_value={"stage": "email_code", "email": "user@example.com",
                                         "session_token": "b" * 64, "message": "enter code"}):
                    pending = client.post(
                        "/api/account/login-password", auth=("admin", "test-password-123"),
                        headers={"origin": "http://testserver"},
                        json={"email": "user@example.com", "password": "temporary-secret"},
                    )
                self.assertEqual(pending.status_code, 200)
                self.assertEqual(pending.json()["stage"], "email_code")
                self.assertNotIn("session_token", pending.text)
                self.assertNotIn("temporary-secret", pending.text)
                attempt_id = pending.json()["attempt_id"]

                with patch("foxyforvps.app.verify_login_step", new_callable=AsyncMock, return_value=True), \
                     patch("foxyforvps.app.account.sign_in_with_session_token", new_callable=AsyncMock,
                           return_value={"quota_remaining": 400}), \
                     patch("foxyforvps.app.account.proxy_pass", new_callable=AsyncMock,
                           return_value={"token": "proxy-pass", "quota_remaining": 400}), \
                     patch("foxyforvps.app._save_json"), patch("foxyforvps.app._write_bearer"), \
                     patch("foxyforvps.app._apply_core"):
                    verified = client.post(
                        "/api/account/login-verify", auth=("admin", "test-password-123"),
                        headers={"origin": "http://testserver"},
                        json={"attempt_id": attempt_id, "code": "123456"},
                    )
                self.assertEqual(verified.status_code, 200)
                self.assertNotIn("b" * 64, verified.text)
                self.assertNotIn(attempt_id, login_attempts)

                with patch("foxyforvps.app._directory", new_callable=AsyncMock, return_value=[]):
                    changed = client.post(
                        "/api/admin/password", auth=("admin", "test-password-123"),
                        headers={"origin": "http://testserver"}, json={"new_password": "x"},
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
