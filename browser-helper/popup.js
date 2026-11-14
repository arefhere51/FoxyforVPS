const button = document.getElementById("send");
const result = document.getElementById("result");
button.addEventListener("click", async () => {
  result.textContent = "";
  button.disabled = true;
  try {
    const pairCode = document.getElementById("pair").value.trim();
    if (!pairCode) throw new Error("کد یک‌بارمصرف را وارد کن.");
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url || !new URL(tab.url).hostname.endsWith("accounts.firefox.com")) {
      throw new Error("ابتدا در همین تب وارد صفحهٔ رسمی accounts.firefox.com شو.");
    }
    const payload = await browser.tabs.sendMessage(tab.id, { type: "foxy-take-session" });
    const token = payload && payload.token;
    if (!token) throw new Error("پیام ورود دریافت نشده؛ صفحهٔ Firefox Accounts را پس از ورود دوباره بارگذاری کن.");
    const response = await fetch("http://127.0.0.1:8777/api/account/browser-session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pair_code: pairCode, session_token: token }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `خطای سرور ${response.status}`);
    result.textContent = "ورود انجام شد. توکن نشست موقت از حافظهٔ افزونه پاک شد.";
    document.getElementById("pair").value = "";
  } catch (error) {
    result.textContent = error.message || "ارسال نشست ناموفق بود.";
  } finally {
    button.disabled = false;
  }
});
