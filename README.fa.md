[🇬🇧 English Documentation](README.md)

# Auto Trade — مستندات فارسی

Auto Trade یک پلتفرم اجرای دسکتاپ ویندوز برای MetaTrader 5 است که تولید سیگنال را از اجرای معامله جدا می‌کند. در این مرحله، هسته‌ی ایمن، آزمون‌های شبیه‌سازی‌شده و حالت dry-run ارائه شده‌اند و هیچ سفارش واقعی ارسال نمی‌شود.

> **هشدار ایمنی و انطباق**
>
> معاملات خودکار، اتوماسیون دسکتاپ، اجرای معاملات خارجی و منابع سیگنال ممکن است توسط بروکر، پراپ‌فرم، ارائه‌دهنده حساب یا مقررات قابل اعمال محدود شوند. کاربران مسئول بررسی مجاز بودن کاربرد خود هستند. این پروژه ادعا نمی‌کند که استفاده از رابط دسکتاپ MT5 به‌طور خودکار یک معامله را «دستی» می‌کند یا درباره‌ی سیاست هیچ ارائه‌دهنده‌ای ادعایی دارد.

## ویژگی‌ها

- مدل‌های دامنه‌ی تایپ‌شده برای سیگنال، درخواست، نتیجه، پروفایل ترمینال، محدودیت ریسک و رخداد حسابرسی.
- رابط provider با فایل محلی، bridge از MQL5 و سه منبع محلی احرازهویت‌شده: HTTP، named pipe و WebSocket.
- موتور ریسک مستقل با فهرست نمادهای مجاز، حجم، انقضا، نرخ، اتصال و سقف پوزیشن.
- kill switch، محدودیت demo-only، dry-run، جلوگیری از سیگنال تکراری و وضعیت صریح اجرای نامعلوم.
- ماشین حالت اجرا با ثبت ساختاریافته‌ی انتقال‌ها.
- کشف پروسه‌ی MT5 بر اساس مسیر فایل اجرایی و پوشه‌ی داده.
- بسته‌ی تشخیصی (diagnostics bundle) و wizard پیکربندی برای فایل `.env`.
- لاگ حسابرسی JSONL با چرخش فایل.
- CLI برای diagnostics و پردازش dry-run بدون سفارش.
- تست‌های unit و integration که به MT5 واقعی وابسته نیستند.

## معماری

```mermaid
flowchart LR
    Signal[منبع سیگنال] --> Bridge[نرمال‌سازی]
    Bridge --> Risk[اعتبارسنجی و ریسک]
    Risk --> Engine[موتور اجرا]
    Engine --> Adapter[آداپتور دسکتاپ MT5]
    Adapter --> MT5[MT5]
    MT5 --> Verify[تأیید مستقل]
    Verify --> Audit[لاگ حسابرسی]
```

آداپتور واقعی دسکتاپ MT5 در این نسخه عمداً فعال نیست. آداپتور dry-run درخواست را آماده می‌کند، اما کنترل نهایی سفارش را لمس نمی‌کند و پذیرش کارگزار را ادعا نمی‌کند.

