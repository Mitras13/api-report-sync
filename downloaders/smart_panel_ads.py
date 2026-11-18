"""Shared logic of the smart panel advertising report (SPA_54 / SPA_HK).

POST <host>/api/report/smart/calculate-ads/<id> - note "calculate-ads", not
SPK_54's "calculate" (calculate/484 answers 403 "User is Not Author").

The response holds TWO overlapping levels (checked 1405/08/09 for both companies):
  - agency rows (54: رنجبران، پرواز، ...، سایت 5040 / HK: رومزپور، دوستی، ...، سایت):
    their sum equals the panel's total row exactly.
  - leader rows (مسئول تبلیغات): the same agencies grouped by leader, named as
    <host>/api/user/LeaderAds/ lists them (54 prefixes "mahsul": mahsulبزرگی;
    HK does not: قلی پور), plus, for 54 only, "0" for agencies with no leader.
Summing every row would count each day twice, so each row gets
RowType = "agency" | "leader" and the total row is dropped. The API suffixes
every column with the index of the requested date range ("__0"); we always
request one range, so the suffix is stripped. Columns (meanings by analogy
with SPK_54, not confirmed by the panel owner):
  AAName                    عاملیت / مسئول
  CPC                       قیمت هر تماس
  answered_percent          درصد پاسخ داد
  bought_percent            درصد خرید
  call_duration             مدت مکالمه
  duration_coe              ضریب مدت مکالمه
  money_coe                 ضریب پولی
  number_answered           تعداد پاسخ داد
  number_calls              تعداد تماس
  number_consume_calls      تعداد شماره‌ی مصرف‌شده (تماس‌گرفته)
  number_entries            تعداد شماره‌ی ورودی
  number_paid               تعداد وصولی
  number_reach_answered     تعداد شماره‌ی پاسخ‌داده
  number_registered         تعداد ثبت
  paid_coe                  ضریب وصولی (HK: often null)
  paid_factor               مبلغ وصولی (میلیون تومان)
  paid_percent              درصد وصولی
  percent_target_number     درصد تحقق هدف
  rch_ans_percent           درصد پاسخ‌داده از ورودی
  registered_factor         مبلغ ثبت (میلیون تومان)
  target_number             هدف

⚠️ GET only on LeaderAds - POST to it creates a new leader.
"""
import logging

import pandas as pd

from .downloader_common import download_with_retry
from .downloader_core import call_api, fetch_smart_panel_json, load_smart_panel_token

logger = logging.getLogger(__name__)

REPORT_CODE = "SPA"


def build_json_body(period_start, period_end, output_generator_id):
    """Same body shape as SPK_54 (captured from the real panel request)."""
    start_dt = period_start.togregorian()
    end_dt = period_end.togregorian()
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    return {
        "av_date_ls": [],
        "date": [
            {
                "start": start_dt.strftime("%Y-%m-%d %H:%M"),
                "startHelp": start_date,
                "startj": start_date,
                "end": end_dt.strftime("%Y-%m-%d %H:%M"),
                "endHelp": end_date,
                "endj": end_date,
                "startTime": None,
                "EndTime": None,
            }
        ],
        "id": output_generator_id,
    }


def fetch_leader_names(company_code, leaders_url):
    token = load_smart_panel_token(company_code)
    response = call_api(
        url=leaders_url, method="GET", params=None, token=token, auth_mode="bearer"
    )
    try:
        return {str(item["name"]) for item in response.json()}
    finally:
        response.close()


def make_transform(label, leader_names, total_row_name):
    leader_names = set(leader_names) | {"0"}

    def transform_df(df, period_start, period_end):
        if df.empty and "AAName" not in df.columns:
            # "آماری وجود ندارد": saved as an empty file so the day counts as done.
            logger.info("%s %s | panel says no stats for this day", label, period_start.strftime("%Y/%m/%d"))
            return pd.DataFrame(columns=["ReportDate", "ReportDateJalali", "RowType", "AAName"], dtype=object)

        df = df.rename(columns=lambda c: c[:-3] if c.endswith("__0") else c)
        df["AAName"] = df["AAName"].astype(str)

        is_total = df["AAName"] == total_row_name
        total = df[is_total]
        df = df[~is_total].reset_index(drop=True)
        row_type = df["AAName"].map(lambda n: "leader" if n in leader_names else "agency")

        if total.empty:
            logger.warning(
                "%s %s | total row %r not found - check the response shape",
                label, period_start.strftime("%Y/%m/%d"), total_row_name,
            )
        else:
            expected = float(total["number_entries"].iloc[0])
            agency_sum = float(df.loc[row_type == "agency", "number_entries"].sum())
            if abs(agency_sum - expected) > 0.5:
                logger.warning(
                    "%s %s | agency rows sum to %s entries but the total row says %s "
                    "- RowType split may be wrong (new leader name?)",
                    label, period_start.strftime("%Y/%m/%d"), agency_sum, expected,
                )

        # Report day as its own column, so the dashboard/AI don't have to parse _SourceFile.
        df.insert(0, "ReportDate", period_start.togregorian().strftime("%Y-%m-%d"))
        df.insert(1, "ReportDateJalali", period_start.strftime("%Y/%m/%d"))
        df.insert(2, "RowType", row_type)
        return df

    return transform_df


def fetch_ads(
    company_code, url, leaders_url, output_generator_id, total_row_name,
    period_start, period_end,
):
    label = f"{REPORT_CODE}_{company_code}"

    def attempt():
        transform_df = make_transform(
            label, fetch_leader_names(company_code, leaders_url), total_row_name
        )
        return fetch_smart_panel_json(
            url=url,
            company_code=company_code,
            report_code=REPORT_CODE,
            period_start=period_start,
            period_end=period_end,
            build_json_body=lambda s, e: build_json_body(s, e, output_generator_id),
            transform_df=transform_df,
        )

    return download_with_retry(attempt, max_retries=3, base_delay_seconds=2, label=label)
