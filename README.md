# Robot Downloader

A Python-based downloader for Hamkadeh API reports using a user-defined Jalali date/time range.

## 1. Token setup

A safe template is provided:

```text
tokens/tokenHK.txt.example
```

Before running the project:

```bash
cp tokens/tokenHK.txt.example tokens/tokenHK.txt
```

Then open `tokens/tokenHK.txt` and replace its contents with **only your real token**.

Do not put comments, quotes, spaces, or multiple lines around the token.

Never commit the real token. `.gitignore` excludes:

```text
tokens/*.txt
!tokens/*.txt.example
```

If a real token has accidentally been exposed, revoke/rotate it at the provider and create a new local token file.

## 2. Authentication mode

Each downloader explicitly defines its own authentication mode.

`downloaders/FCR_HK.py`:

```python
AUTH_MODE = "cookie"
```

Supported values:

```text
cookie
bearer
```

This choice must be verified against the actual Hamkadeh API documentation/API behavior before production use.

- `cookie`: sends the token as cookie `token`
- `bearer`: sends `Authorization: Bearer <token>`

## 3. Date/time

The scheduler accepts Jalali date + time:

```text
1405/05/01 00:00:00
1405/05/10 23:59:59
```

The downloader converts these Jalali datetimes to Gregorian before sending API parameters.

## 4. HTTP and response validation

The downloader checks, in order:

```text
API response
   ↓
HTTP status
   ↓
Authentication (401 / 403)
   ↓
Content-Type
   ↓
Empty response
   ↓
JSON error detection
   ↓
HTML error detection
   ↓
CSV parsing sanity check
   ↓
Temporary .part file
   ↓
Non-zero file size
   ↓
Final CSV
```

Error responses are never finalized as CSV.

### Authentication errors

- `401` → `AuthExpiredError`, no retry
- `403` → `AuthExpiredError`, no retry

### Server/network errors

- `500` and other non-2xx responses → `ServerError`
- network exceptions / timeout → `ServerError`
- these are retryable according to the current retry policy

### Invalid successful responses

A `2xx` response is still rejected if it is:

- empty
- JSON error
- HTML error
- otherwise not parseable as CSV-like content

Invalid downloads are written only to a temporary `.part` file and that file is removed on failure.

## 5. Retry policy

Current downloader configuration:

```text
maximum attempts: 3
base delay: 2 seconds
```

Backoff:

```text
Attempt 1 fails → wait 2 seconds
Attempt 2 fails → wait 4 seconds
Attempt 3 fails → raise final error
```

Authentication failures (`401` / `403`, missing/invalid token) do not retry.

## 6. Logging

Logs are written to both:

```text
console
logs/robot_downloader.log
```

The log file uses `RotatingFileHandler`:

```text
maxBytes = 5 * 1024 * 1024
backupCount = 5
```

This prevents the log file from growing without limit.

## 7. Tests

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run all tests:

```bash
pytest -q
```

The test suite covers:

1. `test_401_auth_error`
2. `test_timeout_retry`
3. `test_http_500`
4. `test_empty_response`
5. `test_json_error_response`
6. `test_html_error_response`
7. `test_valid_csv_response`
8. `test_no_csv_created_on_error`
9. `test_retry_count`
10. `test_exponential_backoff`

Additional regression checks cover:

- Jalali datetime parsing
- invalid Jalali input
- `start >= end`
- Jalali → Gregorian API parameter conversion
- token template safety
- rotating logging configuration

All tests use mocks and do not require the real Hamkadeh API.

## 8. Run

Activate the virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run:

```bash
python main.py
```

## 9. Project structure

```text
Robot_Downloader_fixed_v2/
├── main.py
├── context.py
├── requirements.txt
├── README.md
├── .gitignore
├── scheduler/
│   ├── __init__.py
│   └── time_range.py
├── downloaders/
│   ├── __init__.py
│   ├── FCR_HK.py
│   ├── downloader_common.py
│   └── downloader_core.py
├── tokens/
│   └── tokenHK.txt.example
└── tests/
    ├── __init__.py
    ├── test_error_handling.py
    └── test_tokens_and_logging.py
```


## Daily historical download

`main.py` now downloads the configured reports one Jalali calendar day at a time.

The default start point is:

```text
1404/01/01 00:00:00
```

The end point is the current Jalali date/time at the moment the program starts.

For every completed day, the requested range is:

```text
00:00:00 -> 23:59:59
```

The loop automatically crosses Jalali month/year boundaries. For the current day, the end time is capped at the actual current time so the program does not request future data.

The current project contains these downloaders:

- FC_HK
- FC_54
- VP_HK
- VP_54
- SCL_HK

If one report fails for a particular day, the error is logged and the robot continues with the next report/day rather than stopping the entire historical run.

Run:

```bash
python main.py
```

Run the tests:

```bash
pytest -q
```

## Token management

The downloader expects real tokens at:

```text
tokens/tokenHK.txt
tokens/token54.txt
```

The repository contains only `*.txt.example` files. Never commit the real
token files.

To create/refresh a token interactively:

```bash
python refresh_token.py HK
python refresh_token.py 54
```

The SMS OTP is entered manually. The script saves the returned token directly
to `tokens/tokenHK.txt` or `tokens/token54.txt`, which is the exact location
used by `downloaders/downloader_core.py`.

Check token health without downloading a report:

```bash
python token_health.py
python token_health.py HK
python token_health.py 54
```

## Downloaded data location

All downloaded report Parquet files are stored under:

```text
raw_data/<REPORT_CODE>/<COMPANY_CODE>/
```

For example:

```text
raw_data/FCR/HK/
raw_data/FCR/54/
raw_data/SCL/HK/
```

The directory is created automatically before a file is written. Each Parquet
filename contains the company, report, requested Jalali start/end timestamps,
and download timestamp.

The daily historical loop starts at `1404/01/01 00:00:00` and continues to
the current Jalali date/time, one calendar day at a time. The current day's
end is capped at the actual current time.


## Storage

This version is **Parquet-only**.

For each successful daily download, the DataFrame is saved as one Parquet file:

```text
raw_data/<REPORT_CODE>/<COMPANY_CODE>/<filename>.parquet
```

No SQL Server, SQLite, database table, or database download log is used.
The `database/` package and SQL-writing code have been removed.

Example:

```text
raw_data/
└── INV_SAL/
    ├── HK/
    │   └── HK_INV_SAL_14050401000000_14050401235959_14050823170000.parquet
    └── 54/
        └── 54_INV_SAL_14050401000000_14050401235959_14050823170000.parquet
```

The existing daily delay in `main.py` is still applied between downloader calls.
