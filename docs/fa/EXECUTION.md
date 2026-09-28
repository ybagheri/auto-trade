# اجرا

تنها کدی که در این پروژه می‌تواند سفارش ثبت کند، کنترل نهایی اجراست. این کنترل به‌صورت پیش‌فرض رد می‌شود.

## دروازه‌ها

`ExecutionGate.refusal()` نخستین دلیلی را برمی‌گرداند که اجرا مجاز نیست، و `execute_order` نتیجه‌ی `REJECTED` برمی‌گرداند بدون آنکه به ترمینال دست بزند.

| دروازه | پیش‌فرض | پیام رد |
| --- | --- | --- |
| `AUTO_TRADE_ENABLE_EXECUTION` | `false` | `execution is disabled; set AUTO_TRADE_ENABLE_EXECUTION=true to allow it` |
| kill switch | پشتیبان فایلی، خاموش | `kill switch is active` |
| dry-run | `true` | `dry-run is enforced` |
| سیاست فقط دمو | `true` | `demo-only policy is not satisfied` |
| baseline مشاهده‌شده | الزامی | `refusing to execute: <reason>` |
| action پشتیبانی‌شده | `BUY`، `SELL` | `action X has no guarded final control` |
| تطابق دیالوگ با تأیید ریسک | الزامی | `dialog <field> ... does not match the approved ...` |
| یافتن کنترل نهایی | دقیقاً یکی | `final control ... was not found` / `refusing to guess` |

مقدار `enabled` هرگز از یک پیش‌فرض پیکربندی استخراج نمی‌شود. یک checkout تازه نمی‌تواند اجرا کند.

## شناسه‌های کنترل، اندازه‌گیری‌شده

با بازرسی دیالوگ واقعی سفارش روی Alpari MT5 نسخه ۶۱۸۴ به‌دست آمده‌اند، نه فرضی:

| کنترل | نام | automation id |
| --- | --- | --- |
| خرید | `Buy by Market` | `10408` |
| فروش | `Sell by Market` | `10409` |
| نماد | فیلد | `10325` |
| حجم | فیلد | `10333` |
| حد ضرر | فیلد | `10334` |
| حد سود | فیلد | `10336` |
| توضیح | فیلد | `1001` |

دکمه تنها زمانی کلیک می‌شود که **هم** نام و **هم** automation id آن مطابق باشد، و تنها زمانی که دقیقاً یک عنصر منطبق باشد. دکمه‌ای با همان نام و id متفاوت، آن کنترل شمرده نمی‌شود.

## چرا دیالوگ دوباره خوانده می‌شود

`confirm_dialog_matches` نماد، حجم و هر حد ضرر یا حد سود را مستقیماً از دیالوگ آماده‌شده بازمی‌خواند و با درخواستی که موتور ریسک تأیید کرده مقایسه می‌کند. دیالوگی که دوباره پر شده، نیمه‌ویرایش‌شده یا باقی‌مانده از اجرای قبلی باشد، به‌جای ارسال رد می‌شود. مقایسه‌ی حجم هر دو طرف را نرمال می‌کند، بنابراین `0.010` و `0.01` برابرند.

## کلیک، پر شدن سفارش نیست

`execute_order` مقدار `REQUESTED` برمی‌گرداند، هرگز `ACCEPTED`، و پیامش می‌گوید `acceptance not yet observed`. پذیرش تنها توسط `verify_execution` اثبات می‌شود، که یک snapshot مستقل را با baseline ثبت‌شده در انتهای `prepare_order` مقایسه می‌کند. تنها دقیقاً یک پوزیشن جدید که نماد، جهت و حجمش مطابق باشد به `ACCEPTED` می‌رسد؛ هر چیز دیگری، از جمله snapshot غیرقابل‌خواندن، `UNKNOWN` می‌دهد.

همین جدایی تمام استدلال ایمنی است: یک کلیک موفق درباره‌ی بروکر چیزی اثبات نمی‌کند، و کد هرگز ادعا نمی‌کند که می‌کند.

## روشن کردن آن

```dotenv
AUTO_TRADE_ENABLE_EXECUTION=true
AUTO_TRADE_DRY_RUN=false
```

هر دو لازم‌اند. فرمان `execute` در CLI علاوه بر این‌ها به `--confirm-demo` نیاز دارد:

```powershell
python -m auto_trade execute --confirm-demo <signal-file>
```

