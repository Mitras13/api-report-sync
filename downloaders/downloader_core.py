import csv
import json
import logging
import os
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd
import requests

from context import now_jalali


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_ROOT = PROJECT_ROOT / "raw_data"
LOG_ROOT = PROJECT_ROOT / "logs"

TOKEN_FILES = {
    "HK": PROJECT_ROOT / "tokens" / "tokenHK.txt",
    "54": PROJECT_ROOT / "tokens" / "token54.txt",
}

# Smart panel (5040-product.5040.me) endpoints use a separate token from the
# regular per-company TOKEN_FILES above - see downloaders/SPK_54.py.
SMART_PANEL_TOKEN_FILES = {
    "54": PROJECT_ROOT / "tokens" / "tokenSmartPanel54.txt",
}

logger = logging.getLogger(__name__)


class AuthExpiredError(Exception):
    """Authentication token is missing, empty, invalid, or expired."""


class InvalidContentError(Exception):
    """HTTP 2xx response does not contain valid CSV-like data."""


class ServerError(Exception):
    """HTTP/network/server failure that may be retried."""


def configure_logging():
    """Configure console + rotating file logging once."""
    LOG_ROOT.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if root_logger.handlers:
        return

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        LOG_ROOT / "robot_downloader.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console)
    root_logger.addHandler(file_handler)


def load_token(company_code: str) -> str:
    path = TOKEN_FILES.get(company_code)

    if path is None or not path.exists():
        raise AuthExpiredError(
            f"No token file found for company '{company_code}'"
        )

    token = path.read_text(encoding="utf-8").strip()

    if not token:
        raise AuthExpiredError(
            f"Token file for '{company_code}' is empty"
        )

    # A real token file must contain one value only. This also prevents
    # comments from accidentally being sent as an HTTP header/cookie.
    if "\n" in token or "\r" in token:
        raise AuthExpiredError(
            f"Token file for '{company_code}' contains multiple lines; "
            "store only the real token value."
        )

    return token


def load_smart_panel_token(company_code: str) -> str:
    path = SMART_PANEL_TOKEN_FILES.get(company_code)

    if path is None or not path.exists():
        raise AuthExpiredError(
            f"No smart panel token file found for company '{company_code}'"
        )

    token = path.read_text(encoding="utf-8").strip()

    if not token:
        raise AuthExpiredError(
            f"Smart panel token file for '{company_code}' is empty"
        )

    return token


def api_datetime_str(jdt) -> str:
    """Convert Jalali datetime to Gregorian API datetime string."""
    return jdt.togregorian().strftime("%Y-%m-%d %H:%M:%S")


def build_raw_filename(
    company_code, report_code, period_start, period_end, download_time
):
    return (
        f"{company_code}_{report_code}_"
        f"{period_start.strftime('%Y%m%d%H%M%S')}_"
        f"{period_end.strftime('%Y%m%d%H%M%S')}_"
        f"{download_time.strftime('%Y%m%d%H%M%S')}.parquet"
    )


def build_raw_path(company_code, report_code, filename):
    folder = RAW_DATA_ROOT / report_code / company_code
    folder.mkdir(parents=True, exist_ok=True)
    return folder / filename


def _response_looks_like_invalid_content(sample: str) -> bool:
    stripped = sample.lstrip()
    upper = stripped.upper()

    if not stripped:
        return True

    if upper.startswith("<!DOCTYPE HTML") or upper.startswith("<HTML"):
        return True

    if upper.startswith("WELCOME"):
        return True

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, (dict, list)):
            return True
    except json.JSONDecodeError:
        pass

    return False


def _validate_csv_sample(sample: str) -> None:
    """Validate that a non-empty response can be parsed as CSV."""
    if not sample.strip():
        raise InvalidContentError("Response body is empty.")

    if _response_looks_like_invalid_content(sample):
        raise InvalidContentError(
            f"Response is not valid CSV content: {sample[:200]!r}"
        )

    try:
        rows = list(csv.reader(sample.splitlines()))
    except csv.Error as exc:
        raise InvalidContentError(
            f"Response is not valid CSV: {exc}"
        ) from exc

    if not rows or not any(any(cell.strip() for cell in row) for row in rows):
        raise InvalidContentError("Response does not contain CSV rows.")


def _validate_content_type(response) -> None:
    content_type = (response.headers.get("Content-Type") or "").lower()

    if "application/json" in content_type or "+json" in content_type:
        raise InvalidContentError(
            f"API returned JSON instead of CSV (Content-Type: {content_type})"
        )

    if "text/html" in content_type or "application/xhtml" in content_type:
        raise InvalidContentError(
            f"API returned HTML instead of CSV (Content-Type: {content_type})"
        )


