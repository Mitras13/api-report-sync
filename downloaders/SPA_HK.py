"""گزارش تبلیغات پنل هوشمند همکده - منطق و ستون‌ها در smart_panel_ads.py."""
from .smart_panel_ads import REPORT_CODE, fetch_ads  # noqa: F401  (REPORT_CODE: same convention as other downloaders)

# Captured from the real panel request (2026-11-02). Different host from 54
# (5040.5040.me, not 5040-product) and a different panel user/token
# (tokens/tokenSmartPanelHK.txt).
URL = "https://5040.5040.me/api/report/smart/calculate-ads/537"
LEADERS_URL = "https://5040.5040.me/api/user/LeaderAds/"
COMPANY_CODE = "HK"
OUTPUT_GENERATOR_ID = "537"
# HK has no "مجموع/میانگین" row; its first row "همکده" is the total.
TOTAL_ROW_NAME = "همکده"


def fetch(context, period_start, period_end):
    """Standard contract every downloader implements."""
    return fetch_ads(
        COMPANY_CODE, URL, LEADERS_URL, OUTPUT_GENERATOR_ID, TOTAL_ROW_NAME,
        period_start, period_end,
    )
