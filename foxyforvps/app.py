from __future__ import annotations

import asyncio
import hmac
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import AuthError, FirefoxAccount
from .engine import write_config
from .fxa_password_login import LoginRejected, start_password_login, verify_login_step
from .servers import DirectoryError, fetch_locations

STATE_DIR = Path(os.getenv("FOXY_STATE_DIR", "/var/lib/foxyforvps"))
ETC_DIR = Path(os.getenv("FOXY_ETC_DIR", "/etc/foxyforvps"))
CORE_CONFIG = Path(os.getenv("FOXY_CORE_CONFIG", "/etc/foxyforvps/sing-box.json"))
TOKEN_FILE = Path(os.getenv("FOXY_TOKEN_FILE", "/var/lib/foxyforvps/bearer.token"))
CORE_SERVICE = os.getenv("FOXY_CORE_SERVICE", "foxyforvps-core")
ADMIN_USER = os.getenv("FOXY_ADMIN_USER", "admin")
ADMIN_PASSWORD_FILE = Path(os.getenv("FOXY_ADMIN_PASSWORD_FILE", "/etc/foxyforvps/admin-password"))
PUBLIC_IPS_FILE = Path(os.getenv("FOXY_PUBLIC_IPS_FILE", "/etc/foxyforvps/public-ips"))
STATE_FILE = STATE_DIR / "settings.json"
QUOTA_FILE = STATE_DIR / "quota.json"
security = HTTPBasic(auto_error=False)
_TLS_DNS_CACHE: dict[str, tuple[float, frozenset[str]]] = {}
_TLS_DNS_SEMAPHORE = asyncio.Semaphore(8)


def _normalize_public_domain(value: str) -> str | None:
    name = value.strip().rstrip(".").lower()
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if not name or len(name) > 253 or "." not in name:
        return None
    try:
        ipaddress.ip_address(name)
        return None
    except ValueError:
        pass
    labels = name.split(".")
    label_re = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    tld = labels[-1]
    if len(tld) < 2 or not (tld.isalpha() or tld.startswith("xn--")) or any(not label_re.fullmatch(label) for label in labels):
        return None
    if name in {"localhost", "local", "internal", "home.arpa"}:
        return None
    return name


def _lookup_public_ips_sync(domain: str) -> frozenset[str]:
    result: set[str] = set()
    for answer in socket.getaddrinfo(domain, None, type=socket.SOCK_STREAM):
        raw = answer[4][0].split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if address.is_global:
            result.add(str(address))
    return frozenset(result)


async def _lookup_public_ips(domain: str) -> frozenset[str]:
    now = time.monotonic()
    cached = _TLS_DNS_CACHE.get(domain)
    if cached and cached[0] > now:
        return cached[1]
    try:
        async with _TLS_DNS_SEMAPHORE:
            result = await asyncio.wait_for(asyncio.to_thread(_lookup_public_ips_sync, domain), timeout=3.0)
    except (OSError, asyncio.TimeoutError, UnicodeError):
        result = frozenset()
    _TLS_DNS_CACHE[domain] = (now + (60 if result else 10), result)
    if len(_TLS_DNS_CACHE) > 1024:
        expired = [key for key, (expires, _) in _TLS_DNS_CACHE.items() if expires <= now]
        for key in expired:
            _TLS_DNS_CACHE.pop(key, None)
        while len(_TLS_DNS_CACHE) > 1024:
            _TLS_DNS_CACHE.pop(next(iter(_TLS_DNS_CACHE)))
    return result


def _allowed_public_ips() -> set[str]:
    result = set()
    try:
        for line in PUBLIC_IPS_FILE.read_text().splitlines():
            try:
                address = ipaddress.ip_address(line.strip())
            except ValueError:
                continue
            if address.is_global:
                result.add(str(address))
    except OSError:
        pass
    return result


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def _save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def _state() -> dict:
    state = _read_json(STATE_FILE, {"locations": {}})
    if not isinstance(state, dict):
        state = {"locations": {}}
    locations = state.setdefault("locations", {})
    changed = False
    if isinstance(locations, dict):
        for settings in locations.values():
            if not isinstance(settings, dict):
                continue
            for key in ("username", "password", "proxy_username", "proxy_password"):
                if key in settings:
                    settings.pop(key, None)
                    changed = True
    if changed:
        _save_json(STATE_FILE, state)
    return state


def _password() -> str:
    try:
        return ADMIN_PASSWORD_FILE.read_text().strip()
    except OSError:
        return os.getenv("FOXY_ADMIN_PASSWORD", "")


