const statusEl = document.getElementById('status');
const detailEl = document.getElementById('detail');

function render(result) {
  statusEl.className = 'status';
  if (!result.pageHookReady) {
    statusEl.textContent = 'افزونه هست، اما hook صفحه فعال نیست.';
    statusEl.classList.add('warn');
    detailEl.textContent = 'صفحهٔ accounts.firefox.com را تازه‌سازی کن. اگر درست نشد، افزونه را Remove کن و نسخهٔ 1.1.1 را دوباره بارگذاری کن.';
  } else if (!result.bridgeReady) {
    statusEl.textContent = 'افزونه فعال است؛ هنوز پنل را دریافت نکرده.';
    statusEl.classList.add('warn');
    detailEl.textContent = 'ورود را از دکمهٔ داخل پنل FoxyforVPS شروع کن؛ بازکردن دستی accounts.firefox.com پل پنل را ایجاد نمی‌کند.';
  } else if (result.deliveryFailed) {
    statusEl.textContent = 'ارسال به پنل ناموفق شد.';
    statusEl.classList.add('warn');
    detailEl.textContent = 'ورود را از پنل دوباره شروع کن. اگر تکرار شد، نشانی HTTPS پنل یا متن خطای پنل را بررسی کن.';
  } else if (result.consentDenied) {
    statusEl.textContent = 'ارسال نشست را رد کردی.';
    statusEl.classList.add('warn');
    detailEl.textContent = 'اگر قصد ادامه داری، ورود را از پنل از نو آغاز کن و فقط مقصد پنل خودت را تأیید کن.';
  } else if (result.sessionSent) {
    statusEl.textContent = 'نشست به پنل فرستاده شد.';
    statusEl.classList.add('ok');
    detailEl.textContent = 'این صفحه فقط موفقیت ارسال را تأیید می‌کند؛ نتیجهٔ نهایی را در پنل FoxyforVPS ببین.';
  } else if (result.loginEventSeen) {
    statusEl.textContent = 'ورود شناسایی شد؛ منتظر اجازهٔ ارسال است.';
    statusEl.classList.add('warn');
    detailEl.textContent = 'در پنجرهٔ تأیید Firefox، مقصد را بررسی و انتقال را تأیید کن.';
  } else {
    statusEl.textContent = 'افزونه فعال است و به پنل وصل شده.';
    statusEl.classList.add('ok');
    detailEl.textContent = 'حالا در همین پنجره ورود Firefox را کامل کن؛ پنل پس از رویداد ورود، اجازهٔ انتقال نشست را می‌پرسد.';
  }
}

async function showStatus() {
  try {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    if (!tab || !Number.isInteger(tab.id)) throw new Error('no active tab');
    const result = await browser.tabs.sendMessage(tab.id, { type: 'foxyforvps:bridge-status' });
    render(result);
  } catch (_) {
    statusEl.textContent = 'افزونه روی این تب فعال نیست.';
    statusEl.className = 'status warn';
    detailEl.textContent = 'این popup فقط روی accounts.firefox.com وضعیت را نشان می‌دهد. ورود را از پنل شروع کن؛ افزونه پنجرهٔ ورود را خودش باز نمی‌کند.';
  }
}

showStatus();
