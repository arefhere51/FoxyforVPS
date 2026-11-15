# گزارش دیباگ و تغییرات

## ورود Firefox فعلی

پنل دیگر فرم رمز Firefox یا direct-password API login ندارد. ورود در سایت رسمی Firefox Accounts انجام می‌شود و افزونهٔ `browser-extension/` بعد از تأیید کاربر نشست موقت را برمی‌گرداند. راهنمای نصب در [browser-login.md](browser-login.md) است.

اگر پنجره باز نمی‌شود، popupها را برای دامنهٔ پنل مجاز کن. اگر افزونه آماده نیست، آن را در Firefox جاری بارگذاری کن. اگر ورود صفحه کامل می‌شود اما backend HTTP 406 می‌گیرد، محدودیت درخواست‌های VPS هنوز برقرار است؛ این flow CAPTCHA یا کنترل ضدربات را دور نمی‌زند.

گذرواژه و کدهای تأیید را فقط در صفحهٔ Mozilla وارد کن. Session token یا فایل `account.json` را در issue یا گفتگو نفرست. پس از لغو یا پایان مهلت، تلاش موقت از حافظه حذف می‌شود.

## پنل عمومی

backend روی loopback VPS و پورت 8778 می‌ماند؛ دسترسی public از Caddy روی `domain:8777` با TLS خودکار انجام می‌شود. آدرس عمومی `https://domain:8777` است. گواهی به DNS صحیح و دسترسی شبکه برای challenge نیاز دارد.

## منابع

- Arman VPN browser sign-in flow: https://github.com/armanlife/firefox-vpn-client/blob/main/app/lib/ui/browser_signin.dart
- FoxyVPN WebView/WebChannel bridge: https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/ui/screens/BrowserLoginScreen.kt
- Mozilla WebChannel reference: https://mozilla.github.io/ecosystem-platform/reference/webchannels
- Mozilla FxA integration overview: https://mozilla.github.io/ecosystem-platform/relying-parties/tutorials/integration-with-fxa
- Caddy automatic HTTPS: https://caddyserver.com/docs/automatic-https
