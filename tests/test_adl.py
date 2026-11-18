from unittest.mock import patch
import pytest
import jdatetime
from downloaders import ADL_HK as adl
import main

START = jdatetime.datetime.fromgregorian(year=2026, month=11, day=3)
END = START.replace(hour=23, minute=59, second=59)


def test_pagination_and_nested_fields(tmp_path):
    pages = [([{"id": 1, "created_at": "2026-11-03T12:00:00Z", "campaign": {"name": "test"}}],
              {"total": 2, "last_page": 2}),
             ([{"id": 2, "created_at": "2026-11-03T13:00:00Z"}], {"total": 2, "last_page": 2})]
    with patch.object(adl, "read_page", side_effect=pages), patch.object(adl.time, "sleep"), \
         patch.object(adl, "build_raw_path", return_value=tmp_path / "data.parquet"), \
         patch.object(adl, "save_dataframe_as_parquet") as save:
        result = adl.fetch(None, START, END)
    assert result["rows"] == 2
    assert save.call_args.args[0].iloc[0]["campaign"] == '{"name": "test"}'


@pytest.mark.parametrize("rows,total", [([], 1), ([{"id": 1, "created_at": "2026-11-04T12:00:00Z"}], 1)])
def test_reject_incomplete_or_unfiltered(rows, total):
    with patch.object(adl, "read_page", return_value=(rows, {"total": total, "last_page": 1})), \
         pytest.raises(adl.InvalidContentError):
        adl.fetch(None, START, END)


def test_exact_ten_completed_days():
    spec = next(s for s in main.DOWNLOADERS if s.label == "ADL_HK")
    now = END + jdatetime.timedelta(days=1)
    with patch.object(main, "latest_downloaded_period_end", return_value=None):
        start, end = main.resolve_spec_range(spec, START - jdatetime.timedelta(days=100), now)
    assert end == END
    assert (end.date() - start.date()).days == 9


def test_empty_day_saved(tmp_path):
    with patch.object(adl, "read_page", return_value=([], {"total": 0, "last_page": 1})), \
         patch.object(adl, "build_raw_path", return_value=tmp_path / "empty.parquet"), \
         patch.object(adl, "save_dataframe_as_parquet") as save:
        assert adl.fetch(None, START, END)["rows"] == 0
    assert list(save.call_args.args[0].columns) == ["id"]
