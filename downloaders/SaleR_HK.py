import io
import pandas as pd

from context import now_jalali
from .downloader_common import download_with_retry
from .downloader_core import (
    call_api,
    build_raw_filename,
    build_raw_path,
    save_dataframe_as_parquet,
    load_token,
)

URL = "https://api.hamkadeh.com/api/statistic/seller/sales"
METHOD = "GET"
COMPANY_CODE = "HK"
REPORT_CODE = "SaleR"
AUTH_MODE = "bearer"


def api_datetime_minute_str(jdt):
    return jdt.togregorian().strftime("%Y-%m-%d %H:%M")


def build_params(period_start, period_end):
    return {
        "export_data": "1",
        "start_date": api_datetime_minute_str(period_start),
        "end_date": api_datetime_minute_str(period_end),
    }


def fetch(context, period_start, period_end):

    def attempt():
        token = load_token(COMPANY_CODE)
        params = build_params(period_start, period_end)

        # اینجا خودمان response خام را می‌گیریم، نه از fetch_generic
        response = call_api(
            url=URL,
            method=METHOD,
            params=params,
            token=token,
            auth_mode=AUTH_MODE,
            json_body={},
        )

        excel_data = io.BytesIO(response.content)
        df = pd.read_excel(excel_data)

        if df.empty:
            raise ValueError(f"{REPORT_CODE}_{COMPANY_CODE}: API returned an empty Excel file")

        # حالا خودمان با همان قرارداد پروژه روی دیسک ذخیره می‌کنیم (Parquet)
        download_time = now_jalali()
        filename = build_raw_filename(COMPANY_CODE, REPORT_CODE, period_start, period_end, download_time)
        save_path = build_raw_path(COMPANY_CODE, REPORT_CODE, filename)
        save_dataframe_as_parquet(df, save_path)

        return save_path

    label = f"{REPORT_CODE}_{COMPANY_CODE}"
    return download_with_retry(
    attempt,
    max_retries=3,
    base_delay_seconds=2,
    label=label
)