def call_api(
    url,
    method,
    params,
    token,
    auth_mode="cookie",
    json_body=None,
    timeout=(15, 300),
):
    """Call API using cookie or bearer authentication.

    auth_mode must be verified against the real Hamkadeh API documentation
    before production use. Supported values: "cookie" and "bearer".
    """
    if auth_mode == "bearer":
        cookies = None
        headers = {"Authorization": f"Bearer {token}"}
    elif auth_mode == "cookie":
        cookies = {"token": token}
        headers = None
    else:
        raise ValueError(
            f"Unsupported auth_mode: {auth_mode!r}. "
            "Use 'cookie' or 'bearer'."
        )

    try:
        response = requests.request(
            method,
            url,
            params=params,
            cookies=cookies,
            headers=headers,
            json=json_body,
            timeout=timeout,
            stream=True,
        )
    except requests.exceptions.RequestException as exc:
        raise ServerError(f"HTTP request failed: {exc}") from exc

    if response.status_code in (401, 403):
        response.close()
        raise AuthExpiredError(
            f"Authentication failed (HTTP {response.status_code})"
        )

    if not 200 <= response.status_code < 300:
        response.close()
        raise ServerError(f"API returned HTTP {response.status_code}")

    return response


def _coerce_mixed_type_object_columns(df):
    """
    Some Excel/CSV sources mix types within one column (e.g. a "name"
    column with a stray numeric cell), which pandas stores as dtype
    object but PyArrow refuses to convert to Parquet. Any object column
    with more than one Python type among its non-null values is coerced
    to string (nulls are preserved as-is) so saving never fails on this.
    """
    for column in df.columns[df.dtypes == object]:
        non_null = df[column].dropna()
        if non_null.empty:
            continue
        if non_null.map(type).nunique() > 1:
            df[column] = df[column].map(lambda v: v if pd.isna(v) else str(v))

    return df


def save_dataframe_as_parquet(df, save_path):
    """
    Save a DataFrame as a Parquet file at save_path.

    Parent directories are created automatically. Writes to a temporary
    ".part" file first and atomically renames it, so a crash mid-write can
    never leave a corrupt/partial Parquet file at the final path.
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = save_path.with_suffix(save_path.suffix + ".part")

    df = _coerce_mixed_type_object_columns(df)

    try:
        df.to_parquet(temp_path, index=False)
        temp_path.replace(save_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    logger.info("Saved Parquet: %s (%d rows)", save_path, len(df))

    return save_path


def stream_response_to_dataframe(response, encoding="utf-8-sig"):
    """
    Validate that an API response is well-formed CSV, stream it to a
    temporary file (so we never hold the whole payload in memory at once),
    parse it into a DataFrame, then delete the temporary file.

    Only the parsed DataFrame is returned. If you also want a permanent
    copy of the data on disk (in raw_data/), save the returned DataFrame
    yourself via `save_dataframe_as_parquet`.

    Always closes the response, even on failure.
    """
    total_bytes = 0
    first_chunk = True
    temp_path = None

    try:
        _validate_content_type(response)

        fd, temp_name = tempfile.mkstemp(suffix=".csv")
        temp_path = Path(temp_name)

        with os.fdopen(fd, "wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue

                if first_chunk:
                    sample = chunk[:4096].decode("utf-8", errors="replace")
                    _validate_csv_sample(sample)
                    first_chunk = False

                output.write(chunk)
                total_bytes += len(chunk)

        if total_bytes == 0:
            raise InvalidContentError("Downloaded file is empty.")

        with temp_path.open("rb") as check:
            magic_bytes = check.read(8)

        # برخی اندپوینت‌ها به‌جای CSV واقعی، فایل اکسل (xlsx/xls) برمی‌گردانند
        # (با اینکه export_data=1 فرستاده شده)؛ این حالت را از روی magic
        # bytes تشخیص می‌دهیم تا به‌جای شکست در پارس CSV، با pd.read_excel
        # خوانده شود.
        is_xlsx = magic_bytes.startswith(b"PK\x03\x04")
        is_xls = magic_bytes.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")

        if is_xlsx or is_xls:
            df = pd.read_excel(temp_path)
            return df

        with temp_path.open("rb") as check:
            sample = check.read(4096).decode("utf-8", errors="replace")
            _validate_csv_sample(sample)

        # برخی اندپوینت‌ها CSV را با انکودینگ فارسی/عربی (نه UTF-8) یا با
        # جداکننده‌ای غیر از کاما برمی‌گردانند؛ در صورت شکست حالت پیش‌فرض،
        # این ترکیب‌ها را هم امتحان می‌کنیم.
        encodings_to_try = [encoding, "windows-1256", "windows-1252"]
        last_exc = None

        for candidate_encoding in encodings_to_try:
            try:
                df = pd.read_csv(temp_path, encoding=candidate_encoding)
                return df
            except UnicodeDecodeError as exc:
                last_exc = exc
                continue
            except pd.errors.ParserError as exc:
                last_exc = exc
                try:
                    df = pd.read_csv(
                        temp_path,
                        encoding=candidate_encoding,
                        sep=None,
                        engine="python",
                    )
                    return df
                except (UnicodeDecodeError, pd.errors.ParserError) as inner_exc:
                    last_exc = inner_exc
                    continue

        raise last_exc

    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
        response.close()


def save_response_to_csv(response, save_path):
    """Validate and stream an API response to CSV via a temporary file.

    NOTE: kept for reference / backward compatibility. Active downloaders
    now use `stream_response_to_dataframe` + `save_dataframe_as_parquet`
    instead, so raw_data/ contains Parquet files rather than raw CSV.
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = save_path.with_suffix(save_path.suffix + ".part")

    total_bytes = 0
    first_chunk = True

    try:
        _validate_content_type(response)

        with temp_path.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue

                if first_chunk:
                    sample = chunk[:4096].decode("utf-8", errors="replace")
                    _validate_csv_sample(sample)
                    first_chunk = False

                output.write(chunk)
                total_bytes += len(chunk)

        if total_bytes == 0:
            raise InvalidContentError("Downloaded file is empty.")

        with temp_path.open("rb") as check:
            sample = check.read(4096).decode("utf-8", errors="replace")
            _validate_csv_sample(sample)

        if temp_path.stat().st_size == 0:
            raise InvalidContentError("Downloaded CSV file has zero size.")

        temp_path.replace(save_path)
        logger.info("Saved CSV: %s (%d bytes)", save_path, total_bytes)
        return save_path

    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        if save_path.exists() and save_path.stat().st_size == 0:
            save_path.unlink()
        raise

    finally:
        response.close()


