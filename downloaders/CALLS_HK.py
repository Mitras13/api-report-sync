"""تماس‌های مشاوران همکده (خروجی اکسل پنل 5040.5040.me) - یک روز در هر درخواست.

منتقل‌شده از D:\\Smart_telegram_bot\\API_Downloader\\HK\\CALLS.py (۲۰۲۶-۱۱-۱۷)، با دو تفاوت:
- خروجی Parquet در raw_data/CALLS/HK (نه CSV) -> جدول dbo.CALLS_HK.
- زمان با ثانیه فرستاده می‌شود: API دقت ثانیه را می‌پذیرد و end شامل است (تست ۱۴۰۵/۰۷/۰۱: دو نیمه‌ی
  00:00:00–11:59:59 و 12:00:00–23:59:59 = ۴۱۹۷ + ۶۲۷۰ = ۱۰۴۶۷ = کل روز). با قالب بی‌ثانیه‌ی نسخه‌ی قبلی،
  end=23:59 تماس‌های دقیقه‌ی آخر روز را جا می‌انداخت.

فیلتر تاریخ واقعی است (دو روز متفاوت، شناسه‌های بی‌اشتراک؛ همه‌ی ردیف‌ها jcalldate همان روز).
توکن: پنل هوشمند همکده (tokens/tokenSmartPanelHK.txt، همان SPA_HK). پاسخ Excel است، همه‌ی ستون‌ها متن
(شماره‌ها صفر اول دارند).

روز کامل بدون هیچ ردیفی ذخیره نمی‌شود (خطا -> تلاش دوباره): مرکز تماس روزی هزاران تماس دارد، پس پاسخ
خالی یعنی خطای سرور، نه روز بی‌تماس. بازه‌ی ناقصِ امروز (اجرای وسط روز) می‌تواند خالی باشد.
"""
import io
import logging

import pandas as pd

from context import now_jalali
from .downloader_common import download_with_retry
from .downloader_core import (
    InvalidContentError,
    api_datetime_str,
    build_raw_filename,
    build_raw_path,
    call_api,
    load_smart_panel_token,
    save_dataframe_as_parquet,
)

logger = logging.getLogger(__name__)

URL = "https://5040.5040.me/api/consultant/excel-entriescall"
COMPANY_CODE = "HK"
REPORT_CODE = "CALLS"
DATE_COLUMN = "jcalldate"


def build_json_body(period_start, period_end):
    return {"start": api_datetime_str(period_start), "end": api_datetime_str(period_end)}


def check_rows(df, period_start, period_end):
    if DATE_COLUMN not in df.columns:
        raise InvalidContentError(f"{REPORT_CODE}_{COMPANY_CODE}: column {DATE_COLUMN!r} missing")
    full_day = (period_end.hour, period_end.minute, period_end.second) == (23, 59, 59)
    if df.empty:
        if full_day:
            raise InvalidContentError(
                f"{REPORT_CODE}_{COMPANY_CODE}: no rows for full day {period_start:%Y/%m/%d}"
            )
        return
    days = set(df[DATE_COLUMN].astype(str).str[:10])
    wanted = {period_start.strftime("%Y-%m-%d"), period_end.strftime("%Y-%m-%d")}
    if not days <= wanted:
        raise InvalidContentError(
            f"{REPORT_CODE}_{COMPANY_CODE}: rows outside {sorted(wanted)}: {sorted(days - wanted)[:5]}"
        )


def fetch(context, period_start, period_end):
    if period_start.date() != period_end.date():
        raise ValueError("CALLS requests must cover only one day")

    def attempt():
        response = call_api(
            url=URL,
            method="POST",
            params=None,
            token=load_smart_panel_token(COMPANY_CODE),
            auth_mode="bearer",
            json_body=build_json_body(period_start, period_end),
        )
        try:
            content = response.content
        finally:
            response.close()
        if content[:2] != b"PK":
            raise InvalidContentError(
                f"{REPORT_CODE}_{COMPANY_CODE}: expected an Excel file, got {content[:200]!r}"
            )
        df = pd.read_excel(io.BytesIO(content), dtype=str).fillna("")
        check_rows(df, period_start, period_end)

        filename = build_raw_filename(COMPANY_CODE, REPORT_CODE, period_start, period_end, now_jalali())
        save_path = build_raw_path(COMPANY_CODE, REPORT_CODE, filename)
        save_dataframe_as_parquet(df, save_path)
        last = df["calldate"].max() if "calldate" in df.columns and not df.empty else None
        logger.info("%s_%s | Parquet completed | rows=%d | last call=%s | path=%s",
                    REPORT_CODE, COMPANY_CODE, len(df), last, save_path)
        return {"path": str(save_path), "rows": len(df)}

    return download_with_retry(attempt, max_retries=3, base_delay_seconds=2, label=f"{REPORT_CODE}_{COMPANY_CODE}")
