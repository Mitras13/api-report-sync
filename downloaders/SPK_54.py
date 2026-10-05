import logging

from .downloader_common import download_with_retry
from .downloader_core import fetch_smart_panel_json

logger = logging.getLogger(__name__)

URL = "https://5040-product.5040.me/api/report/smart/calculate/1172"
COMPANY_CODE = "54"
REPORT_CODE = "SPK"  # Smart panel, per-کارشناس Kartabeli calculate report

# Fixed id assigned by the smart panel to this specific output-generator,
# confirmed from a real captured request (2026-09-13) in Robot_Reward's
# API_Downloader/SP/54/SPK.py - same logic ported here, only the on-disk
# format changed (Parquet instead of that project's CSV, via
# fetch_smart_panel_json). Gives a per-کارشناس SUMMARY table directly
# (answered_count, paid_coe, ...), not raw per-call rows.
OUTPUT_GENERATOR_ID = "1172"

# Full column list of this endpoint's per-کارشناس response row (given by the
# user, 2026-09-15). Money columns (paid, cartable_paid, manual_paid,
# registered_factor, ...) are in میلیون تومان (confirmed for cartable_paid
# only; not independently re-verified per column here).
#   AAName                              کارشناس
#   supervisor__name                    سوپروایزر
#   CPC                                 قیمت هر تماس
#   answered_count                      تعداد پاسخ داد
#   answered_percent                    درصد پاسخ داد
#   bought_percent_cartable             درصد خرید کارتابلی
#   bought_percent_total                درصد خرید کل
#   call_duration                       مدت مکالمه
#   calls_count                         تعداد تماس
#   cartable_paid                       وصولی کارتابلی
#   cartable_registered_factor          ثبت کارتابلی
#   entries_count                       تعداد شماره دریافتی
#   manual_paid                         مبلغ وصولی دستی
#   manual_registered_factor            مبلغ ثبت دستی
#   money_coe                           ضریب پولی
#   number_cartable_paid                تعداد وصولی کارتابلی
#   number_cartable_registered_factor   تعداد فاکتور ثبت شده کارتابلی
#   number_manual_paid                  تعداد ثبت وصول کارتابلی
#   number_manual_registered_factor     تعداد ثبت دستی
#   number_paid                         تعداد وصولی کل
#   number_registered_factor            تعداد ثبت کلی
#   paid                                وصولی کل
#   paid_coe                            ضریب وصولی
#   paid_percent                        درصد وصولی
#   past_registered_paid                وصولی با ثبت گذشته
#   registered_factor                   مبلغ ثبت کلی
#   registered_paid                     ثبت و وصول


def build_json_body(period_start, period_end):
    """
    ⚠️ Different shape from a plain {"start","end","id"} body - this
    endpoint wants the period wrapped in a "date" list of one object, with
    BOTH a "start"/"end" (Gregorian, "YYYY-MM-DD HH:MM") and a same-value
    "startHelp"/"endHelp" + "startj"/"endj" (also Gregorian in the real
    captured request, despite the "j" suffix), plus "av_date_ls": [] and
    startTime/EndTime: null. Copied exactly as observed working in
    Robot_Reward - do not simplify without re-capturing a real request.
    """
    start_dt = period_start.togregorian()
    end_dt = period_end.togregorian()
    start_str = start_dt.strftime("%Y-%m-%d %H:%M")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M")
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    return {
        "av_date_ls": [],
        "date": [
            {
                "start": start_str,
                "startHelp": start_date,
                "startj": start_date,
                "end": end_str,
                "endHelp": end_date,
                "endj": end_date,
                "startTime": None,
                "EndTime": None,
            }
        ],
        "id": OUTPUT_GENERATOR_ID,
    }


def fetch(context, period_start, period_end):
    """Standard contract every downloader implements."""

    def attempt():
        return fetch_smart_panel_json(
            url=URL,
            company_code=COMPANY_CODE,
            report_code=REPORT_CODE,
            period_start=period_start,
            period_end=period_end,
            build_json_body=build_json_body,
        )

    label = f"{REPORT_CODE}_{COMPANY_CODE}"
    return download_with_retry(attempt, max_retries=3, base_delay_seconds=2, label=label)
