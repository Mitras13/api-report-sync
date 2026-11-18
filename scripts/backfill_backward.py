"""بک‌فیل رو به عقب: از قدیمی‌ترین روزِ پنجره‌ی main.py، روزبه‌روز به عقب تا یک تاریخ، و هر روز بلافاصله در SQL.

برای دانلودرهای BACKFILLED_BACKWARD در main.py (فعلاً SPA_54). main.py هر شب فقط پنجره‌ی N روز آخر
را می‌گیرد؛ این اسکریپت روزهای قدیمی‌تر از آن را پر می‌کند، پس دو تا هیچ‌وقت روی یک روز کار نمی‌کنند.
روزی که فایل کامل (تا ۲۳:۵۹:۵۹) دارد رد می‌شود، پس اگر قطع شد دوباره اجرا کن تا از همان‌جا ادامه دهد.
وقتی main.py در حال اجراست صبر می‌کند (همان توکن پنل → 429). هر گزارش قفل خودش را دارد
(`.backfill_backward_<label>.lock`)، پس SPA_HK و SPA_54 (هاست و توکن جدا) می‌توانند هم‌زمان اجرا شوند.

اجرا (از ریشه‌ی پروژه):
    python scripts/backfill_backward.py                  ← SPA_54 تا ۱۴۰۴/۰۱/۰۱
    python scripts/backfill_backward.py SPA_HK
    python scripts/backfill_backward.py SPA_54 1404/06/01
"""
import logging
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import jdatetime  # noqa: E402

import main  # noqa: E402
from context import now_jalali  # noqa: E402
from downloaders.downloader_core import AuthExpiredError, RAW_DATA_ROOT, configure_logging  # noqa: E402
from load_raw_data_to_sql import SQL_SERVER, SQL_DATABASE  # noqa: E402
from db.sql_loader import ensure_tracking_table, get_connection  # noqa: E402

DELAY_SECONDS = 30          # بین دو روز - سرور پنل با ۳ درخواست در ۳۰ ثانیه 429 داد
FAIL_WAIT_SECONDS = 300     # بعد از خطا (معمولاً 429 یا 500 شبانه‌ی 5040)
MAX_TRIES_PER_DAY = 6

# اگر این تعداد روز پشت‌سرهم خالی بود، یعنی قبل از شروع داده‌ی گزارش رسیده‌ایم و بک‌فیل تمام می‌شود
# (پزشکت: نمی‌خواهیم صدها روز خالی بیهوده از سرور خواسته شود).
EMPTY_STOP_DAYS = {"WTX_PT": 45, "DCU_PT": 45}
# فاصله‌ی بین دو روز برای سرورهایی که rate-limit پنل را ندارند
DELAY_FOR = {"WTX_PT": 2, "DCU_PT": 2, "CALLS_HK": 10}



def complete_days(spec):
    folder = RAW_DATA_ROOT / spec.report_code / spec.company_code
    pattern = main._filename_pattern(spec.report_code, spec.company_code)
    days = set()
    for file_path in folder.glob("*.parquet") if folder.is_dir() else ():
        match = pattern.match(file_path.name)
        if match and match.group(2).endswith("235959"):
            days.add(jdatetime.datetime.strptime(match.group(1), "%Y%m%d%H%M%S").date())
    return days


def wait_while_main_runs(logger):
    while main.LOCK_PATH.exists() and main._lock_owner_alive():
        logger.info("main.py is running - backfill waits")
        time.sleep(120)


def run(spec, until, logger):
    window = main.WINDOW_DAYS.get(spec.label, 0)
    day = (now_jalali() - timedelta(days=1 if spec.label == "ADL_HK" else window + 1)).date()
    done = complete_days(spec)

    conn = get_connection(SQL_SERVER, SQL_DATABASE)
    ensure_tracking_table(conn)
    ok = skipped = failed = empty_streak = 0
    stop_after = EMPTY_STOP_DAYS.get(spec.label)
    try:
        while day >= until:
            if day in done:
                skipped += 1
                day -= timedelta(days=1)
                continue

            period_start = jdatetime.datetime(day.year, day.month, day.day, 0, 0, 0)
            period_end = period_start.replace(hour=23, minute=59, second=59)

            for attempt in range(1, MAX_TRIES_PER_DAY + 1):
                wait_while_main_runs(logger)
                try:
                    result = main._call_downloader(spec, period_start, period_end)
                    main._retire_old_files_for_day(conn, spec, day, main._extract_save_path(result))
                    main._load_result_into_sql(conn, spec, result)
                    ok += 1
                    logger.info("%s | backfill %s ok: %s", spec.label, day, result)
                    rows = result.get("rows") if isinstance(result, dict) else None
                    empty_streak = empty_streak + 1 if rows == 0 else 0
                    break
                except AuthExpiredError:
                    conn.rollback()
                    logger.exception("%s | token rejected - backfill stopped at %s", spec.label, day)
                    return
                except Exception:
                    conn.rollback()
                    logger.exception("%s | backfill %s failed (try %d/%d)", spec.label, day, attempt, MAX_TRIES_PER_DAY)
                    if attempt < MAX_TRIES_PER_DAY:
                        time.sleep(FAIL_WAIT_SECONDS)
            else:
                failed += 1

            if stop_after and empty_streak >= stop_after:
                logger.info("%s | %d empty days in a row - no older data, backfill stops at %s",
                            spec.label, empty_streak, day)
                break
            time.sleep(DELAY_FOR.get(spec.label, DELAY_SECONDS))
            day -= timedelta(days=1)
    finally:
        conn.close()
        logger.info("%s | backfill finished | ok=%d skipped=%d failed=%d", spec.label, ok, skipped, failed)


if __name__ == "__main__":
    configure_logging()
    logger = logging.getLogger("backfill_backward")

    label = sys.argv[1] if len(sys.argv) > 1 else "SPA_54"
    until = jdatetime.datetime.strptime(sys.argv[2] if len(sys.argv) > 2 else "1404/01/01", "%Y/%m/%d").date()
    specs = {s.label: s for s in main.DOWNLOADERS if s.label in main.BACKFILLED_BACKWARD}
    if label not in specs:
        sys.exit(f"Unknown label {label!r}; one of: {', '.join(sorted(specs))}")

    lock_path = ROOT / f".backfill_backward_{label}.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        sys.exit(f"Another {label} backfill is running (lock file {lock_path})")
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))
    try:
        run(specs[label], until, logger)
    finally:
        lock_path.unlink(missing_ok=True)
