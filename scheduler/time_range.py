import jdatetime

DATETIME_FORMAT = "%Y/%m/%d %H:%M:%S"


def parse_jalali_datetime(date_str, time_str):
    try:
        return jdatetime.datetime.strptime(
            f"{date_str.strip()} {time_str.strip()}",
            DATETIME_FORMAT,
        )
    except ValueError as exc:
        raise ValueError(
            f"Invalid Jalali date/time: {date_str} {time_str}"
        ) from exc


def create_time_range(start_date, start_time, end_date, end_time):
    period_start = parse_jalali_datetime(start_date, start_time)
    period_end = parse_jalali_datetime(end_date, end_time)

    if period_start >= period_end:
        raise ValueError("Start datetime must be before end datetime.")

    return period_start, period_end
