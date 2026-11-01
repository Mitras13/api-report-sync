import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple, Union

import jdatetime
import pandas as pd

from scheduler.time_range import parse_jalali_datetime
from context import now_jalali
from downloaders.INV_SAL_HK import fetch as fetch_INV_SAL_HK
from downloaders.INV_SAL_54 import fetch as fetch_INV_SAL_54
from downloaders.VP_HK import fetch as fetch_vp_hk
from downloaders.VP_54 import fetch as fetch_vp_54
from downloaders.SCL_HK import fetch as fetch_SCL_HK
from downloaders.SaleR_HK import fetch as fetch_SaleR_HK
from downloaders.SaleR_54 import fetch as fetch_SaleR_54
from downloaders.APT_LST_HK import fetch as fetch_APT_LST_HK
from downloaders.CON_LST_HK import fetch as fetch_CON_LST_HK
from downloaders.AGN_LST_54 import fetch as fetch_AGN_LST_54
from downloaders.VOI_INC_54 import fetch as fetch_VOI_INC_54
from downloaders.SPK_54 import fetch as fetch_SPK_54
from downloaders.EXT_HK import fetch as fetch_EXT_HK
from downloaders.EXT_54 import fetch as fetch_EXT_54
from downloaders.downloader_core import configure_logging, RAW_DATA_ROOT

# ============================================================
# قفل اجرا (برای زمان‌بندی شبانه با Task Scheduler)
# ============================================================
# اگر main.py طولانی در حال اجرا باشد (مثلاً catch-up چندساعته) و همزمان
# Task Scheduler هم یک اجرای شبانه‌ی جدید را شروع کند، دو اجرای همزمان روی
# یک فایل Parquet مشترک race می‌کنند. این قفل از آن جلوگیری می‌کند: اجرای
# دومی که قفل را گرفته‌شده می‌بیند فقط یک پیام لاگ می‌کند و بی‌سروصدا خارج
# می‌شود (نه خطا) - چون در اجرای زمان‌بندی‌شده، "این دفعه رد شد" طبیعی است.
LOCK_PATH = RAW_DATA_ROOT.parent / ".main_download.lock"


def _lock_owner_alive() -> bool:
    # اگر پروسه‌ی صاحب قفل مرده باشد (کرش، خاموشی سیستم)، قفل باطل است - وگرنه همه‌ی
    # اجراهای بعدی بی‌سروصدا رد می‌شوند (دو بار اتفاق افتاد: ۲۰۲۶-۰۹-۲۲ و ۲۰۲۶-۱۰-۳۱).
    # در هر حالت نامطمئن، قفل معتبر فرض می‌شود.
    try:
        pid = int(LOCK_PATH.read_text().strip())
    except (OSError, ValueError):
        return True
    try:
        import psutil
    except ImportError:
        return True
    return psutil.pid_exists(pid)


def acquire_lock() -> bool:
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if _lock_owner_alive():
            return False
        logging.getLogger(__name__).warning("Removing stale lock file %s (owner process is gone)", LOCK_PATH)
        release_lock()
        try:
            fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass

# ============================================================
# بارگذاری در SQL Server
# ============================================================
# دیتابیس مقصد (اسمش الان "Mitra_sarkhosh" است - همان دیتابیسی که داشبورد
# فروش هم رویش است؛ به همین اسم مشترک attach/rename شد، ۲۰۲۶-۰۹-۲۸) attach و
# در دسترس است، پس main.py هر فایل جدید را بلافاصله هم در raw_data و هم در
# SQL ذخیره می‌کند.
ENABLE_SQL_LOAD = True

if ENABLE_SQL_LOAD:
    from load_raw_data_to_sql import SQL_SERVER, SQL_DATABASE
    from db.sql_loader import (
        ensure_database,
        get_connection,
        ensure_tracking_table,
        is_file_loaded,
        mark_file_loaded,
        unmark_file_loaded,
        delete_rows_for_file,
        table_exists,
        load_dataframe_into_table,
    )


# ============================================================
# محدوده دانلود
# ============================================================

# نقطه‌ی شروعِ پیش‌فرض: فقط وقتی استفاده می‌شود که یک دانلودر هنوز هیچ
# فایلی در raw_data نداشته باشد. اگر دانلودری از قبل داده دارد، خودکار از
# روزِ بعدِ آخرین فایل موجودش ادامه می‌دهد (نه از این تاریخ) - چون بازه‌ی
# زمانیِ کامل‌شده‌ی هر گزارش با بقیه فرق دارد.
DEFAULT_START_DATE = "1404/01/02"
DEFAULT_START_TIME = "00:00:00"

