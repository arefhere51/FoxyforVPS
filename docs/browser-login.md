# ورود مرورگری Firefox به FoxyforVPS

این نسخه رمز Firefox را از پنل حذف می‌کند. ورود در صفحهٔ واقعی `accounts.firefox.com` انجام می‌شود. افزونهٔ کوچک داخل `browser-extension/` فقط پیام‌های WebChannel صفحهٔ Firefox Accounts را می‌خواند. قبل از انتقال، یک پنجرهٔ تأیید مرورگر مقصد را نشان می‌دهد. اگر اجازه بدهی، فقط نشست موقت Firefox از پنجرهٔ ورود به تب پنل فرستاده می‌شود؛ رمز و کدهای تأیید به پنل فرستاده نمی‌شوند.

## نصب افزونه در Firefox دسکتاپ

Firefox باید نسخهٔ 128 یا جدیدتر باشد.

1. ZIP پروژه را روی همان رایانه‌ای که Firefox روی آن اجراست استخراج کن.
2. در Firefox به `about:debugging#/runtime/this-firefox` برو.
3. اگر نسخهٔ قبلی افزونه بارگذاری است، آن را با **Remove** حذف کن. سپس روی **Load Temporary Add-on…** بزن و فایل `browser-extension/manifest.json` را از پوشهٔ نسخهٔ جدید انتخاب کن.
4. تب پنل FoxyforVPS را در همین Firefox باز کن و تازه‌سازی کن. پنل عمومی باید HTTPS باشد؛ برای پنل محلی/SSH، `localhost` یا `127.0.0.1` مجاز است.
5. در پنل **ورود در پنجرهٔ رسمی Firefox** را بزن. پنجرهٔ `accounts.firefox.com` باز می‌شود. گذرواژه، passkey، کد ایمیل و TOTP را فقط همان‌جا وارد کن.
6. پس از نمایش پنجرهٔ اجازه، مقصد را دقیق بررسی کن. اگر مقصد پنل خودت است، انتقال را تأیید کن. پنل تا ۱۵ دقیقه وضعیت تأیید را بررسی می‌کند.

افزونه خودش پنجرهٔ جداگانه باز نمی‌کند؛ ورود باید از پنل آغاز شود. پس از بارگذاری، آیکن **FoxyforVPS Login Bridge** در فهرست/نوار افزونه‌های Firefox دارد. وقتی پنجرهٔ Firefox Accounts باز شد، روی آیکن افزونه بزن: popup مرحله را نشان می‌دهد—فعال‌بودن hook، اتصال به پنل، دیده‌شدن رویداد ورود، تأیید یا ارسال نشست. این تشخیص توکن خام را نمایش یا ذخیره نمی‌کند.

نسخهٔ افزونه دو بخش دارد: hook رویداد WebChannel را در محیط صفحهٔ Firefox می‌خواند؛ بخش ایزوله پیام را می‌گیرد، اجازهٔ کاربر را می‌پرسد و نشست را به تب پنل می‌فرستد. اگر popup گفت hook فعال نیست، تب Firefox Accounts را تازه‌سازی کن. اگر گفت «هنوز پنل را دریافت نکرده»، صفحه را دستی باز نکن؛ ورود را از دکمهٔ پنل آغاز کن. اگر بعد از حدود دو دقیقه پنل نوشت «افزونه پاسخی نداد»، افزونهٔ قبلی را Remove کن، نسخهٔ تازه را بارگذاری کن، تب پنل را تازه‌سازی کن و ورود را از نو آغاز کن.

افزونه فقط مجوز `https://accounts.firefox.com/*` دارد و نشست را در storage افزونه ذخیره نمی‌کند. افزونهٔ موقت Firefox معمولاً پس از بستن/بازکردن مرورگر غیرفعال یا حذف می‌شود؛ برای استفادهٔ دائمی باید بستهٔ امضاشدهٔ افزونه نصب شود. پروژه فایل XPI امضاشده ارائه نمی‌کند.

## چه چیزی به VPS می‌رسد

پس از رضایت صریح، نشست موقت (۶۴ رقم hex) از راه HTTPS یا SSH به backend می‌رسد. backend آن را فقط در حافظه، حداکثر ۱۵ دقیقه، نگه می‌دارد؛ پس از تأیید نشست با OAuth مبادله می‌کند و درخواست حذف نشست موقت را می‌فرستد. توکن‌های OAuth لازم برای اجرای VPN همچنان روی VPS ذخیره می‌شوند. مدیر root VPS از نظر فنی قادر به مشاهدهٔ حافظهٔ برنامه است؛ فقط به VPS خودت اعتماد کن.

هر عملیات نوشتنی پنل same-origin و احراز هویت مدیر را لازم دارد. nonce تصادفیِ کوتاه‌عمر، attempt ورود را به popup همان پنل متصل می‌کند. افزونه فقط به origin دقیق opener پیام می‌دهد و پیش از ارسال، از کاربر اجازه می‌گیرد. مقصد باید HTTPS باشد، مگر `localhost` یا loopback.

## محدودیت مهم

این راه از `context=fx_desktop_v3` و WebChannel ورود Sync استفاده می‌کند. این روش، OAuth عمومی برای هر وب‌سایت نیست و FoxyforVPS یک OAuth relying party ثبت‌شدهٔ Mozilla محسوب نمی‌شود. Mozilla برای OAuth عمومی، client و redirect URI ثبت‌شده می‌خواهد؛ این پروژه از آن flow ادعای پشتیبانی رسمی ندارد. ارتباط WebChannel ممکن است در Firefox یا سمت Mozilla تغییر کند.

ورود در مرورگر کاربر، چالش صفحهٔ ورود را به سایت رسمی واگذار می‌کند؛ CAPTCHA یا ضدربات را دور نمی‌زنیم. با این حال، backend VPS هنوز باید وضعیت نشست و OAuth را از Mozilla بپرسد. اگر این درخواست‌های backend نیز HTTP 406 بدهند، این پل به‌تنهایی کافی نیست و ورود از VPS قابل تکمیل نخواهد بود. در آن حالت راه‌حل مطمئن، رفع محدودیت از سمت Mozilla/شبکه یا اجرای VPN روی دستگاهی است که ورود در آن کامل می‌شود؛ چالش را دور نمی‌زنیم.

## منابع فنی

- [Mozilla: Firefox Accounts OAuth overview](https://vladikoff.github.io/app-services-site/docs/accounts/welcome.html)
- [Mozilla: WebChannel reference](https://mozilla.github.io/ecosystem-platform/reference/webchannels)
- [Mozilla Ecosystem Platform: integration with FxA](https://mozilla.github.io/ecosystem-platform/relying-parties/tutorials/integration-with-fxa)
- [Mozilla Ecosystem Platform: FxA API](https://mozilla.github.io/ecosystem-platform/api)
- [Arman VPN: browser sign-in implementation](https://github.com/armanlife/firefox-vpn-client/blob/main/app/lib/ui/browser_signin.dart)
