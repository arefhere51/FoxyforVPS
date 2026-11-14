from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://accounts.firefox.com/?context=fx_desktop_v3&service=sync&action=email"
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")

# This mirrors FoxyVPN's Android WebView bridge: answer only the WebChannel
# capability/link checks it needs, and forward the official FxA login token.
WEBCHANNEL_HOOK = r"""
(() => {
  if (window.__foxyVpsBridgeInstalled) return;
  window.__foxyVpsBridgeInstalled = true;
  window.__foxyVpsCaptured = false;
  window.__foxyVpsCapturePending = false;
  const channel = 'account_updates';
  const reply = (eventData, message, data) => {
    const response = {
      id: eventData.id || channel,
      message: { messageId: message.messageId || '', command: message.command, data }
    };
    try {
      window.dispatchEvent(new CustomEvent('WebChannelMessageToContent', {detail: response}));
      document.dispatchEvent(new CustomEvent('WebChannelMessageToContent', {detail: response}));
    } catch (_) {}
  };
  const onMessage = (event) => {
    try {
      const host = location.hostname.toLowerCase();
      if (host !== 'accounts.firefox.com' && !host.endsWith('.firefox.com')) return;
      let envelope = event.detail;
      if (typeof envelope === 'string') envelope = JSON.parse(envelope);
      if (!envelope || (envelope.id && envelope.id !== channel)) return;
      const message = envelope.message || {};
      const command = message.command || '';
      const data = message.data || {};
      if (command === 'fxaccounts:fxa_status') {
        reply(envelope, message, {capabilities: {}, signedInUser: null});
        return;
      }
      if (command === 'fxaccounts:can_link_account') {
        reply(envelope, message, {ok: true});
        return;
      }
      if (command === 'fxaccounts:login' || command === 'fxaccounts:oauth_login') {
        const token = String(data.sessionToken || data.token || '').trim().toLowerCase();
        if (/^[0-9a-f]{64}$/.test(token) && !window.__foxyVpsCaptured && !window.__foxyVpsCapturePending) {
          window.__foxyVpsCapturePending = true;
          Promise.resolve(window.__foxyVpsDeliver(token)).then(() => {
            window.__foxyVpsCaptured = true;
            window.__foxyVpsCapturePending = false;
          }).catch(() => { window.__foxyVpsCapturePending = false; });
        }
        if (message.messageId) reply(envelope, message, {ok: true});
      }
    } catch (_) {}
  };
  window.addEventListener('WebChannelMessageToChrome', onMessage);
  document.addEventListener('WebChannelMessageToChrome', onMessage);
})();
"""


class FirefoxBrowserLoginError(RuntimeError):
    pass


def _visible(locator) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except PlaywrightError:
        return False


def _submit(page) -> None:
    button = page.locator('button[type="submit"]')
    if _visible(button):
        button.first.click(timeout=10_000)
    else:
        page.keyboard.press("Enter")


def _page_failure(page) -> str:
    try:
        text = page.locator("body").inner_text(timeout=2_000).lower()
    except PlaywrightError:
        text = ""
    challenge_terms = (
        "captcha", "robot", "unusual activity", "verification code",
        "two-step", "two factor", "authenticator", "passkey", "security check",
    )
    if any(term in text for term in challenge_terms):
        return "فایرفاکس یک مرحلهٔ امنیتی مثل CAPTCHA، کد تأیید یا احراز هویت دومرحله‌ای خواست. این مرحله دور زده نشد و رمز ذخیره نشد."
    password_terms = ("incorrect password", "wrong password", "invalid password", "incorrect email or password")
    if any(term in text for term in password_terms):
        return "فایرفاکس ایمیل یا گذرواژه را نپذیرفت؛ مشخصات را بررسی کن. رمز ذخیره نشد."
    return "ورود خودکار کامل نشد؛ ممکن است مرحلهٔ امنیتی یا تغییر صفحهٔ ورود علت باشد. رمز ذخیره نشد."