def _password_matches(candidate: str) -> bool:
    stored = _password()
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt_hex, digest_hex = stored.split("$", 3)
            digest = hashlib.pbkdf2_hmac("sha256", candidate.encode(), bytes.fromhex(salt_hex), int(rounds))
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (ValueError, TypeError):
            return False
    return bool(stored) and hmac.compare_digest(candidate.encode(), stored.encode())


def _hash_password(password: str) -> str:
    rounds = 310_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


async def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not credentials or not (
        hmac.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
        and _password_matches(credentials.password)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Basic"})


account = FirefoxAccount(STATE_DIR)
locations_cache: list[dict] = []
cache_at = 0.0
refresh_task: asyncio.Task | None = None
fxa_login_lock = asyncio.Lock()
login_attempts: dict[str, dict] = {}
LOGIN_ATTEMPT_TTL = 15 * 60
LOGIN_ATTEMPT_LIMIT = 16


async def _directory(force: bool = False) -> list[dict]:
    global locations_cache, cache_at
    if force or not locations_cache or time.time() - cache_at > 3600:
        locations_cache = await fetch_locations()
        cache_at = time.time()
    return locations_cache


def _write_bearer(value: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = TOKEN_FILE.with_suffix(".tmp")
    temp.write_text(value)
    os.chmod(temp, 0o600)
    temp.replace(TOKEN_FILE)
    os.chmod(TOKEN_FILE, 0o600)


def _apply_core(locations: list[dict] | None = None) -> None:
    if not account.load():
        return
    current = locations or locations_cache
    write_config(CORE_CONFIG, current, _state())
    try:
        result = subprocess.run(["systemctl", "restart", CORE_SERVICE], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "systemd restart failed")
    except FileNotFoundError as exc:
        raise RuntimeError("systemd is unavailable; install this application on Ubuntu with systemd.") from exc


async def _refresh_loop():
    while True:
        try:
            if account.load():
                pass_data = await account.proxy_pass()
                _write_bearer(pass_data["token"])
                _save_json(QUOTA_FILE, {**pass_data, "checked_at": int(time.time())})
                # Confirm the status endpoint too; it often supplies the authoritative remaining quota.
                try:
                    quota = await account.quota()
                    merged = {**pass_data, **{k: v for k, v in quota.items() if v is not None}, "checked_at": int(time.time())}
                    _save_json(QUOTA_FILE, merged)
                except AuthError:
                    pass
                # Start the core after login if it is not already running; token rotation is
                # picked up by the patched sing-box process without restarting live tunnels.
                try:
                    active = subprocess.run(["systemctl", "is-active", "--quiet", CORE_SERVICE], timeout=3).returncode == 0
                    if not active:
                        _apply_core(await _directory())
                except Exception:
                    pass
                expires = pass_data.get("expires_at")
                try:
                    delay = max(45, min(300, int(expires) - int(time.time()) - 45)) if expires else 240
                except (ValueError, TypeError):
                    delay = 240
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(20)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(90)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global refresh_task
    try:
        await _directory()
    except Exception:
        pass
    refresh_task = asyncio.create_task(_refresh_loop())
    yield
    if refresh_task:
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass
    await account.http.aclose()


app = FastAPI(title="FoxyforVPS", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def same_origin_guard(request: Request, call_next):
    # All writes must come from the panel's own origin; this prevents cross-site
    # requests using cached HTTP Basic credentials on a public hostname.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        parsed = urlsplit(origin) if origin else None
        host = request.headers.get("host", "")
        if not parsed or parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host.lower():
            return JSONResponse({"detail": "Same-origin request required."}, status_code=403)
    app_response = await call_next(request)
    return app_response


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/api/tls/authorize")
async def authorize_dynamic_certificate(request: Request, domain: str = ""):
    # Uvicorn is configured with --no-proxy-headers so this is the TCP peer,
    # not a client-supplied X-Forwarded-For value. Only local Caddy may ask.
    peer = request.client.host if request.client else ""
    if peer not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "Local TLS issuer required.")
    normalized = _normalize_public_domain(domain)
    allowed = _allowed_public_ips()
    if not normalized or not allowed:
        raise HTTPException(403, "Domain is not authorized for this VPS.")
    resolved = await _lookup_public_ips(normalized)
    if not resolved or not resolved.issubset(allowed):
        raise HTTPException(403, "Domain DNS must point only to this VPS.")
    return Response(status_code=204)


class FirefoxCredentialsInput(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    unblock_code: str = Field(default="", max_length=64)


class LoginVerificationInput(BaseModel):
    attempt_id: str = Field(min_length=20, max_length=128)
    code: str = Field(default="", max_length=64)
    confirmed: bool = False


class AdminPasswordInput(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)


class LocationUpdate(BaseModel):
    enabled: Optional[bool] = None
    port: Optional[int] = Field(default=None, ge=1024, le=65535)
    server_index: Optional[int] = Field(default=None, ge=0, le=1000)


@app.get("/")
async def index(_=Depends(require_admin)):
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/state")
async def get_state(_=Depends(require_admin)):
    try:
        countries = await _directory()
    except DirectoryError as exc:
        raise HTTPException(502, str(exc)) from exc
    state = _state()
    configured = state.setdefault("locations", {})
    for index, item in enumerate(countries):
        code = item["code"]
        row = configured.setdefault(code, {})
        row.setdefault("enabled", False)
        row.setdefault("port", 2020 + index)
        row.setdefault("node", (item["servers"] or [None])[0])
    _save_json(STATE_FILE, state)
    quota = _read_json(QUOTA_FILE, {})
    running = False
    try:
        running = subprocess.run(["systemctl", "is-active", "--quiet", CORE_SERVICE], timeout=3).returncode == 0
    except Exception:
        pass
    return {
        "account_connected": bool(account.load()),
        "quota": quota,
        "core_running": running,
        "panel_bind": "127.0.0.1",
        "locations": [
            {**item, "enabled": bool(configured[item["code"]].get("enabled")),
             "port": configured[item["code"]]["port"],
             "node": configured[item["code"]].get("node") or (item["servers"] or [None])[0]}
            for item in countries
        ],
    }


@app.post("/api/account/login-password")
async def login_with_password(data: FirefoxCredentialsInput, _=Depends(require_admin)):
    email = data.email.strip()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        data.password = ""
        raise HTTPException(422, "ایمیل معتبر Firefox را وارد کن.")
    password = data.password
    unblock_code = data.unblock_code
    data.password = ""
    data.unblock_code = ""
    try:
        async with fxa_login_lock:
            result = await start_password_login(account.http, email, password, unblock_code)
            stage = result["stage"]
            if stage == "unblock_code":
                return {"ok": False, "stage": stage, "email": result["email"], "message": result["message"]}
            if stage != "verified":
                _prune_login_attempts()
                if len(login_attempts) >= LOGIN_ATTEMPT_LIMIT:
                    raise HTTPException(429, "تلاش‌های ورود موقت زیادی باز است؛ کمی صبر کن و دوباره شروع کن.")
                attempt_id = secrets.token_urlsafe(24)
                login_attempts[attempt_id] = {
                    "email": result["email"],
                    "session_token": result["session_token"],
                    "stage": stage,
                    "created": time.monotonic(),
                    "tries": 0,
                }
                return {"ok": False, "stage": stage, "attempt_id": attempt_id, "email": result["email"], "message": result["message"]}
            quota = await _finish_account_login(result["session_token"])
            return {"ok": True, "quota": quota}
    except LoginRejected as exc:
        raise HTTPException(400, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(500, f"Authentication succeeded, but tunnel engine did not start: {exc}") from exc
    finally:
        data.password = ""
        data.unblock_code = ""
        password = ""


def _prune_login_attempts() -> None:
    now = time.monotonic()
    for attempt_id, attempt in list(login_attempts.items()):
        if now - attempt["created"] > LOGIN_ATTEMPT_TTL:
            login_attempts.pop(attempt_id, None)


async def _finish_account_login(session_token: str) -> dict:
    quota = await account.sign_in_with_session_token(session_token)
    pass_data = await account.proxy_pass()
    _save_json(QUOTA_FILE, {**pass_data, **{k: v for k, v in quota.items() if v is not None}, "checked_at": int(time.time())})
    _write_bearer(pass_data["token"])
    _apply_core(await _directory())
    return quota


@app.post("/api/account/login-verify")
async def verify_account_login(data: LoginVerificationInput, _=Depends(require_admin)):
    _prune_login_attempts()
    attempt = login_attempts.get(data.attempt_id)
    if not attempt:
        raise HTTPException(404, "مرحلهٔ ورود پیدا نشد یا منقضی شده است؛ دوباره وارد شو.")
    stage = attempt["stage"]
    if stage == "email_link" and not data.confirmed:
        raise HTTPException(400, "ابتدا لینک تأیید Firefox را باز کن.")
    try:
        async with fxa_login_lock:
            confirmed = await verify_login_step(account.http, attempt["session_token"], stage, data.code)
            if not confirmed:
                raise HTTPException(409, "Firefox هنوز تأیید ایمیل را ثبت نکرده است؛ پس از کلیک لینک دوباره ادامه بده.")
            quota = await _finish_account_login(attempt["session_token"])
            login_attempts.pop(data.attempt_id, None)
            return {"ok": True, "quota": quota}
    except LoginRejected as exc:
        attempt["tries"] += 1
        if attempt["tries"] >= 5:
            login_attempts.pop(data.attempt_id, None)
            raise HTTPException(400, "تعداد تلاش‌های کد تأیید تمام شد؛ ورود را از ابتدا شروع کن.") from exc
        raise HTTPException(400, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        login_attempts.pop(data.attempt_id, None)
        raise HTTPException(500, f"ورود موفق شد، اما موتور تونل اجرا نشد: {exc}") from exc


@app.delete("/api/account/login-attempt/{attempt_id}")
async def cancel_account_login(attempt_id: str, _=Depends(require_admin)):
    login_attempts.pop(attempt_id, None)
    return {"ok": True}


@app.post("/api/admin/password")
async def change_admin_password(data: AdminPasswordInput, _=Depends(require_admin)):
    new_password = data.new_password
    if _password_matches(new_password):
        raise HTTPException(400, "رمز پنل جدید باید با رمز فعلی متفاوت باشد.")
    if any(ord(char) < 32 or ord(char) == 127 for char in new_password):
        data.new_password = ""
        raise HTTPException(400, "از نویسه‌های کنترلی در رمز پنل استفاده نکن.")
    ADMIN_PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = ADMIN_PASSWORD_FILE.with_suffix(".tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_hash_password(new_password))
        os.chmod(temp, 0o600)
        os.replace(temp, ADMIN_PASSWORD_FILE)
        os.chmod(ADMIN_PASSWORD_FILE, 0o600)
    finally:
        data.new_password = ""
        temp.unlink(missing_ok=True)
    return {"ok": True, "reauthenticate": True}


@app.post("/api/account/logout")
async def logout(_=Depends(require_admin)):
    await account.logout()
    QUOTA_FILE.unlink(missing_ok=True)
    try:
        subprocess.run(["systemctl", "stop", CORE_SERVICE], timeout=20)
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/directory/refresh")
async def refresh_directory(_=Depends(require_admin)):
    try:
        countries = await _directory(force=True)
        if account.load():
            _apply_core(countries)
        return {"ok": True, "count": len(countries)}
    except (DirectoryError, RuntimeError) as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/quota/refresh")
async def refresh_quota(_=Depends(require_admin)):
    try:
        quota = await account.quota()
        pass_data = await account.proxy_pass()
        _write_bearer(pass_data["token"])
        quota = {**pass_data, **{k: v for k, v in quota.items() if v is not None}, "checked_at": int(time.time())}
        _save_json(QUOTA_FILE, quota)
        return quota
    except AuthError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/locations/{code}")
async def update_location(code: str, data: LocationUpdate, _=Depends(require_admin)):
    try:
        countries = await _directory()
    except DirectoryError as exc:
        raise HTTPException(502, str(exc)) from exc
    code = code.upper()
    country = next((x for x in countries if x["code"] == code), None)
    if not country:
        raise HTTPException(404, "Location not found in Mozilla's current directory")
    if data.enabled and not account.load():
        raise HTTPException(401, "Connect a Firefox Account session before enabling a location.")
    state = _state()
    settings = state.setdefault("locations", {}).setdefault(code, {})
    if data.port is not None:
        for other_code, other in state["locations"].items():
            if other_code != code and other.get("enabled") and int(other.get("port", 0)) == data.port:
                raise HTTPException(409, "That SOCKS5 port is already assigned to another enabled location.")
        settings["port"] = data.port
    if data.server_index is not None:
        if data.server_index >= len(country["servers"]):
            raise HTTPException(400, "Invalid server selection")
        settings["node"] = country["servers"][data.server_index]
    if data.enabled is not None:
        if data.enabled:
            selected_port = int(settings.get("port", 2020 + countries.index(country)))
            for other_code, other in state["locations"].items():
                if other_code != code and other.get("enabled") and int(other.get("port", 0)) == selected_port:
                    raise HTTPException(409, "That SOCKS5 port is already assigned to another enabled location.")
            if selected_port < 1024:
                settings["port"] = 2020 + countries.index(country)
        settings["enabled"] = bool(data.enabled)
    _save_json(STATE_FILE, state)
    if account.load():
        try:
            _apply_core(countries)
        except RuntimeError as exc:
            raise HTTPException(503, f"Saved settings, but tunnel could not be restarted: {exc}") from exc
    return {"ok": True}


@app.get("/api/health")
async def health():
    # Intentionally unauthenticated for systemd's local health checks only.
    return {"ok": True}
# placeholder
