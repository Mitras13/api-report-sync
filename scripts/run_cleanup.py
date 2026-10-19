"""اجرای واقعی پاک‌سازی فایل‌های تکراری (cleanup_redownloaded_files.sql با @apply = 1).

اجرا: python run_cleanup.py   ← قبل از اجرا «بله» می‌پرسد.
پیش‌نیاز: بارگذار شبانه در حال اجرا نباشد. با حساب ویندوزی همین کامپیوتر (Trusted_Connection) وصل می‌شود.
"""
import sys
from pathlib import Path

import pyodbc

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
LOCK = Path(r"D:\MITRA\ربات های قدیمی\Robot_Downloader_sql\.load_raw_data_to_sql.lock")

if LOCK.exists():
    sys.exit("بارگذار شبانه در حال اجراست (فایل قفل هست). بعداً دوباره اجرا کنید.")

sql = (HERE / "cleanup_redownloaded_files.sql").read_text(encoding="utf-8-sig")
assert sql.count("DECLARE @apply bit = 0;") == 1
sql = sql.replace("DECLARE @apply bit = 0;", "DECLARE @apply bit = 1;")

print("این کار ۴۰ فایل تکراری (۱۹۸٬۳۰۴ ردیف) را از Mitra_sarkhosh پاک می‌کند؛ قبلش پشتیبان گرفته می‌شود.")
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
cur.execute("SELECT name FROM sys.tables WHERE name LIKE '[_]bak[_]dup%' ORDER BY name")
print("پشتیبان‌ها:", ", ".join(r[0] for r in cur.fetchall()))
input("\nتمام شد. Enter بزنید تا پنجره بسته شود.")
