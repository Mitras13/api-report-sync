"""گزارش تبلیغات پنل هوشمند 5040 - منطق و ستون‌ها در smart_panel_ads.py."""
from .smart_panel_ads import REPORT_CODE, fetch_ads  # noqa: F401  (REPORT_CODE: same convention as other downloaders)

# Captured from the real panel request (2026-11-02).
URL = "https://5040-product.5040.me/api/report/smart/calculate-ads/484"
LEADERS_URL = "https://5040-product.5040.me/api/user/LeaderAds/"
COMPANY_CODE = "54"
OUTPUT_GENERATOR_ID = "484"
TOTAL_ROW_NAME = "مجموع/میانگین"


def fetch(context, period_start, period_end):
    """Standard contract every downloader implements."""
    return fetch_ads(
        COMPANY_CODE, URL, LEADERS_URL, OUTPUT_GENERATOR_ID, TOTAL_ROW_NAME,
        period_start, period_end,
    )