# پنجره‌ی بازبینی: تاریخ وصول/ثبت برخی ردیف‌ها بعداً تغییر می‌کنه (مثلاً فاکتوری که
# ۸ مهر ثبت شده و وصولش بعداً به ۱۱ مهر میفته)، و تماس‌های تبلیغاتی تا ۷ روز نوعشون عوض میشه.
# برای این گزارش‌ها، هر اجرا N روز آخر را دوباره دانلود می‌کند و فایل‌های قدیمیِ همان روزها
# (بعد از دانلود موفق) جایگزین می‌شوند، تا هر ردیف فقط یک‌بار و با آخرین وضعیتش بماند.
WINDOW_DAYS = {
    "INV_SAL_HK": 7,
    "INV_SAL_54": 7,
    "SaleR_HK": 6,
    "SaleR_54": 6,
    "VP_HK": 7,
    "VP_54": 7,
    "VOI_INC_54": 7,
    "EXT_HK": 7,
    "EXT_54": 7,
}

# محل نگهداری فایل‌های قدیمیِ جایگزین‌شده (پاک نمی‌شوند، فقط جابه‌جا)
RETIRED_ROOT = RAW_DATA_ROOT.parent / "_retired_raw"

# فاصله (به ثانیه) بین دو فراخوانی دانلودر پشت‌سرهم
# برای جلوگیری از فشار زیاد روی سرور مبدا. اگر نیازی نیست 0 بگذارید.
DELAY_BETWEEN_CALLS_SECONDS = 30.0


# ============================================================
# دانلودرهای پروژه
# ============================================================
#
# simple_signature=True  -> fetch_func(period_start, period_end)
# simple_signature=False -> fetch_func(None, period_start, period_end)
#
# report_code/company_code باید دقیقاً با ثابت‌های REPORT_CODE/COMPANY_CODE
# داخل خود فایل دانلودر یکی باشند - چون برای پیدا کردن پوشه‌ی raw_data و
# پارس کردن آخرین تاریخ دانلودشده استفاده می‌شوند (اسم‌شان همیشه با label
# یکی نیست، مثلاً CON_LST_HK در واقع در raw_data/ListMoshaver/HK می‌نویسد).

@dataclass(frozen=True)
class DownloaderSpec:
    label: str
    fetch: Callable
    simple_signature: bool
    report_code: str
    company_code: str


DOWNLOADERS: Tuple[DownloaderSpec, ...] = (
    DownloaderSpec("INV_SAL_HK", fetch_INV_SAL_HK, False, "INV_SAL", "HK"),
    DownloaderSpec("INV_SAL_54", fetch_INV_SAL_54, False, "INV_SAL", "54"),
    DownloaderSpec("VP_HK", fetch_vp_hk, False, "VP", "HK"),
    DownloaderSpec("VP_54", fetch_vp_54, False, "VP", "54"),
    DownloaderSpec("SCL_HK", fetch_SCL_HK, False, "SC", "HK"),
    DownloaderSpec("SaleR_HK", fetch_SaleR_HK, False, "SaleR", "HK"),
    DownloaderSpec("SaleR_54", fetch_SaleR_54, False, "SaleR", "54"),
    DownloaderSpec("APT_LST_HK", fetch_APT_LST_HK, False, "Nobat", "HK"),
    DownloaderSpec("CON_LST_HK", fetch_CON_LST_HK, False, "ListMoshaver", "HK"),
    DownloaderSpec("AGN_LST_54", fetch_AGN_LST_54, False, "ListN", "54"),
    DownloaderSpec("VOI_INC_54", fetch_VOI_INC_54, False, "VoipTV", "54"),
    DownloaderSpec("SPK_54", fetch_SPK_54, False, "SPK", "54"),
    DownloaderSpec("EXT_HK", fetch_EXT_HK, False, "EXT", "HK"),
    DownloaderSpec("EXT_54", fetch_EXT_54, False, "EXT", "54"),
)


def iter_daily_ranges(
    start_datetime: "jdatetime.datetime",
    end_datetime: "jdatetime.datetime",
) -> Iterator[Tuple["jdatetime.datetime", "jdatetime.datetime"]]:

    current_start = start_datetime

    while current_start.date() <= end_datetime.date():

        is_last_day = current_start.date() == end_datetime.date()

        current_end = (
            end_datetime
            if is_last_day
            else current_start.replace(
                hour=23, minute=59, second=59, microsecond=0
            )
        )

        yield current_start, current_end

        if is_last_day:
            break

        current_start = (current_start + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )


def _call_downloader(
    spec: DownloaderSpec,
    period_start: "jdatetime.datetime",
    period_end: "jdatetime.datetime",
):

    if spec.simple_signature:
        return spec.fetch(period_start, period_end)

    return spec.fetch(None, period_start, period_end)


