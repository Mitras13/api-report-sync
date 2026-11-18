"""هسته‌ی درخواست/احراز هویت پزشکت (PT) - منتقل‌شده از D:\\Smart_telegram_bot\\API_Downloader\\PT و منطبق با
مشخصات فنی کاربر (۲۰۲۶-۱۱-۱۶). گزارش‌های ربات تلگرام (Report_Builders/_pt_forosh_calc.py) به ستون‌ها و قالب
مقدارهای WTX/DCU وابسته‌اند؛ هر تغییری در خروجی باید با آن مشخصات بخواند.

احراز هویت: OAuth2 password grant. username/password/client_id هرگز در کد نیستند:
  ۱. متغیر محیطی PT_USERNAME / PT_PASSWORD / PT_CLIENT_ID (اولویت دارد)
  ۲. tokens/credentialsPT.txt = {"username": ..., "password": ..., "client_id": ...}  (gitignored)
توکن: tokens/tokenPT.txt (اتمیک نوشته می‌شود). با 401/403 فقط یک بار لاگین دوباره و یک بار تکرار درخواست؛
چند thread هم‌زمان فقط یک لاگین انجام می‌دهند.

ثبت یک‌باره (کاربر، چون رمز تایپ می‌شود):  python -m downloaders.pezeshket_core
"""
import datetime
import getpass
import json
import logging
import os
import threading
import time
from zoneinfo import ZoneInfo

import requests

from .downloader_core import AuthExpiredError as _CoreAuthExpiredError, PROJECT_ROOT

logger = logging.getLogger(__name__)

TOKEN_FILE = PROJECT_ROOT / "tokens" / "tokenPT.txt"
CREDENTIALS_FILE = PROJECT_ROOT / "tokens" / "credentialsPT.txt"

OAUTH_URL = "https://api.pezeshket.com/adminCore/v1/oauth/token"
USER_BULK_INFO_URL = "https://api.pezeshket.com/core/v1/users/bulkInfo"
TIMEOUT = 60
TEHRAN = ZoneInfo("Asia/Tehran")

RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 30

# کد ملی، شماره همراه و آواتار در گزارش‌ها استفاده نمی‌شوند و داده‌ی شخصی‌اند: ستون‌ها می‌مانند (شکل خروجی
# عوض نمی‌شود) ولی مقدارشان خالی ذخیره می‌شود. برای ذخیره‌ی واقعی: PT_STORE_PERSONAL_DATA=1
STORE_PERSONAL_DATA = os.environ.get("PT_STORE_PERSONAL_DATA", "").strip() in ("1", "true", "yes")


# ---------------------------------------------------------------- خطاها
class AuthExpiredError(_CoreAuthExpiredError):
    """احراز هویت ناموفق (حتی بعد از یک لاگین دوباره) - نباید تکرار شود."""


class ServerError(Exception):
    """پایه‌ی خطاهای غیر احراز هویت (قابل تکرار)."""


class ServerHTTPError(ServerError):
    """پاسخ با وضعیت غیر 200 (معمولاً 5xx)."""


class InvalidResponseError(ServerError):
    """JSON نامعتبر یا فایل غیر xlsx (مثلاً صفحه‌ی خطای HTML)."""


class ConnectionFailedError(ServerError):
    """قطع اتصال / timeout."""


class LoginError(Exception):
    """خودِ درخواست لاگین شکست خورد."""


# ---------------------------------------------------------------- تنظیمات و لاگین
def _load_credentials():
    data = {}
    try:
        loaded = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        pass
    creds = {
        "username": os.environ.get("PT_USERNAME") or data.get("username"),
        "password": os.environ.get("PT_PASSWORD") or data.get("password"),
        "client_id": os.environ.get("PT_CLIENT_ID") or data.get("client_id"),
    }
    return creds if all(creds.values()) else None


def login_with_credentials(username, password, client_id):
    try:
        response = requests.post(
            OAUTH_URL,
            data={"grant_type": "password", "client_id": client_id,
                  "username": username, "password": password},
            timeout=TIMEOUT,
        )
    except requests.exceptions.RequestException as e:
        raise LoginError(f"Connection failed: {e}")
    if response.status_code != 200:
        raise LoginError(f"Login request failed: HTTP {response.status_code}")
    try:
        token = response.json().get("access_token")
    except (ValueError, AttributeError):
        raise LoginError("Login response was not valid JSON")
    if not token:
        raise LoginError("Login response has no access_token")
    return token


