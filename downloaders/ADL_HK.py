"""Hamkadeh advertisement list, partitioned by API created_at date."""
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from context import now_jalali
from .downloader_common import download_with_retry
from .downloader_core import (
    call_api, load_token, InvalidContentError, build_raw_filename,
    build_raw_path, save_dataframe_as_parquet,
)

URL = "https://api.hamkadeh.com/api/advertisement/index"
REPORT_CODE = "ADL"
COMPANY_CODE = "HK"
PER_PAGE = 100


def read_page(page, period_start, period_end):
    params = {
        "page": page, "per_page": PER_PAGE,
        "relations[]": ["campaign", "creator"],
        "start_created_at": period_start.togregorian().strftime("%Y-%m-%d %H:%M:%S"),
        "end_created_at": period_end.togregorian().strftime("%Y-%m-%d %H:%M:%S"),
    }
    response = call_api(URL, "GET", params, load_token(COMPANY_CODE), auth_mode="cookie")
    try:
        payload = response.json()
    except ValueError as exc:
        raise InvalidContentError("ADL_HK: invalid JSON") from exc
    finally:
        response.close()
    if not isinstance(payload, dict) or payload.get("status") is not True:
        raise InvalidContentError("ADL_HK: unsuccessful response")
    rows, meta = payload.get("data"), payload.get("meta", {})
    if not isinstance(rows, list) or not isinstance(meta, dict):
        raise InvalidContentError("ADL_HK: invalid pagination payload")
    if meta.get("current_page") != page or type(meta.get("last_page")) is not int:
        raise InvalidContentError("ADL_HK: missing pagination metadata")
    return rows, meta


def fetch(context, period_start, period_end):
    rows, seen = [], set()
    page, expected_total = 1, None
    while True:
        batch, meta = download_with_retry(
            lambda: read_page(page, period_start, period_end),
            max_retries=3, base_delay_seconds=2, label="ADL_HK",
        )
        if expected_total is None:
            expected_total = meta.get("total")
        if meta.get("total") != expected_total or not isinstance(expected_total, int):
            raise InvalidContentError("ADL_HK: pagination changed during download")
        for row in batch:
            if not isinstance(row, dict) or row.get("id") is None or row["id"] in seen:
                raise InvalidContentError("ADL_HK: invalid or repeated advertisement")
            # Verify the API actually applied the requested created_at filter.
            # API timestamps carry UTC (Z); requested filters use Tehran local time.
            # Convert only for validation; preserve the original raw timestamp.
            try:
                created = datetime.fromisoformat(str(row.get("created_at", "")).replace("Z", "+00:00"))
                if created.tzinfo is not None:
                    created = created.astimezone(ZoneInfo("Asia/Tehran")).replace(tzinfo=None)
            except (ValueError, TypeError) as exc:
                raise InvalidContentError("ADL_HK: invalid created_at timestamp") from exc
            start = period_start.togregorian()
            end = period_end.togregorian()
            if not start <= created <= end:
                raise InvalidContentError("ADL_HK: row outside requested created_at range")
            seen.add(row["id"])
            rows.append({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                         for k, v in row.items()})
        if page >= meta["last_page"]:
            break
        if not batch:
            raise InvalidContentError("ADL_HK: premature empty page")
        page += 1
        time.sleep(1)
    if len(rows) != expected_total:
        raise InvalidContentError("ADL_HK: incomplete pagination")
    # Empty days are valid and must also replace previously downloaded rows.
    df = pd.DataFrame(rows) if rows else pd.DataFrame({"id": pd.Series(dtype="int64")})
    filename = build_raw_filename(COMPANY_CODE, REPORT_CODE, period_start, period_end, now_jalali())
    path = build_raw_path(COMPANY_CODE, REPORT_CODE, filename)
    save_dataframe_as_parquet(df, path)
    return {"path": str(path), "rows": len(df)}
