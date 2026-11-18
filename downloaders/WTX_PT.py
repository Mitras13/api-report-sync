"""پزشکت - تراکنش‌های کیف پول (همه‌ی reasonها، بدون فیلتر reason) - مشخصات کاربر ۲۰۲۶-۱۱-۱۶.

GET https://api.pezeshket.com/wallet/v1/admin/history  (offset/limit=100، startTime/endTime = unix seconds تهران)
userId/adviserId همه‌ی روز یک‌جا (بدون تکرار) با core/v1/users/bulkInfo غنی می‌شوند.
خروجی دقیقاً ۲۵ ستون WTX_COLUMNS به همین ترتیب؛ reason بدون هیچ تغییری (گزارش‌ها با زیررشته‌ی آن دسته‌بندی
می‌کنند)، amount ریال و بدون تغییر، createdAt = "yyyy/MM/dd HH:mm:ss" جلالی تهران.
WTX شناسه‌ی یکتا ندارد: کل روز جایگزین می‌شود (main.py: _retire_old_files_for_day + supersede در sql_loader).
ذخیره: Parquet در raw_data/WTX/PT (برای dbo.WTX_PT) + CSV مشخصات در raw_data_csv/WTX/PT.
"""
import datetime
import logging

import jdatetime
import pandas as pd

from context import now_jalali
from .downloader_core import build_raw_filename, build_raw_path, save_dataframe_as_parquet, InvalidContentError
from .pezeshket_core import (
    fetch_paginated, bulk_user_info, api_unix_timestamp, tehran_from_ms, sanitize_value, with_retry,
    save_spec_csv, EMPTY_BULK_INFO, STORE_PERSONAL_DATA,
)

URL = "https://api.pezeshket.com/wallet/v1/admin/history"
COMPANY_CODE = "PT"
REPORT_CODE = "WTX"

logger = logging.getLogger(__name__)

STATUS_LABELS = {"SETTLED": "تکمیل شده", "FAILED": "ناموفق"}
FAIL_STATE_LABELS = {"CanceledByUser": "لغو توسط کاربر"}

WTX_COLUMNS = [
    "reason", "advisorName", "patientName", "amount", "nickname", "gateway",
    "createdAt", "status", "gatewayFailCode", "failedAmount", "failedReason",
    "userId", "userType", "userNationalCode",
    "userAvatarColor", "userAvatarInitials", "userAvatarUrl", "userAvatarThumbnail",
    "advisorUserId", "advisorUserType", "advisorNationalCode",
    "advisorAvatarColor", "advisorAvatarInitials", "advisorAvatarUrl", "advisorAvatarThumbnail",
]
PERSONAL_COLUMNS = [
    "userNationalCode", "userAvatarColor", "userAvatarInitials", "userAvatarUrl", "userAvatarThumbnail",
    "advisorNationalCode", "advisorAvatarColor", "advisorAvatarInitials", "advisorAvatarUrl", "advisorAvatarThumbnail",
]


def _mapped_label(value, labels, kind):
    if value is None or value in labels:
        return labels.get(value, value)
    logger.warning("WTX_PT: unknown %s value %r - kept raw", kind, value)
    return value


def _dict(value):
    return value if isinstance(value, dict) else {}


def _flatten_row(row, info_by_id):
    # gateway / gatewayFailReason / reasonMetadata در خیلی از ردیف‌ها اصلاً کلید ندارند.
    reason_meta = _dict(row.get("reasonMetadata"))
    fail = _dict(row.get("gatewayFailReason"))
    fail_response = _dict(fail.get("response"))
    advisor_id = reason_meta.get("adviserId")
    user_info = info_by_id.get(row.get("userId")) or EMPTY_BULK_INFO
    advisor_info = (info_by_id.get(advisor_id) or EMPTY_BULK_INFO) if advisor_id else EMPTY_BULK_INFO
    created_ms = row.get("createdAt")
    out = {
        "reason": row.get("reason"),
        "advisorName": advisor_info["nickname"],
        "patientName": None,
        "amount": row.get("amount"),
        "nickname": user_info["nickname"],
        "gateway": row.get("gateway"),
        "createdAt": jdatetime.datetime.fromgregorian(datetime=tehran_from_ms(created_ms)).strftime("%Y/%m/%d %H:%M:%S")
        if created_ms else None,
        "status": _mapped_label(reason_meta.get("status"), STATUS_LABELS, "status"),
        "gatewayFailCode": fail.get("code"),
        "failedAmount": fail_response.get("amount"),
        "failedReason": _mapped_label(fail_response.get("state"), FAIL_STATE_LABELS, "failedReason"),
        "userId": row.get("userId"),
        "userType": user_info["userType"],
        "userNationalCode": user_info["nationalCode"],
        "userAvatarColor": user_info["avatarColor"],
        "userAvatarInitials": user_info["avatarInitials"],
        "userAvatarUrl": user_info["avatarUrl"],
        "userAvatarThumbnail": user_info["avatarThumbnail"],
        "advisorUserId": advisor_id,
        "advisorUserType": advisor_info["userType"],
        "advisorNationalCode": advisor_info["nationalCode"],
        "advisorAvatarColor": advisor_info["avatarColor"],
        "advisorAvatarInitials": advisor_info["avatarInitials"],
        "advisorAvatarUrl": advisor_info["avatarUrl"],
        "advisorAvatarThumbnail": advisor_info["avatarThumbnail"],
    }
    if not STORE_PERSONAL_DATA:
        for column in PERSONAL_COLUMNS:
            out[column] = None
    return {k: sanitize_value(v) for k, v in out.items()}


def build_params(period_start, period_end):
    def _build(offset, limit):
        return {"offset": offset, "limit": limit,
                "startTime": api_unix_timestamp(period_start),
                "endTime": api_unix_timestamp(period_end)}
    return _build


def fetch(context, period_start, period_end):
    def attempt():
        download_time = now_jalali()
        rows = fetch_paginated(URL, build_params(period_start, period_end), data_key="history")

        # محافظ: اگر API فیلتر تاریخ را نادیده بگیرد، فایل با تاریخ غلط ذخیره نشود.
        start = period_start.togregorian() - datetime.timedelta(seconds=1)
        end = period_end.togregorian() + datetime.timedelta(seconds=1)
        for row in rows:
            ms = row.get("createdAt")
            if ms and not start <= tehran_from_ms(ms) <= end:
                raise InvalidContentError(f"WTX_PT: createdAt {tehran_from_ms(ms)} outside requested range")

        ids = [r.get("userId") for r in rows] + [_dict(r.get("reasonMetadata")).get("adviserId") for r in rows]
        info_by_id = bulk_user_info(ids) if rows else {}
        df = pd.DataFrame([_flatten_row(r, info_by_id) for r in rows], columns=WTX_COLUMNS)

        save_spec_csv(df, REPORT_CODE, period_start, period_end, download_time)
        path = build_raw_path(COMPANY_CODE, REPORT_CODE, build_raw_filename(
            COMPANY_CODE, REPORT_CODE, period_start, period_end, download_time))
        save_dataframe_as_parquet(df, path)
        return {"path": str(path), "rows": len(df)}

    return with_retry(attempt, "WTX_PT")
