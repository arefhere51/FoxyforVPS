import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class WebTests(unittest.TestCase):
    def test_pair_code_is_single_use_and_invalid_token_is_not_sent_to_mozilla(self):
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
                created = client.post("/api/account/pair", auth=("admin", "test-password-123"))
                self.assertEqual(created.status_code, 200)
                code = created.json()["pair_code"]
                invalid = client.post("/api/account/browser-session", json={
                    "pair_code": code,
                    "session_token": "z" * 64,
                })
                self.assertEqual(invalid.status_code, 400)
                reused = client.post("/api/account/browser-session", json={
                    "pair_code": code,
                    "session_token": "z" * 64,
                })
                self.assertEqual(reused.status_code, 403)
                denied = client.post("/api/account/pair", auth=("admin", "wrong"))
                self.assertEqual(denied.status_code, 401)


if __name__ == "__main__":
    unittest.main()
