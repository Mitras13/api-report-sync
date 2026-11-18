"""بازبینی روزهای CALLS_HK: روز ناموجود یا مشکوک به ناقص را پیدا می‌کند، چند بار دوباره می‌گیرد و گزارش می‌دهد.

روز «مشکوک» یعنی یکی از این‌ها (روز کامل تا ۲۳:۵۹:۵۹ ولی):
- تعداد ردیف کمتر از ۴۰٪ میانه‌ی همان روزِ هفته در کل بازه (جمعه‌ها با جمعه‌ها)،
- آخرین تماس قبل از ۲۰:۰۰ یا اولین تماس بعد از ۰۹:۰۰.
برای روز ناموجود: تا MAX_TRIES بار دانلود (با مسیر معمول main: فایل + جایگزینی + SQL).
برای روز مشکوک: دوباره از API می‌گیرد؛ اگر ردیف بیشتری آمد جایگزین می‌شود، وگرنه «پاسخ API ثابت است».
خروجی: logs/calls_audit.csv و خلاصه در کنسول.

    python scripts/audit_calls.py [1405/01/01]
"""
import csv
import io
import logging
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import jdatetime  # noqa: E402
import pandas as pd  # noqa: E402

import main  # noqa: E402
from backfill_backward import wait_while_main_runs  # noqa: E402
from context import now_jalali  # noqa: E402
from db.sql_loader import ensure_tracking_table, get_connection, table_exists  # noqa: E402
from downloaders import CALLS_HK as calls  # noqa: E402
from downloaders.downloader_core import call_api, configure_logging, load_smart_panel_token  # noqa: E402
from load_raw_data_to_sql import SQL_DATABASE, SQL_SERVER  # noqa: E402

MAX_TRIES = 4
RETRY_WAIT = 120
DELAY = 10
SPEC = next(s for s in main.DOWNLOADERS if s.label == "CALLS_HK")
OUT = ROOT / "logs" / "calls_audit.csv"


def sql_days(conn):
    """روز -> (ردیف، اولین تماس، آخرین تماس) از جدول، فقط فایل‌های روز کامل."""
    if not table_exists(conn, SPEC.table):
        return {}
    rows = conn.cursor().execute(
        "SELECT _SourceFile, COUNT(*), MIN(calldate), MAX(calldate) FROM dbo.CALLS_HK GROUP BY _SourceFile"
    ).fetchall()
    out = {}
    pattern = main._filename_pattern(SPEC.report_code, SPEC.company_code)
    for src, n, first, last in rows:
        m = pattern.match(src.split("/")[-1])
        if m and m.group(2).endswith("235959"):
            day = jdatetime.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").date()
            out[day] = (n, str(first), str(last))
    return out


def api_count(day):
    start = jdatetime.datetime(day.year, day.month, day.day)
    end = start.replace(hour=23, minute=59, second=59)
    r = call_api(calls.URL, "POST", None, load_smart_panel_token("HK"), auth_mode="bearer",
                 json_body=calls.build_json_body(start, end))
    try:
        content = r.content
    finally:
        r.close()
    if content[:2] != b"PK":
        return None, f"not excel: {content[:120]!r}"
    return len(pd.read_excel(io.BytesIO(content), dtype=str)), ""


def server_error(day):
    """متن خطای سرور (صفحه‌ی دیباگ Django) برای روزی که 500 می‌دهد - علت در گزارش."""
    import html
    import re
    import requests
    start = jdatetime.datetime(day.year, day.month, day.day)
    body = calls.build_json_body(start, start.replace(hour=23, minute=59, second=59))
    try:
        r = requests.post(calls.URL, json=body, timeout=300,
                          headers={"Authorization": f"Bearer {load_smart_panel_token('HK')}"})
    except requests.RequestException as exc:
        return f"request failed: {exc}"
    text = html.unescape(r.text)
    value = re.search(r'exception_value">(.*?)<', text, re.S)
    where = re.findall(r'File "(/www/wwwroot/Backend/hamkadeh/(?!env/)[^"]+)", line (\d+), in (\w+)\s+(.+)', text)
    parts = [f"HTTP {r.status_code}"]
    if value:
        parts.append(value.group(1).strip())
    if where:
        f, line, func, code = where[-1]
        parts.append(f"{f.split('hamkadeh/')[-1]}:{line} {func}: {code.strip()}")
    return " | ".join(parts)