## شروع سریع

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m auto_trade diagnostics
python -m auto_trade test-signal examples\signals\example.json
```

برای dry-run باید زمان سیگنال به‌صورت UTC و به‌روز باشد؛ فایل نمونه ممکن است منقضی شود.

## منابع سیگنال

پیاده‌سازی‌شده: فایل JSON محلی، فایل‌های bridge که یک برنامه‌ی MQL5 در
`MQL5\Files` می‌نویسد، و سه منبع محلی احرازهویت‌شده: HTTP، named pipe و
WebSocket روی لوپ‌بک. در هر اجرا فقط یک منبع استفاده می‌شود و تنظیم دو منبع
هم‌زمان رد می‌شود. هیچ provider‌ای listener باز نمی‌کند و هیچ‌کدام نمی‌تواند سفارش
ثبت کند؛ `wss` هم به‌جای پیاده‌سازی ناقص، رد می‌شود.

```powershell
$env:AUTO_TRADE_HTTP_SIGNAL_URL = "http://127.0.0.1:8787/signals/next"
$env:AUTO_TRADE_HTTP_SIGNAL_TOKEN = "<token>"
python -m auto_trade fetch-signal
```

توکن هرگز در لاگ حسابرسی یا خروجی `diagnostics` چاپ نمی‌شود و نباید در مخزن commit شود.

## پیکربندی و بسته‌ی تشخیصی

```powershell
python -m auto_trade configure
python -m auto_trade diagnostics-bundle
```

`configure` برای هر تنظیم، مقدار فعلی را به‌عنوان پیش‌فرض نشان می‌دهد، مسیر
ترمینال یا پوشه‌ی داده‌ای که وجود ندارد را رد می‌کند، تنظیماتی را که مدیریت
نمی‌کند حفظ می‌کند و `AUTO_TRADE_ENABLE_EXECUTION=false` می‌نویسد؛ هیچ پاسخی
در این wizard اجرای واقعی را فعال نمی‌کند.

`diagnostics-bundle` یک فایل zip شامل محیط اجرا (از جمله DPI و تعداد مانیتور)،
پیکربندی، کشف ترمینال، مشاهده‌ی پوزیشن، دفتر اجرا، سیگنال‌های در انتظار، وضعیت
kill switch و انتهای لاگ حسابرسی می‌سازد. این کار فقط خواندنی است و شکست کشف
ترمینال به‌جای خطا، در فایل ثبت می‌شود. این بسته هیچ credential ندارد، اما مسیر
ترمینال، نمادها و زمان‌بندی را آشکار می‌کند، پس عمداً به اشتراک گذاشته شود.

## ایمنی

- حالت dry-run به‌صورت پیش‌فرض فعال است.
- فقط نمادهای مجاز پذیرفته می‌شوند.
- حجم و نرخ اجرا محدود می‌شود.
- سیگنال تکراری و منقضی رد می‌شود.
- kill switch باید پیش از هر اجرا بررسی شود.
- هیچ کلیک یا سفارش واقعی در مسیر فعلی وجود ندارد.

جزئیات در [SAFETY.md](docs/SAFETY.md) و [COMPLIANCE.md](docs/COMPLIANCE.md) آمده است.

## آزمون

- **PASS — mocked:** ۴۱۱ تست unit و integration اجرا شد.
- **PASS — مستندات دو زبانه:** هر صفحه‌ای که یک رد، یک بازیابی یا یک مشاهده را توصیف می‌کند ترجمه‌ی فارسی دارد، هر دو زبان به هم لینک دارند، و هر دو README هر دو زبان را فهرست می‌کنند.
- **PASS — crash بین کلیک و مشاهده:** رکورد پایدار pending می‌ماند، پروسه‌ی پس از restart همان سیگنال را بدون دست‌زدن به ترمینال رد می‌کند، و فقط اپراتور می‌تواند آن را تسویه کند. [بازیابی](docs/fa/RECOVERY.md)
- **PASS — سنجه‌ها و تأخیر:** شمارنده‌ها و زمان‌سنجی هر فاز، استخراج‌شده از لاگ حسابرسی، پس اجرایی که crash کرده همچنان اندازه‌گیری می‌شود. فاز اندازه‌گیری‌نشده چیزی گزارش نمی‌کند، نه صفر. [سنجه‌ها](docs/fa/METRICS.md)
- **PASS — محیط:** ترمینال Alpari MT5 نسخه ۶۱۸۴، پوشه‌ی داده و پروسه‌ی در حال اجرای `Alpari-MT5-Demo` پیدا و توسط کد خودِ پروژه شناسایی شدند.
- **PASS — ساخت اندیکاتور:** `AutoTradePositionReader` با ۰ خطا و ۰ هشدار کامپایل شد، در Navigator ثبت شد و به چارت `EURUSD,M5` متصل است.
- **PASS — snapshot پوزیشن:** `position-snapshot` وضعیت `AVAILABLE` را از یک snapshot زنده و کامل گزارش می‌کند و حساب در حال حاضر پوزیشن بازی ندارد.
- **PASS — محافظ stale:** یک snapshot واقعی از جلسه‌ی قبل درست رد شد و به‌عنوان حساب خالی خوانده نشد.
- **PASS — dry-run کنترل‌شده:** dry-runهای واقعی BUY و SELL روی همین نسخه به `ORDER_READY` رسیدند و بدون کنترل نهایی بسته شدند و هیچ پوزیشنی باقی نماند.
- **PASS — داشبورد:** سرور loopback با توکن برای عملیات تغییردهنده.
- **PASS — executable:** ساخت ویندوز اجرا شد و `diagnostics`، `diagnostics-bundle`، `dry-run --mock` و داشبورد کار کردند؛ با پایتون ۳.۱۳ ساخته شده و باید روی ۳.۱۲ بازساخته شود.
- **NOT RUN — نصب‌کننده:** تعریف Inno Setup کامپایل نشد، چون روی این ماشین نصب نیست.
- **PASS — سفارش demo محافظت‌شده:** اجرای واقعی `execute --confirm-demo` روی حساب demo نتیجه‌ی `ACCEPTED` داد، همراه با `order_reference`، baseline خالی و شواهد پوزیشن مشاهده‌شده. تلاش اول `UNKNOWN` داد و سه ایراد پس از کلیک آشکار کرد که هر سه رفع شدند.
- **PASS — بستن پوزیشن محافظت‌شده:** `close-position 382652281 --confirm-demo` مقدار `CLOSED` داد و ticket از یک مشاهده‌ی مستقل ناپدید شد. تنها پوزیشنی که همین برنامه باز کرده قابل بستن است. [اجرا](docs/fa/EXECUTION.md)
- **NOT RUN — حساب واقعی:** در هیچ مرحله‌ای از حساب واقعی یا شارژشده استفاده نشد.

- **MANUAL TEST REQUIRED:** انتخاب نماد، رفتار DPI و رد شدن سفارش توسط بروکر باید در demo بررسی شوند.

## مستندات

> **وضعیت فعلی پروژه:** [docs/STATUS.md](docs/STATUS.md) صفحه‌ی اولی برای خواندن است.
> آنچه واقعاً روی یک ترمینال demo اجرا و مشاهده شده، چه چیزهایی عمداً رد می‌شوند و
> چرا، و هر آیتم باز با مانعی که دارد را ثبت می‌کند.

- [وضعیت پروژه](docs/STATUS.md)
- [ارزیابی معماری](docs/ARCHITECTURE_ASSESSMENT.md)
- [معماری](docs/ARCHITECTURE.md)
- [پیکربندی](docs/CONFIGURATION.md)
- [پروتکل سیگنال](docs/fa/SIGNAL_PROTOCOL.md) · [English](docs/SIGNAL_PROTOCOL.md)
- [ایمنی](docs/fa/SAFETY.md) · [English](docs/SAFETY.md)
- [یکپارچه‌سازی MT5](docs/MT5_INTEGRATION.md)
- [position reader](docs/fa/POSITION_READER.md) · [English](docs/POSITION_READER.md)
- [داشبورد](docs/fa/DASHBOARD.md) · [English](docs/DASHBOARD.md)
- [اجرا](docs/fa/EXECUTION.md) · [English](docs/EXECUTION.md)
- [بازیابی](docs/fa/RECOVERY.md) · [English](docs/RECOVERY.md)
- [سنجه‌ها](docs/fa/METRICS.md) · [English](docs/METRICS.md)
- [یکپارچه‌سازی استراتژی](docs/fa/STRATEGY_INTEGRATION.md) · [English](docs/STRATEGY_INTEGRATION.md)
- [فهرست آثار قابل ردیابی](docs/fa/TRACEABILITY.md) · [English](docs/TRACEABILITY.md)
- [بسته‌بندی](docs/PACKAGING.md)
- [توسعه و آزمون](docs/TESTING.md)
- [English documentation](README.md)

## نقشه‌ی راه

وضعیت فعلی در [ROADMAP.md](ROADMAP.md) و [docs/STATUS.md](docs/STATUS.md) ثبت شده است. فازهای ۰ تا ۹ کامل‌اند و هر دو کنترلی که حساب را تغییر می‌دهند — ثبت سفارش و بستن پوزیشن — روی یک ترمینال demo واقعی اجرا و تأیید شده‌اند. مسیر اجرای زنده تا زمانی که این کنترل‌ها کامل نشده‌اند مسدود خواهد بود.