def smart_panel_json_to_dataframe(payload: dict) -> pd.DataFrame:
    """
    Smart panel endpoints (5040-product.5040.me) wrap their table in
    {"data": [...], "column": [...], "status": ..., "message": ...} instead
    of returning CSV directly. An empty "data" is only a legitimate
    "no activity" result when status is exactly True; otherwise it's a real
    failure response and must not silently become a header-only DataFrame.
    """
    data = payload.get("data", [])
    columns = payload.get("column")

    if not data:
        if payload.get("status") is not True:
            raise InvalidContentError(
                "Smart panel response has empty data but status is not true "
                f"(status={payload.get('status')!r}, message={payload.get('message')!r})"
            )
        return pd.DataFrame(columns=columns or [])

    df = pd.DataFrame(data)
    if columns:
        df = df[columns]
    return df


def fetch_smart_panel_json(
    url, company_code, report_code, period_start, period_end, build_json_body
):
    """
    Smart panel equivalent of fetch_generic: synchronous POST, auth via
    load_smart_panel_token/auth_mode="bearer" (a token separate from the
    regular per-company TOKEN_FILES). Saved as Parquet like every other
    downloader in this project (not CSV, unlike the Robot_Reward project
    this logic was ported from).

    build_json_body(period_start, period_end) must return the full POST
    body dict (including any fixed output-generator id).
    """
    token = load_smart_panel_token(company_code)
    json_body = build_json_body(period_start, period_end)

    response = call_api(
        url=url,
        method="POST",
        params=None,
        token=token,
        auth_mode="bearer",
        json_body=json_body,
        timeout=(15, 300),
    )

    try:
        payload = response.json()
    finally:
        response.close()

    df = smart_panel_json_to_dataframe(payload)

    download_time = now_jalali()
    filename = build_raw_filename(
        company_code, report_code, period_start, period_end, download_time
    )
    save_path = build_raw_path(company_code, report_code, filename)

    save_dataframe_as_parquet(df, save_path)

    return {"path": str(save_path), "rows": len(df)}


def fetch_generic(
    url,
    method,
    company_code,
    report_code,
    period_start,
    period_end,
    build_params,
    auth_mode="cookie",
    json_body=None,
    build_json_body=None,
):
    """Call the API and return the raw (streaming) response.

    NOTE: This function no longer saves the response to disk. The caller
    (Downloader) is responsible for:
      1. Recording `download_time` right after this call returns.
      2. Building the filename/save_path via `build_raw_filename` /
         `build_raw_path`.
      3. Calling `save_response_to_csv(response, save_path)`.
      4. Ensuring the response is closed even if an exception occurs
         between receiving it and calling `save_response_to_csv`
         (e.g. via `try/finally` or `contextlib.closing`), since
         `call_api` returns an open stream (`stream=True`).
    """
    token = load_token(company_code)
    params = build_params(period_start, period_end)

    if build_json_body is not None:
        json_body = build_json_body(period_start, period_end)

    response = call_api(
        url=url,
        method=method,
        params=params,
        token=token,
        auth_mode=auth_mode,
        json_body=json_body,
    )

    return response
