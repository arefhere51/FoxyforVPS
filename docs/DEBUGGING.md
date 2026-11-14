# گزارش دیباگ و تغییرات امنیتی

## نتیجهٔ بررسی ورود

ورود به وب‌سایت رسمی `accounts.firefox.com` با حسابی که کاربر برای این آزمون معرفی کرد پذیرفته شد و صفحهٔ تنظیمات Mozilla account باز شد. بنابراین مشکل مشاهده‌شده ناشی از ردشدن رمز نبود. نشست مرورگر ساخته‌شده برای دیباگ باید پس از آزمون بسته شود؛ هیچ گذرواژه‌ای در سورس یا فایل پروژه درج نشده است.

## علت محتمل خرابی افزونهٔ قبلی

نسخهٔ قبلی `content.js` در محیط پیش‌فرض isolated اجرا می‌شد و مستقیماً `event.detail` رویداد `WebChannelMessageToChrome` را می‌خواند. مستند Mozilla توضیح می‌دهد که content script و JavaScript صفحه دو جهان جدا دارند؛ اشیای JavaScript صفحه لزوماً از isolated world قابل‌دسترسی نیستند. در نسخهٔ جدید یک listener کوچک در `world: MAIN` رویداد را می‌خواند، فقط `sessionToken` با قالب مورد انتظار را به receiver ایزوله bridge می‌کند، و background آن را در `storage.session` نگه می‌دارد. طبق MDN این storage در حافظهٔ نشست است، روی دیسک نوشته نمی‌شود و با پایان نشست مرورگر پاک می‌شود. Popup پس از redirect همان تب، token را یک‌بار برمی‌دارد و حذف می‌کند.

برای شروع جریان درست WebChannel افزونه لینک رسمی با `service=sync&context=fx_desktop_v3` را باز می‌کند. ورود در تب دیگری یا ورود از صفحه‌ای بدون این context ممکن است هیچ پیام WebChannel قابل‌مصرفی تولید نکند.

## پنل عمومی

پورت عمومی 8777 نباید HTTP خام باشد، چون Basic Auth و داده‌های مدیریتی را آشکار می‌کند. backend در نسخهٔ جدید روی loopback VPS و پورت 8778 می‌ماند؛ راه‌اندازی public (در صورت داشتن دامنه‌ای که DNS آن به VPS اشاره می‌کند) باید Caddy را روی `domain:8777` با TLS خودکار قرار دهد. آدرس عمومی در نتیجه `https://domain:8777` است. دسترسی HTTP بدون TLS یا بازکردن مستقیم Uvicorn به اینترنت پشتیبانی نمی‌شود. صدور گواهی عمومی به DNS صحیح و دسترسی شبکه به روش challenge نیاز دارد.

## مستندات رسمی

- [MDN: content_scripts و world MAIN/ISOLATED](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/content_scripts)
- [MDN: storage.session](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/storage/session)
- [MDN: background scripts در Manifest V3 و پشتیبانی Firefox](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/background)
- [MDN: درخواست مجوز origin اختیاری با کلیک کاربر](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/permissions/request)
- [Caddy: HTTPS خودکار](https://caddyserver.com/docs/automatic-https)
- [Caddy: reverse proxy](https://caddyserver.com/docs/quick-starts/reverse-proxy)
