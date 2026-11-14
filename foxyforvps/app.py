from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import os
import secrets
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import AuthError, FirefoxAccount
from .engine import write_config
from .servers import DirectoryError, fetch_locations

STATE_DIR = Path(os.getenv("FOXY_STATE_DIR", "/var/lib/foxyforvps"))
ETC_DIR = Path(os.getenv("FOXY_ETC_DIR", "/etc/foxyforvps"))
CORE_CONFIG = Path(os.getenv("FOXY_CORE_CONFIG", "/etc/foxyforvps/sing-box.json"))
TOKEN_FILE = Path(os.getenv("FOXY_TOKEN_FILE", "/var/lib/foxyforvps/bearer.token"))
CORE_SERVICE = os.getenv("FOXY_CORE_SERVICE", "foxyforvps-core")
ADMIN_USER = os.getenv("FOXY_ADMIN_USER", "admin")
ADMIN_PASSWORD_FILE = Path(os.getenv("FOXY_ADMIN_PASSWORD_FILE", "/etc/foxyforvps/admin-password"))
STATE_FILE = STATE_DIR / "settings.json"
QUOTA_FILE = STATE_DIR / "quota.json"
security = HTTPBasic(auto_error=False)


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
    return _read_json(STATE_FILE, {"locations": {}})


def _password() -> str:
    try:
        return ADMIN_PASSWORD_FILE.read_text().strip()
    except OSError:
        return os.getenv("FOXY_ADMIN_PASSWORD", "")


async def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    expected = _password()
    if not credentials or not expected or not (
        hmac.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
        and hmac.compare_digest(credentials.password.encode(), expected.encode())
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers={"WWW-Authenticate": "Basic"})


account = FirefoxAccount(STATE_DIR)
locations_cache: list[dict] = []
cache_at = 0.0
refresh_task: asyncio.Task | None = None
pending_pair_hash: str | None = None
pending_pair_expires: float = 0.0


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
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"moz-extension://.*",
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def same_origin_guard(request: Request, call_next):
    # The extension's one-time pairing endpoint is separately protected by a
    # random, single-use code and strict CORS. All other writes must come from
    # the panel's own origin; this prevents cross-site requests using cached
    # HTTP Basic credentials on a publicly reachable hostname.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path != "/api/account/browser-session":
        origin = request.headers.get("origin")
        parsed = urlsplit(origin) if origin else None
        host = request.headers.get("host", "")
        if not parsed or parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host.lower():
            return JSONResponse({"detail": "Same-origin request required."}, status_code=403)
    app_response = await call_next(request)
    return app_response


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class SessionTokenInput(BaseModel):
    session_token: str = Field(min_length=64, max_length=128)


class PairSessionInput(BaseModel):
    pair_code: str = Field(min_length=32, max_length=128)
    session_token: str = Field(min_length=64, max_length=128)


class LocationUpdate(BaseModel):
    enabled: Optional[bool] = None
    port: Optional[int] = Field(default=None, ge=1024, le=65535)
    server_index: Optional[int] = Field(default=None, ge=0, le=1000)
    proxy_username: Optional[str] = Field(default=None, max_length=64)
    proxy_password: Optional[str] = Field(default=None, max_length=128)


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
        row.setdefault("username", "proxy")
        row.setdefault("password", secrets.token_urlsafe(18))
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
             "proxy_username": configured[item["code"]].get("username", "proxy"),
             "proxy_password": configured[item["code"]].get("password", ""),
             "node": configured[item["code"]].get("node") or (item["servers"] or [None])[0]}
            for item in countries
        ],
    }


@app.post("/api/account/login")
async def login(data: SessionTokenInput, _=Depends(require_admin)):
    try:
        quota = await account.sign_in_with_session_token(data.session_token)
        _save_json(QUOTA_FILE, {**quota, "checked_at": int(time.time())})
        _write_bearer((await account.proxy_pass())["token"])
        try:
            _apply_core(await _directory())
        except Exception as exc:
            raise HTTPException(500, f"Authentication succeeded, but tunnel engine did not start: {exc}") from exc
        return {"ok": True, "quota": quota}
    except AuthError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/account/pair")
async def create_pair(_=Depends(require_admin)):
    global pending_pair_hash, pending_pair_expires
    code = secrets.token_urlsafe(32)
    pending_pair_hash = hashlib.sha256(code.encode()).hexdigest()
    pending_pair_expires = time.time() + 600
    return {"pair_code": code, "expires_in": 600, "login_url": "https://accounts.firefox.com/?context=fx_desktop_v3&service=sync&action=email"}


@app.post("/api/account/browser-session")
async def browser_session(data: PairSessionInput):
    global pending_pair_hash, pending_pair_expires
    supplied = hashlib.sha256(data.pair_code.encode()).hexdigest()
    if (not pending_pair_hash or time.time() > pending_pair_expires
            or not hmac.compare_digest(supplied, pending_pair_hash)):
        raise HTTPException(403, "Pairing code is invalid, expired, or already used.")
    pending_pair_hash = None
    pending_pair_expires = 0
    try:
        quota = await account.sign_in_with_session_token(data.session_token)
        pass_data = await account.proxy_pass()
        _save_json(QUOTA_FILE, {**pass_data, **{k: v for k, v in quota.items() if v is not None}, "checked_at": int(time.time())})
        _write_bearer(pass_data["token"])
        _apply_core(await _directory())
        return {"ok": True, "quota": quota}
    except AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, f"Login was accepted, but tunnel startup failed: {exc}") from exc


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
    if data.proxy_username is not None:
        if not data.proxy_username or ":" in data.proxy_username:
            raise HTTPException(400, "Proxy username must be non-empty and must not contain ':'")
        settings["username"] = data.proxy_username
    if data.proxy_password is not None:
        if len(data.proxy_password.encode()) < 12:
            raise HTTPException(400, "Use a proxy password of at least 12 bytes")
        settings["password"] = data.proxy_password
    if data.enabled is not None:
        if data.enabled:
            selected_port = int(settings.get("port", 2020 + countries.index(country)))
            for other_code, other in state["locations"].items():
                if other_code != code and other.get("enabled") and int(other.get("port", 0)) == selected_port:
                    raise HTTPException(409, "That SOCKS5 port is already assigned to another enabled location.")
            settings.setdefault("username", "proxy")
            settings.setdefault("password", secrets.token_urlsafe(18))
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
