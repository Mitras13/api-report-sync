"""پزشکت - مصرف کد تخفیف (Discount Code Usage) - مشخصات کاربر ۲۰۲۶-۱۱-۱۶.

GET https://api.pezeshket.com/core/v1/admin/discountCodes/usages
    startTime/endTime (unix seconds تهران)، exportFileType=EXCEL، expLimit=100000؛ پاسخ xlsx باینری (باید با PK شروع شود).
همه‌ی ستون‌ها با همان نام و ترتیب اکسل می‌مانند (هیچ ستونی اضافه/حذف نمی‌شود). ستون‌های فعلی:
    شناسه، عنوان، کد، نوع، مبلغ، تخفیف، زمان مصرف، نوع مشاوره، مبلغ کل، قابل پرداخت،
    شناسه کاربر، کاربر، شماره همراه کاربر، مشاور، شماره همراه مشاور، تخصص
عنوان بدون تغییر (گزارش‌ها با زیررشته دسته‌بندی می‌کنند). شماره‌های همراه بدون PT_STORE_PERSONAL_DATA خالی ذخیره می‌شوند.
ذخیره: Parquet در raw_data/DCU/PT (برای dbo.DCU_PT) + CSV مشخصات در raw_data_csv/DCU/PT.
"""
import io
import logging

import pandas as pd

from context import now_jalali
from .downloader_core import build_raw_filename, build_raw_path, save_dataframe_as_parquet
from .pezeshket_core import (
    fetch_excel, api_unix_timestamp, sanitize_value, with_retry, save_spec_csv, STORE_PERSONAL_DATA,
)

URL = "https://api.pezeshket.com/core/v1/admin/discountCodes/usages"
COMPANY_CODE = "PT"
REPORT_CODE = "DCU"
EXP_LIMIT = 100000
PERSONAL_COLUMNS = ["شماره همراه کاربر", "شماره همراه مشاور"]

logger = logging.getLogger(__name__)


def build_params(period_start, period_end):
    return {
        "startTime": api_unix_timestamp(period_start),
        "endTime": api_unix_timestamp(period_end),
        "exportFileType": "EXCEL",
        "expLimit": EXP_LIMIT,
    }


def fetch(context, period_start, period_end):
    def attempt():
        download_time = now_jalali()
        content = fetch_excel(URL, build_params(period_start, period_end))
        df = pd.read_excel(io.BytesIO(content))
        for column in df.columns:
            if df[column].dtype == object:
                df[column] = df[column].map(sanitize_value)
        if not STORE_PERSONAL_DATA:
            for column in PERSONAL_COLUMNS:
                if column in df.columns:
                    df[column] = None
        if len(df) >= EXP_LIMIT:
            logger.warning("DCU_PT: %d rows hit expLimit for %s - data may be truncated", len(df), period_start)

        save_spec_csv(df, REPORT_CODE, period_start, period_end, download_time)
        path = build_raw_path(COMPANY_CODE, REPORT_CODE, build_raw_filename(
            COMPANY_CODE, REPORT_CODE, period_start, period_end, download_time))
        save_dataframe_as_parquet(df, path)
        return {"path": str(path), "rows": len(df)}

    return with_retry(attempt, "DCU_PT")
