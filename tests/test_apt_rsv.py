from unittest.mock import patch

import jdatetime
import pandas as pd
import pytest

import main
from downloaders import APT_RSV_HK as rsv
from downloaders.downloader_core import InvalidContentError

DAY = jdatetime.datetime(1405, 7, 1)
END = DAY.replace(hour=23, minute=59, second=59)


def test_params_use_appointment_date():
    p = rsv.build_params(DAY, END)
    assert p == {"export_data": "1", "start_reserved_at": "2026-09-23 00:00", "end_reserved_at": "2026-09-23 23:59"}


def test_rejects_rows_outside_day():
    df = pd.DataFrame({"تاریخ نوبت": ["1405-07-01 10:00:00", "1405-07-02 10:00:00"]})
    with pytest.raises(InvalidContentError):
        rsv.check_filtered(df, DAY, END)


def test_accepts_day_and_empty_day():
    rsv.check_filtered(pd.DataFrame({"تاریخ نوبت": ["1405-07-01 23:00:00"]}), DAY, END)
    rsv.check_filtered(pd.DataFrame({"تاریخ نوبت": []}), DAY, END)
    with pytest.raises(InvalidContentError):
        rsv.check_filtered(pd.DataFrame({"x": []}), DAY, END)


def test_spec_loads_into_apt_lst_table_from_own_folder():
    spec = next(s for s in main.DOWNLOADERS if s.label == "APT_RSV_HK")
    assert (spec.report_code, spec.company_code, spec.table) == ("NobatDate", "HK", "APT_LST_HK")
    old = next(s for s in main.DOWNLOADERS if s.label == "APT_LST_HK")
    assert old.table == "APT_LST_HK" and old.report_code == "Nobat"


@pytest.mark.parametrize("latest", [None, END - jdatetime.timedelta(days=1)])
def test_last_ten_completed_days_redownloaded(latest):
    """کاربر ۱۴۰۵/۰۸/۱۷: هر شب ۱۰ روز آخر تا دیروز (وضعیت نوبت تا چند روز بعد عوض می‌شود)."""
    spec = next(s for s in main.DOWNLOADERS if s.label == "APT_RSV_HK")
    now = END + jdatetime.timedelta(hours=6)  # 1405/07/02 06:00
    with patch.object(main, "latest_downloaded_period_end", return_value=latest):
        start, end = main.resolve_spec_range(spec, DAY - jdatetime.timedelta(days=200), now)
    assert (start, end) == (DAY - jdatetime.timedelta(days=9), END)


def test_bulk_loader_maps_folder_to_table():
    import load_raw_data_to_sql as loader
    assert loader.TABLE_FOR_FOLDER["NobatDate_HK"] == "APT_LST_HK"
