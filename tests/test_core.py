import json
import unittest
from pathlib import Path

from foxyforvps.auth import _hawk, _hkdf, _session_creds
from foxyforvps.engine import build_config


class CoreTests(unittest.TestCase):
    def test_builds_proxy_for_enabled_location_and_locked_flag_does_not_bypass_mozilla_auth(self):
        countries = [
            {"code": "US", "locked": False, "servers": [{"host": "us.example", "port": 443, "city": "New York"}]},
            {"code": "DE", "locked": True, "servers": [{"host": "de.example", "port": 443}]},
            {"code": "NL", "locked": False, "servers": [{"host": "nl.example", "port": 443}]},
        ]
        state = {"locations": {
            "US": {"enabled": True, "port": 2020, "username": "u", "password": "long-secret"},
            "DE": {"enabled": True, "port": 2021, "username": "u", "password": "long-secret"},
            "NL": {"enabled": False, "port": 2022, "username": "u", "password": "long-secret"},
        }}
        config = build_config(countries, state)
        self.assertEqual([x["tag"] for x in config["inbounds"]], ["socks-us", "socks-de"])
        self.assertEqual(config["inbounds"][0]["listen_port"], 2020)
        self.assertEqual(config["inbounds"][1]["listen_port"], 2021)
        self.assertEqual(config["inbounds"][0]["listen"], "0.0.0.0")
        self.assertEqual(config["inbounds"][0]["users"], [{"username": "u", "password": "long-secret"}])
        self.assertEqual(config["outbounds"][1]["dynamic_bearer_token"], True)
        self.assertEqual(config["route"]["rules"], [{"inbound": ["socks-us"], "outbound": "vpn-us"}, {"inbound": ["socks-de"], "outbound": "vpn-de"}])

    def test_hkdf_and_session_credential_shapes(self):
        key = bytes(range(32))
        output = _hkdf(key, b"identity.mozilla.com/picl/v1/sessionToken", 64)
        self.assertEqual(len(output), 64)
        token_id, mac_key = _session_creds("00" * 32)
        self.assertEqual(len(token_id), 64)
        self.assertEqual(len(mac_key), 32)

    def test_hawk_auth_header_contains_no_raw_session_token(self):
        raw = "00" * 32
        token_id, mac_key = _session_creds(raw)
        header = _hawk("POST", "https://example.com/v1/token", token_id, mac_key, b"{}")
        self.assertTrue(header.startswith('Hawk id='))
        self.assertIn('hash=', header)
        self.assertNotIn(raw, header)

    def test_browser_helper_manifest_is_scoped_to_firefox_accounts(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "browser-helper" / "manifest.json").read_text())
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertIn("https://accounts.firefox.com/*", manifest["host_permissions"])
        self.assertIn("http://127.0.0.1/*", manifest["host_permissions"])
        self.assertIn("https://*/*", manifest["optional_host_permissions"])
        self.assertEqual(manifest["content_scripts"][0]["world"], "MAIN")


if __name__ == "__main__":
    unittest.main()
