import logging

from context import now_jalali
from .downloader_common import download_with_retry
from .downloader_core import (
    fetch_generic,
    api_datetime_str,
    build_raw_filename,
    build_raw_path,
    stream_response_to_dataframe,
    save_dataframe_as_parquet,
)

logger = logging.getLogger(__name__)

URL = "https://api.5040.me/api/v1/factor-extraction"
METHOD = "POST"
COMPANY_CODE = "54"
REPORT_CODE = "INV_SAL"


def build_params(period_start, period_end):
    """Only the parameters specific to THIS report/endpoint."""
    return {
        "filter": 1,
        "startInvoiceDate": api_datetime_str(period_start),
        "endInvoiceDate": api_datetime_str(period_end),
    }


def fetch(context, period_start, period_end):
    """Download the report and save it only as a Parquet file."""

    def attempt():
        response = fetch_generic(
            url=URL,
            method=METHOD,
            company_code=COMPANY_CODE,
            report_code=REPORT_CODE,
            period_start=period_start,
            period_end=period_end,
            build_params=build_params,
            auth_mode="bearer",
            json_body={},
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
        base_delay_seconds=2,
        label=label,
    )
