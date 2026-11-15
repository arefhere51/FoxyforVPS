from __future__ import annotations

import hashlib
import json
import re

import httpx

from .auth import AuthError, _hawk, _session_creds

FXA_V1 = "https://api.accounts.firefox.com/v1"
LOGIN_URL = f"{FXA_V1}/account/login"
UNBLOCK_URL = f"{FXA_V1}/account/login/send_unblock_code"
VERIFY_CODE_URL = f"{FXA_V1}/session/verify_code"
VERIFY_TOTP_URL = f"{FXA_V1}/session/verify/totp"
SESSION_STATUS_URL = f"{FXA_V1}/recovery_email/status"
DESTROY_URL = f"{FXA_V1}/session/destroy"
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
PROTOCOL = b"identity.mozilla.com/picl/v1/"
FIREFOX_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0"


class LoginRejected(AuthError):
    """A user-facing, sanitized Firefox Accounts sign-in error."""


def derive_auth_pw(email: str, password: str) -> str:
    """Derive FxA authPW; the plaintext password is not sent in the API body."""
    salt = PROTOCOL + b"quickStretch:" + email.encode("utf-8")
    stretched = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 1000, 32)
    auth_pw = _hkdf_sha256(stretched, b"\x00", PROTOCOL + b"authPW", 32)
    return auth_pw.hex()


def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    # RFC 5869. The one-byte zero salt is the value used by FxA's quickStretch flow.
    import hmac

    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    output = bytearray()
    previous = b""
    counter = 1
    while len(output) < length:
        previous = hmac.new(prk, previous + info + bytes((counter,)), hashlib.sha256).digest()
        output.extend(previous)
        counter += 1
    return bytes(output[:length])


def _error_payload(response: httpx.Response) -> tuple[int, str, str]:
    try:
        body = response.json()
    except ValueError:
        body = {}
    try:
        errno = int(body.get("errno", body.get("code", 0)) or 0)
    except (TypeError, ValueError):
        errno = 0
    message = str(body.get("message", "")) if isinstance(body, dict) else ""
    email = str(body.get("email", "")) if isinstance(body, dict) else ""
    return errno, message, email


def _raise_api_error(response: httpx.Response) -> None:
    if response.status_code == 406:
        raise LoginRejected(
            "Firefox Accounts returned HTTP 406 (security challenge). The direct API request was stopped; no CAPTCHA or anti-bot challenge was bypassed."
        )
    errno, _message, _email = _error_payload(response)
    if response.status_code == 429 or errno == 114:
        raise LoginRejected("فایرفاکس تعداد تلاش‌ها را زیاد تشخیص داد. کمی صبر کن و دوباره امتحان کن.")
    messages = {
        102: "برای این ایمیل حساب Firefox پیدا نشد.",
        103: "ایمیل یا گذرواژهٔ Firefox درست نیست.",
        105: "کد تأیید پذیرفته نشد یا منقضی شده است.",
        107: "درخواست ورود با این روش تأیید پذیرفته نشد.",
        125: "Firefox ورود را مسدود نگه داشت؛ کد رفع مسدودی را تازه بگیر یا کمی صبر کن.",
        127: "کد رفع مسدودی Firefox پذیرفته نشد.",
        152: "کد TOTP پذیرفته نشد.",
        183: "کد تأیید نامعتبر یا منقضی است.",
        210: "این حساب گذرواژه ندارد؛ ابتدا برای حساب Firefox گذرواژه تعیین کن.",
    }
    if errno in messages:
        raise LoginRejected(messages[errno])
    if response.status_code >= 500:
        raise LoginRejected("سرویس Firefox Accounts موقتاً خطا داد؛ بعداً دوباره تلاش کن.")
    raise LoginRejected(f"Firefox Accounts درخواست را نپذیرفت (HTTP {response.status_code}, کد {errno or 'نامشخص'}).")


def _headers() -> dict[str, str]:
    return {
        "User-Agent": FIREFOX_UA,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Content-Type": "application/json",
        "Cache-Control": "max-age=0",
    }


