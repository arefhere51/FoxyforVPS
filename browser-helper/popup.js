const sendButton = document.getElementById("send");
const result = document.getElementById("result");
const loginUrl = "https://accounts.firefox.com/?service=sync&context=fx_desktop_v3&action=email";

document.getElementById("open-login").addEventListener("click", async () => {
  await browser.tabs.create({ url: loginUrl });
});

function normalizeDashboardUrl(raw) {
  let url;
  try { url = new URL(raw.trim()); }
  catch (_) { throw new Error("آدرس پنل معتبر نیست."); }
  if (url.username || url.password || url.search || url.hash || (url.pathname && url.pathname !== "/")) {
    throw new Error("فقط origin پنل را وارد کن؛ مسیر، query، رمز یا hash نداشته باشد.");
  }
  const isLoopback = url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "[::1]";
  if (url.protocol !== "https:" && !(url.protocol === "http:" && isLoopback)) {
    throw new Error("پنل عمومی باید HTTPS باشد؛ HTTP فقط برای localhost مجاز است.");
  }
  if (url.protocol === "http:" && url.port && url.port !== "8777") {
    throw new Error("برای تونل SSH محلی از http://127.0.0.1:8777 استفاده کن.");
  }
  return { origin: url.origin, isLoopback, hostname: url.hostname };
}

sendButton.addEventListener("click", async () => {
  result.textContent = "";
  sendButton.disabled = true;
  try {
    const pairCode = document.getElementById("pair").value.trim();
    if (!pairCode) throw new Error("کد یک‌بارمصرف را وارد کن.");

    const dashboard = normalizeDashboardUrl(document.getElementById("server").value);
    // Request only the HTTPS hostname entered by the user, and only after this explicit click.
    if (!dashboard.isLoopback) {
      const granted = await browser.permissions.request({ origins: [`https://${dashboard.hostname}/*`] });
      if (!granted) throw new Error("مجوز اتصال به میزبان پنل داده نشد.");
    }

    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url || new URL(tab.url).hostname !== "accounts.firefox.com") {
      throw new Error("همین Firefox را پس از ورود روی accounts.firefox.com نگه‌دار و دوباره افزونه را باز کن.");
    }

    const payload = await browser.runtime.sendMessage({ type: "foxy-take-session", tabId: tab.id });
    const token = payload && payload.token;
    if (!token) {
      throw new Error("پیام WebChannel نیامد. دکمهٔ ورود رسمی را بزن، در همان تب وارد شو و سپس دوباره تلاش کن.");
    }

    const response = await fetch(`${dashboard.origin}/api/account/browser-session`, {
      method: "POST",
      mode: "cors",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pair_code: pairCode, session_token: token })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `خطای سرور ${response.status}`);

    result.textContent = "ورود انجام شد؛ نشست موقت از حافظهٔ افزونه حذف شد.";
    document.getElementById("pair").value = "";
  } catch (error) {
    result.textContent = error.message || "ارسال نشست ناموفق بود. اگر توکن مصرف شده، دوباره وارد Firefox شو.";
  } finally {
    sendButton.disabled = false;
  }
});
