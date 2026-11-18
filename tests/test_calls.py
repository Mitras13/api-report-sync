from unittest.mock import patch

import jdatetime
import pandas as pd
import pytest

import main
from downloaders import CALLS_HK as calls
from downloaders.downloader_core import InvalidContentError

DAY = jdatetime.datetime(1405, 7, 1)
END = DAY.replace(hour=23, minute=59, second=59)


def test_body_sends_seconds_so_last_minute_is_included():
    assert calls.build_json_body(DAY, END) == {"start": "2026-09-23 00:00:00", "end": "2026-09-23 23:59:59"}


def test_rejects_rows_outside_day():
    df = pd.DataFrame({"jcalldate": ["1405-07-01 10:00:00", "1405-07-02 10:00:00"]})
    with pytest.raises(InvalidContentError):
        calls.check_rows(df, DAY, END)


def test_empty_full_day_is_an_error_but_partial_today_is_not():
    empty = pd.DataFrame({"jcalldate": []})
    with pytest.raises(InvalidContentError):
        calls.check_rows(empty, DAY, END)
    calls.check_rows(empty, DAY, DAY.replace(minute=10))
    calls.check_rows(pd.DataFrame({"jcalldate": ["1405-07-01 23:59:59"]}), DAY, END)
    with pytest.raises(InvalidContentError):
        calls.check_rows(pd.DataFrame({"x": ["1"]}), DAY, END)


def test_spec_and_three_day_window():
    spec = next(s for s in main.DOWNLOADERS if s.label == "CALLS_HK")
    assert (spec.report_code, spec.company_code, spec.table) == ("CALLS", "HK", "CALLS_HK")
    assert main.WINDOW_DAYS["CALLS_HK"] == 3 and "CALLS_HK" in main.BACKFILLED_BACKWARD
    now = DAY.replace(hour=6)
    with patch.object(main, "latest_downloaded_period_end", return_value=None):
        start, end = main.resolve_spec_range(spec, DAY - jdatetime.timedelta(days=500), now)
    assert (start, end) == (DAY - jdatetime.timedelta(days=3), now)
