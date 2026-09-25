# Persian Signal Protocol

هر فایل سیگنال یک شیء JSON با فیلدهای اجباری `id`، `timestamp` دارای timezone، `source`، `symbol`، `action` و `volume` است. حجم باید مثبت و محدود به فهرست ایمنی باشد. سیگنال‌های منقضی، تکراری یا خارج از whitelist پیش از آماده‌سازی سفارش رد می‌شوند. provider فعلی فایل محلی است و پس از parse موفق، فایل را مصرف می‌کند.