async def _send_login(client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    try:
        return await client.post(LOGIN_URL, json=payload, headers=_headers())
    except httpx.HTTPError:
        raise LoginRejected("اتصال مستقیم به Firefox Accounts API برقرار نشد. شبکهٔ VPS را بررسی کن.") from None


async def _send_unblock_code(client: httpx.AsyncClient, email: str) -> None:
    try:
        response = await client.post(UNBLOCK_URL, json={"email": email}, headers=_headers())
    except httpx.HTTPError:
        raise LoginRejected("درخواست کد رفع مسدودی به Firefox Accounts نرسید.") from None
    if not response.is_success:
        _raise_api_error(response)


async def start_password_login(
    client: httpx.AsyncClient,
    email: str,
    password: str,
    unblock_code: str = "",
) -> dict:
    """Start a direct FxA API login and return only a stage plus a session token."""
    email = email.strip()
    if not email or not password:
        raise LoginRejected("ایمیل و گذرواژهٔ Firefox را وارد کن.")

    payload = {
        "email": email,
        "authPW": derive_auth_pw(email, password),
        "verificationMethod": "email-2fa",
    }
    if unblock_code:
        payload["unblockCode"] = "".join(unblock_code.split()).upper()

    response = await _send_login(client, payload)
    if response.status_code == 400:
        errno, _message, corrected_email = _error_payload(response)
        if errno == 120 and corrected_email and corrected_email != email:
            payload["originalLoginEmail"] = email
            payload["email"] = corrected_email
            payload["authPW"] = derive_auth_pw(corrected_email, password)
            response = await _send_login(client, payload)
    if response.status_code == 400:
        errno, _message, _email = _error_payload(response)
        if errno == 107 and "verificationMethod" in payload:
            payload.pop("verificationMethod", None)
            response = await _send_login(client, payload)
    if response.status_code == 400:
        errno, _message, canonical_email = _error_payload(response)
        if errno == 125 and not unblock_code:
            await _send_unblock_code(client, canonical_email or email)
            return {
                "stage": "unblock_code",
                "email": canonical_email or email,
                "message": "Firefox ورود را غیرعادی تشخیص داد و کد رفع مسدودی فرستاد. گذرواژه و کد ایمیل‌شده را دوباره وارد کن.",
            }
    if not response.is_success:
        _raise_api_error(response)

    try:
        result = response.json()
    except ValueError:
        raise LoginRejected("پاسخ Firefox Accounts قابل‌خواندن نبود.") from None
    session_token = str(result.get("sessionToken", "")).lower()
    if not TOKEN_RE.fullmatch(session_token):
        raise LoginRejected("Firefox Accounts نشست ورود معتبر برنگرداند.")
    signed_email = str(result.get("email") or payload["email"])
    if result.get("verified") is True:
        return {"stage": "verified", "email": signed_email, "session_token": session_token}

    method = str(result.get("verificationMethod") or "email-2fa")
    if method == "email":
        stage = "email_link"
        message = "لینک تأیید ارسال‌شده از Firefox را باز کن، سپس در پنل ادامه بده."
    elif method == "totp-2fa":
        stage = "totp"
        message = "کد جاری برنامهٔ احراز هویت دومرحله‌ای را وارد کن."
    else:
        stage = "email_code"
        message = "کد تأییدی را که Firefox به ایمیل حساب فرستاده وارد کن."
    return {"stage": stage, "email": signed_email, "session_token": session_token, "message": message}


async def _hawk_json(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    session_token: str,
    payload: dict | None = None,
) -> dict:
    body = json.dumps(payload or {}, separators=(",", ":")).encode("utf-8") if method != "GET" else b""
    token_id, key = _session_creds(session_token)
    headers = _headers()
    headers["Authorization"] = _hawk(method, url, token_id, key, body)
    try:
        response = await client.request(method, url, content=body if method != "GET" else None, headers=headers)
    except httpx.HTTPError:
        raise LoginRejected("ارتباط امن با Firefox Accounts برای تأیید ورود برقرار نشد.") from None
    if not response.is_success:
        _raise_api_error(response)
    try:
        return response.json()
    except ValueError:
        if method == "POST":
            return {}
        raise LoginRejected("پاسخ وضعیت نشست Firefox نامعتبر بود.") from None


async def verify_login_step(
    client: httpx.AsyncClient,
    session_token: str,
    method: str,
    code: str = "",
) -> bool:
    """Complete email-code/TOTP verification, or check an email-link session."""
    if method == "email_link":
        result = await _hawk_json(client, SESSION_STATUS_URL, "GET", session_token)
        return result.get("verified") is True
    if not code.strip():
        raise LoginRejected("کد تأیید را وارد کن.")
    url = VERIFY_TOTP_URL if method == "totp" else VERIFY_CODE_URL
    await _hawk_json(client, url, "POST", session_token, {"code": "".join(code.split())})
    return True


async def destroy_login_session(client: httpx.AsyncClient, session_token: str) -> None:
    """Best-effort cleanup for an unexchanged temporary sign-in session."""
    await _hawk_json(client, DESTROY_URL, "POST", session_token, {})