def _extract_save_path(result: Union[dict, str, Path]) -> Path:
    """Downloaders return either {"path": ..., "rows": ...} or a bare path."""
    if isinstance(result, dict):
        return Path(result["path"])
    return Path(result)


_FILENAME_RE_CACHE = {}


def _filename_pattern(report_code: str, company_code: str) -> "re.Pattern":
    key = (report_code, company_code)
    pattern = _FILENAME_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(
            rf"^{re.escape(company_code)}_{re.escape(report_code)}_"
            rf"(\d{{14}})_(\d{{14}})_\d{{14}}\.parquet$"
        )
        _FILENAME_RE_CACHE[key] = pattern
    return pattern


def latest_downloaded_period_end(
    report_code: str, company_code: str
) -> Optional["jdatetime.datetime"]:
    """Look at every Parquet file already saved under
    raw_data/<report_code>/<company_code>/ and return the latest
    period_end encoded in their filenames, or None if that downloader
    has never successfully saved a file yet."""
    folder = RAW_DATA_ROOT / report_code / company_code
    if not folder.is_dir():
        return None

    pattern = _filename_pattern(report_code, company_code)
    latest = None

    for file_path in folder.glob("*.parquet"):
        match = pattern.match(file_path.name)
        if not match:
            continue
        period_end = jdatetime.datetime.strptime(match.group(2), "%Y%m%d%H%M%S")
        if latest is None or period_end > latest:
            latest = period_end

    return latest


