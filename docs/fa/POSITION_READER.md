# position reader

پروژه برای مشاهده‌ی مستقل پوزیشن از یک indicator فقط‌خواندنی MQL5 استفاده می‌کند. این یک سرویس نیست و سفارشی ثبت، تغییر، نمی‌بندد و لغو نمی‌کند. indicator هیچ فراخوانی `OrderSend` یا trade request ندارد.

## چه می‌کند

هر ثانیه، `AutoTradePositionReader` پوزیشن‌های باز ترمینال را می‌خواند و یک snapshot از نوع JSON می‌نویسد در:

```text
<data dir>\MQL5\Files\auto_trade_positions_a.json
<data dir>\MQL5\Files\auto_trade_positions_b.json
```

این دو فایل یک‌درمیان نوشته می‌شوند تا یک reader بتواند فایلی ناقص یا stale را کنار بگذارد. reader وقتی فایل غایب، قدیمی، ناقص، بدشکل یا با schema ناشناخته باشد، fail-closed است.

indicator فراخوانی `Print` نمی‌کند و فایل لاگ اختصاصی نمی‌سازد. خود MT5 همچنان ممکن است بارگذاری یا attach شدن یک indicator را در Journal معمول خودش ثبت کند، و indicator در Navigator و روی چارت دیده می‌شود. این پروژه ادعا نمی‌کند چنین رفتاری از پلتفرم را پنهان می‌کند.

## نصب

```powershell
.\scripts\install-position-reader.ps1 `
    -DataPath "<MT5 data directory>" `
    -MetaEditor "<path to MetaEditor64.exe in the same terminal folder>"
```

اسکریپت سورس را در `<data dir>\MQL5\Indicators` کپی و کامپایل می‌کند، و اگر هیچ `.ex5` تولید نشود خطا می‌دهد. سپس در MT5 یک چارت باز کنید، `Ctrl+I` بزنید یا از دکمه‌ی indicator استفاده کنید، `AutoTradePositionReader` را انتخاب کنید و با `OK` تأیید کنید. snapshot ظرف یک تا دو ثانیه ظاهر می‌شود.

گام آخر عمداً اقدام انسانی است: گریدها و منوهای راست‌کلیک MT5 در درخت UI Automation ظاهر نمی‌شوند، پس یک چارت و indicator آن را نمی‌توان بدون یک مختصات صفحه‌ی hard-code متصل کرد. برای رویه‌ی اندازه‌گیری‌شده و سابقه‌اش [اعتبارسنجی دمو](../MT5_DEMO_VALIDATION.md) را ببینید.

## بررسی

```powershell
python -m auto_trade position-snapshot
```

یک خواندن موفق مقدار `AVAILABLE` و فهرست پوزیشن‌ها را گزارش می‌کند. snapshot غیرقابل‌دسترس، stale یا غایب هرگز به‌عنوان حساب خالی تلقی نمی‌شود.

## رابطه با اجرا

indicator تنها baseline و مشاهده‌ی پس از کلیک را فراهم می‌کند. خود سفارش همچنان با کنترل محافظت‌شده‌ی دسکتاپ MT5 انجام می‌شود، نه توسط indicator. کلیک به‌صورت `REQUESTED` گزارش می‌شود؛ تنها یک مشاهده‌ی مستقل و منطبق پوزیشن می‌تواند `ACCEPTED` تولید کند.

## [English](POSITION_READER.md) · [اجرا](EXECUTION.md) · [بازیابی](RECOVERY.md)
