# گزارش دیباگ و تغییرات امنیتی

## جریان ورود فعلی

نسخهٔ فعلی پنل افزونه نمی‌خواهد. فرم صفحه، اطلاعات را فقط برای یک تلاش ورود به backend VPS می‌فرستد. backend یک Chromium موقت را با کاربر Linux جداگانه اجرا می‌کند، WebChannel را مشابه WebView خود FoxyVPN پل می‌زند و فقط session token را برای exchange به کد موجود تحویل می‌دهد. جزئیات و محدودیت‌ها در [FXA-AUTH-FLOW.md](FXA-AUTH-FLOW.md) آمده است.

رمز Firefox از VPS عبور می‌کند و فقط در حافظه/pipe موقت است؛ در storage، فایل، command line، environment یا log ذخیره نمی‌شود. این کار رمز را از مدیر root VPS پنهان نمی‌کند. فرم فقط باید از HTTPS عمومی یا SSH tunnel استفاده کند. CAPTCHA، MFA، ایمیل تأیید یا ضدربات دور زده نمی‌شود؛ در صورت ظاهرشدن، تلاش متوقف و رمز در UI پاک می‌شود.

## سابقهٔ اشکال افزونه

نسخهٔ قبلی `content.js` در محیط پیش‌فرض isolated اجرا می‌شد و مستقیماً `event.detail` رویداد `WebChannelMessageToChrome` را می‌خواند. مستند Mozilla توضیح می‌دهد که content script و JavaScript صفحه دو world جدا دارند؛ اشیای JavaScript صفحه لزوماً از isolated world قابل‌دسترسی نیستند. در نسخهٔ قبلی افزونه یک listener در `world: MAIN` رویداد را می‌خواند، سپس از receiver ایزوله و background پیام‌رسانی می‌کرد. این مسیر دیگر flow اصلی ورود پنل نیست.

## پنل عمومی

پورت عمومی 8777 نباید HTTP خام باشد، چون Basic Auth و داده‌های مدیریتی را آشکار می‌کند. backend روی loopback VPS و پورت 8778 می‌ماند؛ دسترسی public از Caddy روی `domain:8777` با TLS خودکار انجام می‌شود. آدرس عمومی `https://domain:8777` است. گواهی به DNS صحیح و دسترسی شبکه برای challenge نیاز دارد.

## منابع

- FoxyVPN WebView/WebChannel bridge: https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/ui/screens/BrowserLoginScreen.kt
- FxA token exchange در FoxyVPN: https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/data/FxaAuthRepository.kt
- MDN: content scripts و world MAIN/ISOLATED: https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/content_scripts
- Mozilla WebChannel reference: https://mozilla.github.io/ecosystem-platform/reference/webchannels
- Mozilla relying-party OAuth guide: https://mozilla.github.io/ecosystem-platform/relying-parties/tutorials/integration-with-fxa
- Caddy: HTTPS خودکار: https://caddyserver.com/docs/automatic-https
- Caddy: reverse proxy: https://caddyserver.com/docs/quick-starts/reverse-proxy
