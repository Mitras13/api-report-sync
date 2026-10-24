import logging

from context import now_jalali
from .downloader_common import download_with_retry
from .downloader_core import (
    fetch_generic,
    api_datetime_str,
    stream_response_to_dataframe,
    build_raw_filename,
    build_raw_path,
    save_dataframe_as_parquet,
)

logger = logging.getLogger(__name__)

URL = "https://api.hamkadeh.com/api/entry/extract-numbers-new"
METHOD = "POST"
COMPANY_CODE = "HK"
REPORT_CODE = "EXT"


def build_params(period_start, period_end):
    return {}


def build_json_body(period_start, period_end):
    """This endpoint takes its period in the JSON body, not query params -
    ported from the legacy تمدیدی/HK.EXT.py reference script."""
    return {
        "product_id": 3,
        "reference": ["landing", "sms"],
        "entry_date_start": api_datetime_str(period_start),
        "entry_date_end": api_datetime_str(period_end),
    }


def fetch(context, period_start, period_end):
    """Standard contract every downloader implements. Cookie auth, like HK.FCR."""

    def attempt():
        response = fetch_generic(
            url=URL,
            method=METHOD,
            company_code=COMPANY_CODE,
            report_code=REPORT_CODE,
            period_start=period_start,
            period_end=period_end,
            build_params=build_params,
            build_json_body=build_json_body,
        )

        df = stream_response_to_dataframe(response)

        if df.empty:
            raise ValueError("API returned an empty dataset.")

        download_time = now_jalali()
        filename = build_raw_filename(
            COMPANY_CODE,
            REPORT_CODE,
            period_start,
            period_end,
            download_time,
        )
        save_path = build_raw_path(
            COMPANY_CODE,
            REPORT_CODE,
            filename,
        )

        save_dataframe_as_parquet(df, save_path)

        logger.info(
            "%s_%s | Parquet completed | rows=%d | path=%s",
            REPORT_CODE,
            COMPANY_CODE,
            len(df),
            save_path,
        )

        return {
            "path": str(save_path),
            "rows": len(df),
        }

    label = f"{REPORT_CODE}_{COMPANY_CODE}"
    return download_with_retry(
        attempt,
        max_retries=3,
        base_delay_seconds=30,
        label=label,
    )