def download(conn, day, logger):
    start = jdatetime.datetime(day.year, day.month, day.day)
    end = start.replace(hour=23, minute=59, second=59)
    error = ""
    for attempt in range(1, MAX_TRIES + 1):
        wait_while_main_runs(logger)
        try:
            result = main._call_downloader(SPEC, start, end)
            main._retire_old_files_for_day(conn, SPEC, day, main._extract_save_path(result))
            main._load_result_into_sql(conn, SPEC, result)
            return result["rows"], attempt, ""
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("CALLS_HK | %s try %d/%d failed: %s", day, attempt, MAX_TRIES, error)
            if attempt < MAX_TRIES:
                time.sleep(RETRY_WAIT)
    return None, MAX_TRIES, error


def suspicious(day, info, medians):
    n, first, last = info
    reasons = []
    med = medians.get(day.weekday())
    if med and n < 0.4 * med:
        reasons.append(f"rows {n} < 40% of weekday median {med:.0f}")
    if last[11:16] < "20:00":
        reasons.append(f"last call {last[11:19]}")
    if first[11:16] > "09:00":
        reasons.append(f"first call {first[11:19]}")
    return reasons


def main_run(first_day, logger):
    yesterday = (now_jalali() - timedelta(days=1)).date()
    conn = get_connection(SQL_SERVER, SQL_DATABASE)
    ensure_tracking_table(conn)
    report = []
    try:
        have = sql_days(conn)
        days = []
        d = first_day
        while d <= yesterday:
            days.append(d)
            d += timedelta(days=1)

        # ۱) روزهای ناموجود
        for day in days:
            if day in have:
                continue
            rows, tries, error = download(conn, day, logger)
            if not rows:
                error = f"{error} || server: {server_error(day)}"
            report.append({"day": str(day), "issue": "missing", "tries": tries,
                           "result": "downloaded" if rows else "NO DATA", "rows": rows or 0, "detail": error})
            time.sleep(DELAY)

        # ۲) روزهای مشکوک
        have = sql_days(conn)
        by_weekday = {}
        for day, (n, _, _) in have.items():
            by_weekday.setdefault(day.weekday(), []).append(n)
        medians = {k: statistics.median(v) for k, v in by_weekday.items()}
        for day in days:
            if day not in have:
                continue
            reasons = suspicious(day, have[day], medians)
            if not reasons:
                continue
            old = have[day][0]
            counts = []
            for _ in range(2):
                n, err = api_count(day)
                counts.append(n if n is not None else err)
                time.sleep(DELAY)
            numeric = [c for c in counts if isinstance(c, int)]
            if numeric and max(numeric) > old:
                rows, tries, error = download(conn, day, logger)
                result = f"replaced {old} -> {rows}" if rows else f"re-download failed: {error}"
            else:
                rows, result = old, "API consistent (same rows on re-request) - likely real"
            report.append({"day": str(day), "issue": "; ".join(reasons), "tries": len(counts),
                           "result": result, "rows": rows, "detail": f"api counts {counts}, in db {old}"})

        final = sql_days(conn)
        for day in days:
            if day not in final and not any(r["day"] == str(day) for r in report):
                report.append({"day": str(day), "issue": "missing", "tries": 0, "result": "NO DATA",
                               "rows": 0, "detail": ""})
    finally:
        conn.close()

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, ["day", "issue", "tries", "result", "rows", "detail"])
        w.writeheader()
        w.writerows(sorted(report, key=lambda r: r["day"]))
    final_days = len(final)
    logger.info("CALLS_HK audit | days=%d in_db=%d issues=%d -> %s", len(days), final_days, len(report), OUT)
    for r in sorted(report, key=lambda r: r["day"]):
        print(r)


if __name__ == "__main__":
    configure_logging()
    first = jdatetime.datetime.strptime(sys.argv[1] if len(sys.argv) > 1 else "1405/01/01", "%Y/%m/%d").date()
    main_run(first, logging.getLogger("audit_calls"))
