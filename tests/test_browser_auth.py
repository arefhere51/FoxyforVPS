import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from foxyforvps.auth import AuthError, FXA_AUTH, FXA_DESTROY, FXA_VERIFY, FirefoxAccount


class BrowserSessionTests(unittest.TestCase):
    def test_session_status_reads_verification_without_sending_raw_token(self):
        seen = []

        def handler(request):
            seen.append(request)
            if str(request.url) == FXA_VERIFY:
                return httpx.Response(200, json={"verified": False, "email": "user@example.com"})
            return httpx.Response(404)

        async def run():
            account = FirefoxAccount(Path(tempfile.mkdtemp(prefix="foxy-fxa-test-")))
            await account.http.aclose()
            account.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                result = await account.session_status("a" * 64)
                self.assertFalse(result["verified"])
                self.assertEqual(result["email"], "user@example.com")
            finally:
                await account.http.aclose()

        asyncio.run(run())
        self.assertEqual(len(seen), 1)
        self.assertNotIn("a" * 64, seen[0].headers.get("Authorization", ""))

    def test_session_is_destroyed_when_oauth_authorization_returns_406(self):
        visited = []

        def handler(request):
            url = str(request.url)
            visited.append(url)
            if url == FXA_VERIFY:
                return httpx.Response(200, json={"verified": True})
            if url == FXA_AUTH:
                return httpx.Response(406, text="challenge body is not exposed")
            if url == FXA_DESTROY:
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(404)

        async def run():
            account = FirefoxAccount(Path(tempfile.mkdtemp(prefix="foxy-fxa-test-")))
            await account.http.aclose()
            account.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                with self.assertRaises(AuthError) as caught:
                    await account.sign_in_with_session_token("b" * 64)
                self.assertIn("HTTP 406", str(caught.exception))
                self.assertNotIn("challenge body", str(caught.exception))
            finally:
                await account.http.aclose()

        asyncio.run(run())
        self.assertEqual(visited, [FXA_VERIFY, FXA_AUTH, FXA_DESTROY])

    def test_invalid_session_is_rejected_before_network_request(self):
        async def run():
            account = FirefoxAccount(Path(tempfile.mkdtemp(prefix="foxy-fxa-test-")))
            await account.http.aclose()
            called = False

            def handler(_request):
                nonlocal called
                called = True
                return httpx.Response(200, json={})

            account.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                with self.assertRaises(AuthError):
                    await account.session_status("not-a-session")
                self.assertFalse(called)
            finally:
                await account.http.aclose()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
