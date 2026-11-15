from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

FXA_CLIENT_ID = "5882386c6d801776"
FXA_SCOPE = "profile https://identity.mozilla.com/apps/vpn"
FXA_AUTH = "https://api.accounts.firefox.com/v1/oauth/authorization"
FXA_TOKEN = "https://oauth.accounts.firefox.com/v1/token"
FXA_TOKEN_FALLBACK = "https://api.accounts.firefox.com/v1/oauth/token"
FXA_VERIFY = "https://api.accounts.firefox.com/v1/recovery_email/status"
FXA_DESTROY = "https://api.accounts.firefox.com/v1/session/destroy"
GUARDIAN = "https://vpn.mozilla.org"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0"


class AuthError(RuntimeError):
    pass


def _b64(data: bytes, urlsafe: bool = False) -> str:
    fn = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    value = fn(data).decode()
    return value.rstrip("=") if urlsafe else value


def _hkdf(ikm: bytes, info: bytes, length: int, salt: bytes = bytes(32)) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, last, counter = b"", b"", 1
    while len(out) < length:
        last = hmac.new(prk, last + info + bytes([counter]), hashlib.sha256).digest()
        out += last
        counter += 1
    return out[:length]


def _hawk(method: str, url: str, token_id: str, key: bytes, body: bytes = b"") -> str:
    p = urlsplit(url)
    ts = str(int(time.time()))
    nonce = _b64(secrets.token_bytes(6), True)
    path = p.path + (("?" + p.query) if p.query else "")
    payload_hash = ""
    if body:
        ph = hashlib.sha256(b"hawk.1.payload\napplication/json\n" + body + b"\n").digest()
        payload_hash = _b64(ph)
    normalized = f"hawk.1.header\n{ts}\n{nonce}\n{method.upper()}\n{path}\n{p.hostname}\n{p.port or 443}\n{payload_hash}\n\n"
    mac = _b64(hmac.new(key, normalized.encode(), hashlib.sha256).digest())
    header = f'Hawk id="{token_id}", ts="{ts}", nonce="{nonce}", mac="{mac}"'
    if payload_hash:
        header += f', hash="{payload_hash}"'
    return header


def _session_creds(session_hex: str) -> tuple[str, bytes]:
    raw = bytes.fromhex(session_hex)
    expanded = _hkdf(raw, b"identity.mozilla.com/picl/v1/sessionToken", 64)
    return expanded[:32].hex(), expanded[32:]