def _read_token_file_raw():
    if not TOKEN_FILE.exists():
        return None
    return TOKEN_FILE.read_text(encoding="utf-8").strip() or None


def _atomic_write_token(token):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_name(f"{TOKEN_FILE.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(token, encoding="utf-8")
    os.replace(tmp, TOKEN_FILE)


_relogin_lock = threading.Lock()


def _auto_relogin(stale_token=None):
    with _relogin_lock:
        current = _read_token_file_raw()
        # thread دیگری در همین موج انقضا قبلاً لاگین کرده: همان توکن تازه.
        if current is not None and current != stale_token:
            return current
        creds = _load_credentials()
        if creds is None:
            raise AuthExpiredError(
                f"PT credentials missing (env PT_USERNAME/PT_PASSWORD/PT_CLIENT_ID or {CREDENTIALS_FILE}) - "
                "run: python -m downloaders.pezeshket_core"
            )
        try:
            token = login_with_credentials(creds["username"], creds["password"], creds["client_id"])
        except LoginError as e:
            raise AuthExpiredError(f"PT login failed: {e}")
        _atomic_write_token(token)
        return token


def load_token():
    return _read_token_file_raw() or _auto_relogin()


# ---------------------------------------------------------------- درخواست‌ها
def _request(method, url, **kwargs):
    def send(token):
        try:
            return requests.request(method, url, headers={"Authorization": f"Bearer {token}"},
                                    timeout=TIMEOUT, **kwargs)
        except requests.exceptions.RequestException as e:
            raise ConnectionFailedError(f"Connection failed: {e}")

    token = load_token()
    response = send(token)
    if response.status_code in (401, 403):
        response = send(_auto_relogin(stale_token=token))
    if response.status_code in (401, 403):
        raise AuthExpiredError(f"Auth failed (HTTP {response.status_code}) even after re-login")
    if response.status_code != 200:
        raise ServerHTTPError(f"Server error (HTTP {response.status_code})")
    return response


def _json(response):
    try:
        return response.json()
    except ValueError:
        raise InvalidResponseError("Response was not valid JSON")


def call_api(url, params):
    return _json(_request("GET", url, params=params))


def call_api_post(url, json_body):
    return _json(_request("POST", url, json=json_body))


def fetch_excel(url, params):
    content = _request("GET", url, params=params).content
    if not content.startswith(b"PK"):
        raise InvalidResponseError("Response is not an .xlsx file (no PK signature) - probably an HTML error page")
    return content


def fetch_paginated(url, build_params, data_key, pages_key="pages", limit=100):
    """offset از 0، هر بار +limit، تا offset < pages*limit (pages از پاسخ اول)؛ صفحه‌ی خالی = توقف."""
    rows, offset, total_pages = [], 0, None
    while total_pages is None or offset < total_pages * limit:
        payload = call_api(url, build_params(offset, limit))
        if not isinstance(payload, dict) or not isinstance(payload.get(data_key, []), list):
            raise InvalidResponseError(f"Unexpected payload shape (no list '{data_key}')")
        page_rows = payload.get(data_key, [])
        rows.extend(page_rows)
        if total_pages is None:
            total_pages = payload.get(pages_key, 1)
            if type(total_pages) is not int:
                raise InvalidResponseError(f"Unexpected '{pages_key}': {total_pages!r}")
        if not page_rows:
            break
        offset += limit
    return rows


EMPTY_BULK_INFO = {
    "userId": None, "nickname": None, "userType": None, "nationalCode": None,
    "avatarColor": None, "avatarInitials": None, "avatarUrl": None, "avatarThumbnail": None,
}


def bulk_user_info(user_ids, chunk_size=100):
    """POST core/v1/users/bulkInfo {"ids": [...]} در دسته‌های ۱۰۰تایی -> {userId: فیلدهای EMPTY_BULK_INFO}."""
    unique_ids = list(dict.fromkeys(i for i in user_ids if i))
    info_by_id = {}
    for i in range(0, len(unique_ids), chunk_size):
        payload = call_api_post(USER_BULK_INFO_URL, {"ids": unique_ids[i:i + chunk_size]})
        for entry in (payload.get("users") or []) if isinstance(payload, dict) else []:
            user = entry.get("user") or {}
            user_id = user.get("userId")
            if not user_id:
                continue
            avatar = user.get("avatar") or {}
            info_by_id[user_id] = {
                "userId": user_id,
                "nickname": user.get("nickname"),
                "userType": entry.get("userType"),
                "nationalCode": entry.get("nationalCode"),
                "avatarColor": avatar.get("color"),
                "avatarInitials": avatar.get("initials"),
                "avatarUrl": avatar.get("avatar"),
                "avatarThumbnail": avatar.get("thumbnail"),
            }
    return info_by_id


# ---------------------------------------------------------------- زمان و تکرار
def api_unix_timestamp(jdt):
    """زمان جلالی به وقت تهران -> unix seconds (عدد صحیح)، مستقل از ساعت سیستم."""
    return int(jdt.togregorian().replace(tzinfo=TEHRAN).timestamp())


def tehran_from_ms(ms_epoch):
    """میلی‌ثانیه -> datetime میلادی بدون tz به وقت تهران."""
    return datetime.datetime.fromtimestamp(ms_epoch / 1000, TEHRAN).replace(tzinfo=None)


def with_retry(func, label):
    """۳ تلاش با فاصله‌ی ثابت ۳۰ ثانیه؛ خطای احراز هویت هرگز تکرار نمی‌شود."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return func()
        except AuthExpiredError:
            logger.error("%s: authentication failure; not retried", label, exc_info=True)
            raise
        except Exception as exc:
            logger.warning("%s: attempt %d/%d failed (%s): %s", label, attempt, RETRY_ATTEMPTS,
                           type(exc).__name__, exc)
            if attempt == RETRY_ATTEMPTS:
                raise
            time.sleep(RETRY_DELAY_SECONDS)


def sanitize_value(value):
    """surrogate تنها (در avatarInitials دیده شده) کل دانلود را خراب نکند."""
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    return value


# ---------------------------------------------------------------- خروجی CSV مطابق مشخصات
CSV_ROOT = PROJECT_ROOT / "raw_data_csv"


def save_spec_csv(df, report_code, period_start, period_end, download_time):
    """PT_{REPORT}_{yyyyMMddHHmm}_{yyyyMMddHHmm}_{yyyyMMddHHmmss}.csv، utf-8-sig، بدون index (تاریخ‌ها جلالی).
    روز بدون ردیف هم فایل با سطر عنوان دارد."""
    folder = CSV_ROOT / report_code / "PT"
    folder.mkdir(parents=True, exist_ok=True)
    name = (f"PT_{report_code}_{period_start.strftime('%Y%m%d%H%M')}_{period_end.strftime('%Y%m%d%H%M')}_"
            f"{download_time.strftime('%Y%m%d%H%M%S')}.csv")
    path = folder / name
    tmp = path.with_suffix(".csv.part")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)
    # فقط جدیدترین نسخه‌ی هر روز معتبر است.
    day_prefix = f"PT_{report_code}_{period_start.strftime('%Y%m%d')}"
    for old in folder.glob(f"{day_prefix}*.csv"):
        if old != path:
            old.unlink()
    return path


def setup_credentials():
    """ثبت یک‌باره‌ی username/password/client_id و تست فوری لاگین."""
    username = input("PT username: ").strip()
    password = getpass.getpass("PT password: ").strip()
    client_id = input("PT client_id: ").strip()
    if not (username and password and client_id):
        print("username/password/client_id cannot be empty - nothing written.")
        return
    try:
        token = login_with_credentials(username, password, client_id)
    except LoginError as e:
        print(f"Login FAILED, nothing written: {e}")
        return
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps({"username": username, "password": password, "client_id": client_id}),
                                encoding="utf-8")
    _atomic_write_token(token)
    print(f"Login OK. Saved {CREDENTIALS_FILE} and {TOKEN_FILE}")


if __name__ == "__main__":
    setup_credentials()
