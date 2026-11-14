import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class WebTests(unittest.TestCase):
    def test_password_login_same_origin_and_panel_password_rotation(self):
        root = Path(tempfile.mkdtemp(prefix="foxyforvps-test-"))
        os.environ["FOXY_STATE_DIR"] = str(root / "state")
        os.environ["FOXY_ETC_DIR"] = str(root / "etc")
        os.environ["FOXY_CORE_CONFIG"] = str(root / "etc" / "sing-box.json")
        os.environ["FOXY_TOKEN_FILE"] = str(root / "state" / "bearer.token")
        os.environ["FOXY_ADMIN_PASSWORD_FILE"] = str(root / "etc" / "admin-password")
        os.environ["FOXY_ADMIN_PASSWORD"] = "test-password-123"
        (root / "etc").mkdir(parents=True)
        (root / "etc" / "admin-password").write_text("test-password-123")

        from fastapi.testclient import TestClient
        from foxyforvps.app import app

        with patch("foxyforvps.app._directory", new_callable=AsyncMock, return_value=[]):
            with TestClient(app) as client:
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
                denied = client.get("/api/state", auth=("admin", "wrong"))
                self.assertEqual(denied.status_code, 401)

                with patch("foxyforvps.app.capture_firefox_session", return_value="a" * 64) as capture, \
                     patch("foxyforvps.app.account.sign_in_with_session_token", new_callable=AsyncMock, return_value={"quota_remaining": 500}), \
                     patch("foxyforvps.app.account.proxy_pass", new_callable=AsyncMock, return_value={"token": "proxy-pass", "quota_remaining": 500}), \
                     patch("foxyforvps.app._save_json"), patch("foxyforvps.app._write_bearer"), \
                     patch("foxyforvps.app._apply_core"):
                    login = client.post(
                        "/api/account/login-password", auth=("admin", "test-password-123"),
                        headers={"origin": "http://testserver"},
                        json={"email": "user@example.com", "password": "temporary-secret"},
                    )
                self.assertEqual(login.status_code, 200)
                self.assertNotIn("temporary-secret", login.text)
                capture.assert_called_once_with("user@example.com", "temporary-secret")

                changed = client.post(
                    "/api/admin/password", auth=("admin", "test-password-123"),
                    headers={"origin": "http://testserver"},
                    json={"new_password": "new-panel-password-12"},
                )
                self.assertEqual(changed.status_code, 200)
                stored = (root / "etc" / "admin-password").read_text()
                self.assertTrue(stored.startswith("pbkdf2_sha256$"))
                self.assertNotIn("new-panel-password-12", stored)
                self.assertEqual(client.get("/api/state", auth=("admin", "test-password-123")).status_code, 401)
                self.assertEqual(client.get("/api/state", auth=("admin", "new-panel-password-12")).status_code, 200)


if __name__ == "__main__":
    unittest.main()
