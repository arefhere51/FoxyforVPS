# گزارش دیباگ و تغییرات

## ورود Firefox فعلی

پنل از API مستقیم حساب Firefox استفاده می‌کند و دیگر WebExtension یا Chromium لازم ندارد. گذرواژه به `authPW` مشتق می‌شود و برای endpoint ورود ارسال می‌شود. کد ایمیل، TOTP، لینک تأیید و کد رفع مسدودی در صورت درخواست FxA، مرحله‌ای در خود پنل دارند. جزئیات در [FXA-AUTH-FLOW.md](FXA-AUTH-FLOW.md) آمده است.

HTTP 406 از Firefox Accounts یعنی سرور یک چالش امنیتی برگردانده است. این نسخهٔ FoxyforVPS چالش را دور نمی‌زند؛ پیام خطای مشخص می‌دهد و توقف می‌کند. هیچ Chromium یا پروفایل مرورگر برای login ساخته نمی‌شود. تلاش‌های تأیید فقط در حافظه نگهداری می‌شوند و پس از ۱۵ دقیقه یا restart سرویس از بین می‌روند.

## اگر ورود API شکست خورد

1. مطمئن شو VPS به `api.accounts.firefox.com` دسترسی HTTPS دارد.
2. مطمئن شو ایمیل/رمز درست است و اگر Firefox کد ایمیل یا TOTP خواسته، همان کد تازه را وارد کن.
3. برای HTTP 406، تلاش را تکرار پشت‌سرهم نکن؛ محدودیت امنیتی یا fingerprint شبکه ممکن است مانع شود. این نسخه چالش را حل نمی‌کند.
4. رمز، کد ایمیل، TOTP، session token و خروجی کامل درخواست‌ها را در issue یا گفتگو نفرست.
5. پنل عمومی باید HTTPS روی پورت 8777 باشد؛ HTTP عمومی پشتیبانی نمی‌شود.

## پنل عمومی

backend روی loopback VPS و پورت 8778 می‌ماند؛ دسترسی public از Caddy روی `domain:8777` با TLS خودکار انجام می‌شود. آدرس عمومی `https://domain:8777` است. گواهی به DNS صحیح و دسترسی شبکه برای challenge نیاز دارد.

## منابع

- FoxyVPN WebView/WebChannel bridge: https://github.com/Vauth/FoxyVPN/blob/main/app/src/main/java/com/vauth/foxyvpn/ui/screens/BrowserLoginScreen.kt
- Arman VPN API login inspection: https://github.com/armanlife/arman-vpn-client/blob/main/core/internal/fxa/fxa.go
- Arman VPN FxA derivation/Hawk: https://github.com/armanlife/arman-vpn-client/blob/main/core/internal/fxa/hawk.go
- Mozilla WebChannel reference: https://mozilla.github.io/ecosystem-platform/reference/webchannels
- Caddy automatic HTTPS: https://caddyserver.com/docs/automatic-https