class FirefoxAccount:
    """Firefox Accounts OAuth and Guardian token/quota client."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / "account.json"
        self.http = httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "identity", "Cache-Control": "max-age=0"},
            follow_redirects=False,
        )

    def load(self) -> dict | None:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None

    def save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
        os.chmod(self.path, 0o600)

    async def _hawk_json(self, url: str, method: str, session: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload or {}, separators=(",", ":")).encode() if method != "GET" else b""
        token_id, key = _session_creds(session)
        headers = {"Authorization": _hawk(method, url, token_id, key, body)}
        if method != "GET":
            headers["Content-Type"] = "application/json"
        response = await self.http.request(method, url, content=body if method != "GET" else None, headers=headers)
        if response.status_code == 406:
            raise AuthError("Firefox Accounts returned HTTP 406 (anti-bot challenge); try a different network or sign in again later.")
        if not response.is_success:
            raise AuthError(f"Firefox Accounts rejected the sign-in request (HTTP {response.status_code}).")
        try:
            return response.json()
        except ValueError as exc:
            raise AuthError("Firefox Accounts returned an invalid response.") from exc

    async def sign_in_with_session_token(self, session_token: str) -> dict:
        token = "".join(session_token.split()).strip('"').lower()
        if len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token):
            raise AuthError("A verified Firefox Accounts session token is required (64 hexadecimal characters).")
        session = await self.session_status(token)
        if not session["verified"]:
            raise AuthError("The Firefox Accounts session is not verified. Complete the official browser sign-in first.")
        try:
            verifier = _b64(secrets.token_bytes(32), True)
            challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest(), True)
            state = _b64(secrets.token_bytes(16), True)
            auth = await self._hawk_json(FXA_AUTH, "POST", token, {
                "client_id": FXA_CLIENT_ID,
                "response_type": "code",
                "scope": FXA_SCOPE,
                "state": state,
                "access_type": "offline",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            })
            code = str(auth.get("code", ""))
            if not code or auth.get("state") != state:
                raise AuthError("Firefox Accounts returned an invalid OAuth response.")
            payload = {
                "client_id": FXA_CLIENT_ID,
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            }
            result = await self._token_request(payload)
            if not result.get("access_token"):
                raise AuthError("Firefox Accounts did not issue an access token.")
            data = {
                "access_token": result["access_token"],
                "refresh_token": result.get("refresh_token"),
                "expires_at": int(time.time()) + int(result.get("expires_in", 3600)),
            }
            self.save(data)
            return await self.quota()
        finally:
            # The temporary browser session is only a bridge credential; persist OAuth tokens instead.
            await self.destroy_session(token)

    async def _token_request(self, payload: dict) -> dict:
        last_error = None
        for url in (FXA_TOKEN, FXA_TOKEN_FALLBACK):
            try:
                r = await self.http.post(url, json=payload, headers={"Content-Type": "application/json"})
                if r.status_code == 406:
                    raise AuthError("Firefox Accounts returned HTTP 406 (anti-bot challenge); try a different network or sign in again later.")
                if r.is_success:
                    return r.json()
                last_error = f"HTTP {r.status_code}"
                if r.status_code not in (404, 429, 502, 503):
                    break
            except httpx.HTTPError as exc:
                last_error = str(exc)
        raise AuthError(f"Could not exchange the Firefox Accounts login ( {last_error or 'network error'} ).")

    async def session_status(self, session_token: str) -> dict:
        token = "".join(session_token.split()).strip('"').lower()
        if len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token):
            raise AuthError("Firefox Accounts browser session was invalid.")
        result = await self._hawk_json(FXA_VERIFY, "GET", token)
        return {"verified": bool(result.get("verified")), "email": str(result.get("email") or "")}

    async def destroy_session(self, session_token: str) -> None:
        token = "".join(session_token.split()).strip('"').lower()
        if len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token):
            return
        try:
            await self._hawk_json(FXA_DESTROY, "POST", token, {})
        except Exception:
            pass

    async def access_token(self) -> str:
        data = self.load()
        if not data:
            raise AuthError("Sign in to Firefox Accounts first.")
        if int(data.get("expires_at", 0)) <= int(time.time()) + 120:
            rt = data.get("refresh_token")
            if not rt:
                raise AuthError("Firefox Accounts session expired; sign in again.")
            result = await self._token_request({
                "client_id": FXA_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "scope": FXA_SCOPE,
            })
            data["access_token"] = result.get("access_token", "")
            data["refresh_token"] = result.get("refresh_token") or rt
            data["expires_at"] = int(time.time()) + int(result.get("expires_in", 3600))
            self.save(data)
        return str(data["access_token"])

    async def proxy_pass(self) -> dict:
        token = await self.access_token()
        r = await self.http.get(f"{GUARDIAN}/api/v1/fpn/token", headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json", "Cache-Control": "max-age=0"})
        if r.status_code == 406:
            raise AuthError("Mozilla Guardian returned HTTP 406 (anti-bot challenge).")
        if r.status_code == 429:
            raise AuthError("Mozilla Guardian rate-limited this account or its VPN quota is exhausted.")
        if not r.is_success:
            raise AuthError(f"Mozilla Guardian did not issue a proxy pass (HTTP {r.status_code}).")
        body = r.json()
        if not body.get("token"):
            raise AuthError("Mozilla Guardian response contained no proxy token.")
        return {"token": body["token"], "expires_at": body.get("expires_at") or _jwt_exp(body["token"]),
                "quota_remaining": _header_int(r, "X-Quota-Remaining", "Quota-Remaining"),
                "quota_limit": _header_int(r, "X-Quota-Limit", "Quota-Limit"),
                "quota_reset": _header_int(r, "X-Quota-Reset", "Quota-Reset")}

    async def quota(self) -> dict:
        token = await self.access_token()
        r = await self.http.get(f"{GUARDIAN}/api/v1/fpn/status", headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json", "Cache-Control": "max-age=0"})
        if r.status_code == 406:
            raise AuthError("Mozilla Guardian returned HTTP 406 (anti-bot challenge).")
        if not r.is_success:
            # Some entitlements only expose quota on the token response.
            try:
                return await self.proxy_pass()
            except Exception:
                raise AuthError(f"Could not read Firefox VPN quota (HTTP {r.status_code}).")
        try:
            body = r.json()
        except ValueError as exc:
            raise AuthError("Mozilla Guardian returned an invalid quota response.") from exc
        return {
            "quota_remaining": _first(body, "quota_remaining", "quotaRemaining", "remaining_bytes", "remainingBytes"),
            "quota_limit": _first(body, "quota_limit", "quotaLimit", "max_bytes", "maxBytes"),
            "limited_bandwidth": _first(body, "limited_bandwidth", "limitedBandwidth"),
            "quota_reset": _first(body, "quota_reset", "quotaReset", "reset_at", "resetAt"),
        }

    async def logout(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        finally:
            try:
                tokenfile = self.state_dir / "bearer.token"
                tokenfile.write_text("")
                os.chmod(tokenfile, 0o600)
            except OSError:
                pass



def _jwt_exp(token: str) -> int | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    try:
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode()))
        return int(payload["exp"]) if payload.get("exp") else None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _header_int(response: httpx.Response, *names: str) -> int | None:
    for name in names:
        try:
            value = response.headers.get(name)
            if value is not None:
                return int(value)
        except ValueError:
            pass
    return None


def _first(body: dict, *names: str):
    for name in names:
        if body.get(name) is not None:
            return body[name]
    return None
