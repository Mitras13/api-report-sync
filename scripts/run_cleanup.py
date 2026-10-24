"""اجرای واقعی یک اسکریپت پاک‌سازی همین پوشه (همان فایل .sql با @apply = 1).

اجرا:
    python run_cleanup.py                                  ← cleanup_redownloaded_files.sql (۱۴۰۵/۰۷/۲۷، انجام شد)
    python run_cleanup.py cleanup_saler_hk_misnamed.sql    ← کپی اشتباه‌نام گزارش کارشناسان همکده
قبل از اجرا y می‌پرسد. پیش‌نیاز: بارگذار شبانه در حال اجرا نباشد. با حساب ویندوزی همین کامپیوتر وصل می‌شود.
"""
import sys
from pathlib import Path

import pyodbc

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
LOCK = HERE.parent / ".load_raw_data_to_sql.lock"
JOBS = {
    "cleanup_redownloaded_files.sql":
        "۴۰ فایل تکراری (۱۹۸٬۳۰۴ ردیف) از SaleR_54، SaleR_HK، INV_SAL_54 و INV_SAL_HK",
    "cleanup_saler_hk_misnamed.sql":
        "کپی اشتباه‌نام گزارش کارشناسان همکده: ۸۴۷ فایل (۴۸۰٬۷۵۶ ردیف) فقط از جدول SaleR_HK",
}

name = sys.argv[1] if len(sys.argv) > 1 else "cleanup_redownloaded_files.sql"
if name not in JOBS:
    sys.exit(f"اسکریپت ناشناخته: {name}. یکی از این‌ها: {', '.join(JOBS)}")
if LOCK.exists():
    sys.exit("بارگذار شبانه در حال اجراست (فایل قفل هست). بعداً دوباره اجرا کنید.")

sql = (HERE / name).read_text(encoding="utf-8-sig")
assert sql.count("DECLARE @apply bit = 0;") == 1
sql = sql.replace("DECLARE @apply bit = 0;", "DECLARE @apply bit = 1;")

print(f"این کار {JOBS[name]} را از Mitra_sarkhosh پاک می‌کند؛ قبلش پشتیبان گرفته می‌شود.")
# پنجره‌ی cmd حروف فارسیِ تایپ‌شده را درست به پایتون نمی‌رساند → y انگلیسی
if input("برای ادامه حرف y (انگلیسی) را تایپ کنید و Enter بزنید: ").strip().lower() not in ("y", "yes", "بله"):
    sys.exit("لغو شد؛ هیچ تغییری داده نشد.")

conn = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=Mitra_sarkhosh;"
                      "Trusted_Connection=yes;Encrypt=no;", autocommit=True, timeout=10)
cur = conn.cursor()
cur.execute(sql)
while True:
    if cur.description:
        print(" | ".join(c[0] for c in cur.description))
        for row in cur.fetchall():
            print(" | ".join(str(v) for v in row))
        print()
    for m in (cur.messages or []):
        print(m[1].split("]")[-1])
    if not cur.nextset():
        break
cur.execute("SELECT name FROM sys.tables WHERE name LIKE '[_]bak[_]%' ORDER BY name")
print("پشتیبان‌ها:", ", ".join(r[0] for r in cur.fetchall()))
input("\nتمام شد. Enter بزنید تا پنجره بسته شود.")