مسیر `dry-run` در CLI آداپتور خود را با `enabled=False` می‌سازد، صرف‌نظر از پیکربندی، بنابراین گردش‌کار مستندشده‌ی dry-run هرگز به کنترل نهایی نمی‌رسد.

فعال کردن این روی حساب واقعی خارج از چیزی است که این پروژه برایش آزموده شده. هدف پشتیبانی‌شده حساب دمو است، و نخستین اجرا باید زیر نظر گرفته شود:

1. تأیید کنید `position-snapshot` مقدار `AVAILABLE` را از indicator فقط‌خواندنی گزارش می‌کند.
2. تأیید کنید `AUTO_TRADE_MAX_VOLUME` آگاهانه تنظیم شده است.
3. از کمترین حجم مجاز بروکر استفاده کنید.
4. kill switch را با یک فراخوانی HTTP در دسترس نگه دارید: `python -m auto_trade dashboard`.
5. لاگ حسابرسی را ببینید. هر رد دروازه و هر نتیجه‌ی تأیید، همراه با شواهدش ثبت می‌شود.

## بستن یک پوزیشن

بستن، دومین کنترلی است که حساب را تغییر می‌دهد، و opt-in مستقل خود را دارد تا هرگز صرفاً به‌دلیل مجاز بودن یک سفارش در دسترس نباشد.

```dotenv
AUTO_TRADE_ENABLE_CLOSE=true
AUTO_TRADE_DRY_RUN=false
```

```powershell
python -m auto_trade close-position 382652281 --confirm-demo
```

| دروازه | پیش‌فرض | پیام رد |
| --- | --- | --- |
| `AUTO_TRADE_ENABLE_CLOSE` | `false` | `closing is disabled; set AUTO_TRADE_ENABLE_CLOSE=true to allow it` |
| kill switch | پشتیبان فایلی، خاموش | `kill switch is active` |
| dry-run | `true` | `dry-run is enforced` |
| سیاست فقط دمو | `true` | `demo-only policy is not satisfied` |
| وجود ticket در دفتر اجرا | الزامی | `ticket ... is not in the execution ledger, so it is not a position this application opened` |
| مشاهده‌ی ticket در همین لحظه | الزامی | `position ... is not in the observed snapshot` |
| تنها یک پوزیشن باز | الزامی | `N positions are open and the trade grid exposes no row text` |
| ردیف بدون ابهام | یک ردیف، به‌علاوه ردیف خلاصه | `the trade grid exposes N rows; refusing to guess` |
| ورودی منو | `Close Position` / `33033`، دقیقاً یکی | `context menu has no 'Close Position' entry` / `automation id` |

قانون دفتر اجرا مهم‌ترین است: تنها پوزیشنی که این برنامه باز کرده از این مسیر بسته می‌شود، پس پوزیشنی که یک انسان باز کرده هرگز لمس نمی‌شود.

قانون ردیف به این دلیل وجود دارد که گرید Trade روی این نسخه مستطیل یک ردیف را نمایش می‌دهد اما متنش را نه، بنابراین ticket را نمی‌توان از گرید خواند. با دقیقاً یک پوزیشن باز، نخستین ردیف به‌طور اثبات‌پذیر همان ردیف موردنظر است؛ با بیش از یکی، این کد رد می‌کند و از انسان کمک می‌خواهد.

`CLOSED` تنها زمانی برگردانده می‌شود که ticketی که در آغاز فراخوانی باز بود در مشاهده‌ای بعدی غایب باشد. پوزیشنی که صرفاً تغییر کرده با بسته‌شده اشتباه گرفته نمی‌شود، و snapshot غیرقابل‌خواندن به‌جای بستن، `UNKNOWN` می‌دهد. `close_position` نه تغییر می‌دهد، نه نیمه‌بستن انجام می‌دهد، نه hedge: ورودی‌های `Close by`، `Close 50%` و `Close All` همسایه‌ی ورودی مورد استفاده‌ی این کد هستند و در `closing.py` نام‌برداری شده‌اند تا دلیل تطابق دقیق روی کاغذ بماند.

جدول دروازه‌های سفارش در [بازیابی](RECOVERY.md) آمده است: پس از restart، همان سیگنال با پیام `duplicate signal id` رد می‌شود، چون تلاش ناتمام پیشین هنوز در دفتر اجراست.

## [English](EXECUTION.md) · [بازیابی](RECOVERY.md) · [سنجه‌ها](METRICS.md)
