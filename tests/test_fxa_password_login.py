import asyncio
import json
import re
import unittest

import httpx

from foxyforvps.fxa_password_login import (
    LOGIN_URL,
    VERIFY_CODE_URL,
    LoginRejected,
    derive_auth_pw,
    start_password_login,
    verify_login_step,
)


class FirefoxPasswordLoginTests(unittest.TestCase):
    def test_authpw_is_deterministic_hex_and_not_plain_password(self):
        first = derive_auth_pw("user@example.com", "example-secret")
        second = derive_auth_pw("user@example.com", "example-secret")
        self.assertEqual(first, second)
        self.assertRegex(first, re.compile(r"^[0-9a-f]{64}$"))
        self.assertNotIn("example-secret", first)
        self.assertNotEqual(first, derive_auth_pw("other@example.com", "example-secret"))

    def test_login_sends_derived_authpw_and_returns_email_code_stage(self):
        observed = {}

        def handler(request):
            self.assertEqual(str(request.url), LOGIN_URL)
            body = json.loads(request.content)
            observed.update(body)
            return httpx.Response(200, json={
                "sessionToken": "a" * 64,
                "verified": False,
                "verificationMethod": "email-2fa",
                "email": "user@example.com",
            })

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await start_password_login(client, "user@example.com", "example-secret")

        result = asyncio.run(run())
        self.assertEqual(result["stage"], "email_code")
        self.assertEqual(result["session_token"], "a" * 64)
        self.assertEqual(observed["authPW"], derive_auth_pw("user@example.com", "example-secret"))
        self.assertNotIn("password", observed)
        self.assertNotIn("example-secret", json.dumps(observed))
        self.assertEqual(observed["verificationMethod"], "email-2fa")

    def test_http_406_is_reported_without_challenge_bypass(self):
        def handler(_request):
            return httpx.Response(406, text="Client Challenge")

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await start_password_login(client, "user@example.com", "example-secret")

        with self.assertRaises(LoginRejected) as caught:
            asyncio.run(run())
        self.assertIn("HTTP 406", str(caught.exception))
        self.assertNotIn("Client Challenge", str(caught.exception))

    def test_email_code_verification_uses_hawk_and_does_not_echo_code(self):
        def handler(request):
            self.assertEqual(str(request.url), VERIFY_CODE_URL)
            self.assertEqual(request.method, "POST")
            self.assertTrue(request.headers.get("Authorization", "").startswith("Hawk id="))
            self.assertEqual(json.loads(request.content), {"code": "123456"})
            return httpx.Response(200, json={"success": True})

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await verify_login_step(client, "b" * 64, "email_code", "12 34 56")

        self.assertTrue(asyncio.run(run()))


if __name__ == "__main__":
    unittest.main()
