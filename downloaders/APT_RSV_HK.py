"""نوبت‌های همکده بر اساس «تاریخ نوبت» (نه تاریخ ثبت) - برای وضعیت نهایی هر نوبت.

APT_LST_HK همین اندپوینت را با start_created_at/end_created_at (تاریخ ثبت) و یک بار می‌گیرد، پس نوبتی
که برای روزهای بعد ثبت شده با وضعیت «منتظر تماس» می‌ماند. این دانلودر روزِ تمام‌شده را با فیلتر
start_reserved_at/end_reserved_at (تاریخ نوبت؛ پیدا شده ۲۰۲۶-۱۱-۰۷ - ۱۴۰۵/۰۷/۰۱ عیناً با پنل خواند)
دوباره می‌گیرد.

- فایل‌ها در raw_data/NobatDate/HK (پوشه‌ی جدا، تا جایگزینیِ «همان بازه» در sql_loader و
  _retire_old_files_for_day فایل‌های تاریخ ثبت را پاک نکنند)، ولی ردیف‌ها در همان جدول dbo.APT_LST_HK.
- آخرین وضعیت هر [شناسه] = ردیفی که _SourceFile آن بیشترین «زمان دانلود» (۱۴ رقم آخر نام فایل) را دارد.
  (مقایسه‌ی کل رشته‌ی _SourceFile کافی نیست: 'NobatDate/' همیشه از 'Nobat/' بزرگ‌تر است.)
- پاسخ Excel است (نه CSV)، مثل CON_LST_HK.
"""
import io
import logging

import pandas as pd

from context import now_jalali
from .downloader_common import download_with_retry
from .downloader_core import (
    InvalidContentError,
    build_raw_filename,
    build_raw_path,
    call_api,
    load_token,
    save_dataframe_as_parquet,
)

logger = logging.getLogger(__name__)

URL = "https://api.hamkadeh.com/api/reservation/index"
METHOD = "GET"
COMPANY_CODE = "HK"
REPORT_CODE = "NobatDate"
TABLE_NAME = "APT_LST_HK"
AUTH_MODE = "cookie"
DATE_COLUMN = "تاریخ نوبت"


def api_datetime_minute_str(jdt):
    return jdt.togregorian().strftime("%Y-%m-%d %H:%M")


def build_params(period_start, period_end):
    return {
        "export_data": "1",
        "start_reserved_at": api_datetime_minute_str(period_start),
        "end_reserved_at": api_datetime_minute_str(period_end),
    }


def check_filtered(df, period_start, period_end):
    """هر ردیف باید تاریخ نوبتش داخل همان روز باشد؛ وگرنه فیلتر رعایت نشده و فایل ذخیره نمی‌شود."""
    if DATE_COLUMN not in df.columns:
        raise InvalidContentError(f"{REPORT_CODE}_{COMPANY_CODE}: column {DATE_COLUMN!r} missing")
    if df.empty:
        return
    days = set(df[DATE_COLUMN].astype(str).str[:10])
    wanted = {period_start.strftime("%Y-%m-%d"), period_end.strftime("%Y-%m-%d")}
    if not days <= wanted:
        raise InvalidContentError(
            f"{REPORT_CODE}_{COMPANY_CODE}: rows outside {sorted(wanted)}: {sorted(days - wanted)[:5]}"
        )


def fetch(context, period_start, period_end):

    def attempt():
        response = call_api(
            url=URL,
            method=METHOD,
            params=build_params(period_start, period_end),
            token=load_token(COMPANY_CODE),
            auth_mode=AUTH_MODE,
            json_body={},
        )
        if response.content[:2] != b"PK":
            raise InvalidContentError(
                f"{REPORT_CODE}_{COMPANY_CODE}: expected an Excel file, got {response.text[:200]!r}"
            )
        df = pd.read_excel(io.BytesIO(response.content))
        # روز بدون نوبت مجاز است (فایل خالی با سرستون‌ها ذخیره می‌شود)، فقط سرستون باید باشد.
        check_filtered(df, period_start, period_end)

        filename = build_raw_filename(COMPANY_CODE, REPORT_CODE, period_start, period_end, now_jalali())
        save_path = build_raw_path(COMPANY_CODE, REPORT_CODE, filename)
        save_dataframe_as_parquet(df, save_path)
        logger.info("%s_%s | Parquet completed | rows=%d | path=%s", REPORT_CODE, COMPANY_CODE, len(df), save_path)
        return {"path": str(save_path), "rows": len(df)}

    return download_with_retry(attempt, max_retries=3, base_delay_seconds=2, label=f"{REPORT_CODE}_{COMPANY_CODE}")