def _run_capture(email: str, password: str) -> str:
    captured: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(locale="en-US", service_workers="block")
                try:
                    page = context.new_page()

                    def receive(token: str) -> None:
                        if isinstance(token, str) and TOKEN_RE.fullmatch(token.lower()):
                            captured.append(token.lower())

                    page.expose_function("__foxyVpsDeliver", receive)
                    page.add_init_script(WEBCHANNEL_HOOK)
                    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
                    if page.url.split("/", 3)[2].lower() != "accounts.firefox.com":
                        raise FirefoxBrowserLoginError("صفحهٔ ورود به میزبان غیرمنتظره‌ای منتقل شد؛ برای امنیت ورود متوقف شد.")

                    email_field = page.locator('input[type="email"], input[name*="email" i]').first
                    email_field.wait_for(state="visible", timeout=30_000)
                    email_field.fill(email)
                    _submit(page)

                    password_field = page.locator('input[type="password"]').first
                    try:
                        password_field.wait_for(state="visible", timeout=30_000)
                    except PlaywrightTimeoutError as exc:
                        raise FirefoxBrowserLoginError(_page_failure(page)) from exc
                    password_field.fill(password)
                    _submit(page)

                    try:
                        page.wait_for_function("window.__foxyVpsCaptured === true", timeout=90_000)
                    except PlaywrightTimeoutError as exc:
                        raise FirefoxBrowserLoginError(_page_failure(page)) from exc
                    if not captured:
                        raise FirefoxBrowserLoginError("فایرفاکس نشست ورود قابل‌استفاده‌ای نداد؛ رمز ذخیره نشد.")
                    return captured[-1]
                finally:
                    context.close()
            finally:
                browser.close()
    except FirefoxBrowserLoginError:
        raise
    except PlaywrightError as exc:
        # Never include browser logs, page text, request bodies, or credentials.
        raise FirefoxBrowserLoginError("مرورگر موقت نتوانست ورود را کامل کند. اتصال شبکه را بررسی و دوباره تلاش کن.") from None


def capture_firefox_session(email: str, password: str) -> str:
    """Run the temporary login browser as a dedicated unprivileged Linux user."""
    if os.geteuid() != 0:
        return _run_capture(email, password)

    user = os.getenv("FOXY_BROWSER_USER", "foxyvpsbrowser")
    home = os.getenv("FOXY_BROWSER_HOME", "/var/lib/foxyforvps-browser")
    browsers = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/foxyforvps-browsers")
    setpriv = "/usr/bin/setpriv"
    if not Path(setpriv).is_file():
        raise FirefoxBrowserLoginError("ابزار اجرای مرورگر محدود نصب نیست؛ برنامه را به‌روزرسانی کن.")
    env = {
        "HOME": home,
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONUNBUFFERED": "1",
        "PLAYWRIGHT_BROWSERS_PATH": browsers,
    }
    command = [setpriv, f"--reuid={user}", f"--regid={user}", "--init-groups", sys.executable, "-m", "foxyforvps.fxa_browser_login"]
    payload = json.dumps({"email": email, "password": password}, separators=(",", ":")).encode("utf-8")
    process = None
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd="/opt/FoxyforVPS", env=env, start_new_session=True,
        )
        stdout, stderr = process.communicate(payload, timeout=150)
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.communicate(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
        raise FirefoxBrowserLoginError("زمان ورود Firefox تمام شد؛ رمز ذخیره نشد. دوباره تلاش کن یا مرحلهٔ امنیتی را در Firefox عادی تکمیل کن.") from exc
    except OSError:
        raise FirefoxBrowserLoginError("مرورگر مجزای Firefox اجرا نشد؛ برنامه را به‌روزرسانی و سرویس را بررسی کن.") from None
    if process.returncode != 0:
        message = stderr.decode("utf-8", "replace").strip()
        if message.startswith("FOXY_LOGIN_ERROR:"):
            raise FirefoxBrowserLoginError(message.removeprefix("FOXY_LOGIN_ERROR:").strip())
        raise FirefoxBrowserLoginError("مرورگر مجزای ورود Firefox اجرا نشد؛ برنامه را به‌روزرسانی و نصب Chromium را بررسی کن.")
    token = stdout.decode("ascii", "ignore").strip().lower()
    if not TOKEN_RE.fullmatch(token):
        raise FirefoxBrowserLoginError("مرورگر موقت نشست معتبر Firefox برنگرداند؛ رمز ذخیره نشد.")
    return token


def _worker_main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read(16_384).decode("utf-8"))
        email = str(payload.get("email", "")).strip()
        password = str(payload.get("password", ""))
        if not email or not password:
            raise FirefoxBrowserLoginError("ایمیل و گذرواژهٔ Firefox را وارد کن.")
        token = _run_capture(email, password)
        sys.stdout.write(token)
        sys.stdout.flush()
        return 0
    except FirefoxBrowserLoginError as exc:
        sys.stderr.write("FOXY_LOGIN_ERROR: " + str(exc))
        return 2
    except Exception:
        sys.stderr.write("FOXY_LOGIN_ERROR: مرورگر موقت ورود با خطای غیرمنتظره متوقف شد؛ اطلاعات ورود ذخیره نشد.")
        return 3


if __name__ == "__main__":
    raise SystemExit(_worker_main())