def resolve_spec_range(
    spec: DownloaderSpec,
    default_start: "jdatetime.datetime",
    now: "jdatetime.datetime",
) -> Optional[Tuple["jdatetime.datetime", "jdatetime.datetime"]]:
    """Each downloader resumes from the day after its own latest saved
    file, not from a global date shared by every report - the reports
    are at very different points in their historical backfill."""
    latest = latest_downloaded_period_end(spec.report_code, spec.company_code)
    window = WINDOW_DAYS.get(spec.label)

    if latest is not None:
        # آخرین فایل اگر روز را تا ۲۳:۵۹:۵۹ نپوشانده (اجرای وسط روز)، همان روز
        # دوباره کامل گرفته می‌شود - وگرنه بقیه‌ی آن روز هیچ‌وقت دانلود نمی‌شد.
        if (latest.hour, latest.minute, latest.second) == (23, 59, 59):
            resume_day = latest + timedelta(days=1)
        else:
            resume_day = latest
        spec_start = resume_day.replace(hour=0, minute=0, second=0, microsecond=0)
        if window:
            window_start = (now - timedelta(days=window)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            spec_start = min(spec_start, window_start)
        spec_start = max(spec_start, default_start)
    else:
        spec_start = default_start

    if spec_start > now:
        return None

    return spec_start, now


def _retire_old_files_for_day(
    conn,
    spec: DownloaderSpec,
    day,
    keep_path: Path,
) -> None:
    """Replace the older Parquet file(s) of one day with the freshly downloaded one.

    Runs only after the new file for that day exists, so a failed download never
    deletes the previous data. The old file is moved to RETIRED_ROOT (not deleted),
    its rows are removed from SQL and its tracking entry is cleared.
    """
    logger = logging.getLogger(__name__)
    folder = RAW_DATA_ROOT / spec.report_code / spec.company_code
    if not folder.is_dir():
        return

    pattern = _filename_pattern(spec.report_code, spec.company_code)
    keep_resolved = keep_path.resolve()

    for file_path in folder.glob("*.parquet"):
        if file_path.resolve() == keep_resolved:
            continue
        match = pattern.match(file_path.name)
        if not match:
            continue
        file_start = jdatetime.datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        if file_start.date() != day:
            continue

        relative_path = str(file_path.relative_to(RAW_DATA_ROOT)).replace("\\", "/")
        if table_exists(conn, spec.label):
            delete_rows_for_file(conn, spec.label, relative_path)
        unmark_file_loaded(conn, relative_path)

        target = RETIRED_ROOT / spec.report_code / spec.company_code / file_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        file_path.replace(target)
        logger.info("%s | retired old file for %s: %s", spec.label, day, file_path.name)
    conn.commit()


def _load_result_into_sql(conn, spec: DownloaderSpec, result) -> None:
    """Load the Parquet file a downloader just wrote into its SQL table.

    Table name matches spec.label (REPORT_CODE_COMPANY_CODE), the same
    convention load_raw_data_to_sql.py uses. Safe to call repeatedly: a
    file already recorded in dbo.LoadedFiles is skipped.
    """
    save_path = _extract_save_path(result)
    relative_path = str(save_path.relative_to(RAW_DATA_ROOT)).replace("\\", "/")

    if is_file_loaded(conn, relative_path):
        return

    df = pd.read_parquet(save_path)
    row_count = load_dataframe_into_table(conn, spec.label, df, relative_path)
    mark_file_loaded(conn, relative_path, spec.label, row_count)


def main():

    configure_logging()
    logger = logging.getLogger(__name__)

    default_start = parse_jalali_datetime(DEFAULT_START_DATE, DEFAULT_START_TIME)
    now = now_jalali()

    logger.info("=" * 70)
    logger.info(
        "Download started | default start (for reports with no data yet) %s | until now %s",
        default_start.strftime("%Y/%m/%d %H:%M:%S"),
        now.strftime("%Y/%m/%d %H:%M:%S"),
    )
    logger.info("=" * 70)

    total_days = 0
    total_success = 0
    total_failed = 0
    per_downloader_stats = {spec.label: {"success": 0, "failed": 0} for spec in DOWNLOADERS}

    conn = None
    if ENABLE_SQL_LOAD:
        ensure_database(SQL_SERVER, SQL_DATABASE)
        conn = get_connection(SQL_SERVER, SQL_DATABASE)
        ensure_tracking_table(conn)

    try:
        for spec in DOWNLOADERS:

            spec_range = resolve_spec_range(spec, default_start, now)
            if spec_range is None:
                logger.info("%s | already up to date, nothing to download", spec.label)
                continue

            spec_start, spec_end = spec_range

            logger.info("=" * 70)
            logger.info(
                "%s | resuming from %s -> %s",
                spec.label,
                spec_start.strftime("%Y/%m/%d %H:%M:%S"),
                spec_end.strftime("%Y/%m/%d %H:%M:%S"),
            )

            for period_start, period_end in iter_daily_ranges(spec_start, spec_end):

                total_days += 1

                try:
                    logger.info(
                        "%s | downloading: %s -> %s",
                        spec.label,
                        period_start.strftime("%Y/%m/%d %H:%M:%S"),
                        period_end.strftime("%Y/%m/%d %H:%M:%S"),
                    )

                    result = _call_downloader(spec, period_start, period_end)

                    if ENABLE_SQL_LOAD:
                        # هر بازه از ۰۰:۰۰ همان روز شروع می‌شود و تا ۲۳:۵۹:۵۹ (یا «الان» برای
                        # امروز) می‌رود، پس فایل تازه همه‌ی فایل‌های قبلیِ آن روز (نسخه‌ی کهنه
                        # یا نیم‌روزه) را پوشش می‌دهد و آن‌ها کنار گذاشته می‌شوند.
                        _retire_old_files_for_day(
                            conn, spec, period_start.date(), _extract_save_path(result)
                        )
                        _load_result_into_sql(conn, spec, result)

                    total_success += 1
                    per_downloader_stats[spec.label]["success"] += 1

                    logger.info("%s | completed: %s", spec.label, result)

                except Exception:

                    total_failed += 1
                    per_downloader_stats[spec.label]["failed"] += 1
                    if conn is not None:
                        conn.rollback()

                    logger.exception(
                        "%s | FAILED for range %s -> %s",
                        spec.label,
                        period_start.strftime("%Y/%m/%d %H:%M:%S"),
                        period_end.strftime("%Y/%m/%d %H:%M:%S"),
                    )
                    # اگر یک گزارش خطا داد، روز بعدِ همین گزارش و بقیه‌ی
                    # گزارش‌ها همچنان اجرا می‌شوند.
                    continue

                finally:
                    if DELAY_BETWEEN_CALLS_SECONDS > 0:
                        time.sleep(DELAY_BETWEEN_CALLS_SECONDS)
    finally:
        if conn is not None:
            conn.close()

    # ========================================================
    # خلاصه نهایی
    # ========================================================

    logger.info("=" * 70)
    logger.info(
        "Download finished | days=%d | successful=%d | failed=%d",
        total_days,
        total_success,
        total_failed,
    )
    for label, stats in per_downloader_stats.items():
        logger.info(
            "  %-14s | success=%d | failed=%d",
            label,
            stats["success"],
            stats["failed"],
        )
    logger.info("=" * 70)


if __name__ == "__main__":
    configure_logging()
    _logger = logging.getLogger(__name__)

    if not acquire_lock():
        _logger.info(
            "Another run of main.py appears to be in progress "
            "(lock file exists: %s). Skipping this run.",
            LOCK_PATH,
        )
    else:
        try:
            main()
        finally:
            release_lock()
