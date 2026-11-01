"""پارس پیام‌های گروه «اعلام هزینه تبلیغات 1405» (ad_cost/telegram_parser.py)؛ متن‌ها عین پیام‌های واقعی ۱۴۰۵/۰۸/۰۹."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ad_cost.telegram_parser import parse_message  # noqa: E402

SOLTANI = """هزینه بلاگری 5040(سلطانی )
 تاریخ1405/08/09
 مجموع :      50.710.000تومان با ارزش افزوده

 هزینه محصول
دمنوش : 18.000.000
 دی دی: 21.110.000
قهوه:6.600.000
شامپو:5.000.000

 اینفلوادوایس:
31.700.000
 اینفلوادوایس با ارزش افزوده
34.870.000

اینفلو ترند:
14.400.000
اینفلو ترند با ارزش افزوده:
15.840.000
"""

SHIRMOHAMMADI = """هزینه بلاگری شیرمحمدی (با ارزش افزوده) 5040

تاریخ: 1405/08/09

ادوایس:
 122,815,000
ترند
5,940,000

مستقیم:
14,850,000

آرتان:
14,630,000
مجموع:
158,235,000


آمار به تفکیک محصول:

جلبک:
10,890,000

دمنوش:
66,110,000

دی دی:
14,630,000

جوانساز:
19,800,000

سفیدکننده:
0

ضد لک:
0


قهوا لاغری:
6,875,000

شامپو:
39,930,000


فیلر:
0
"""

TV = """زینه تبلیغات صدا و سیما با ارزش افزوده ۵۰۴۰

          مورخ ۱۴۰۵/۰8/09


برنامه صبحانه ایرانی (شبکه ۲)دی دی کرم

117/000/000 T

برنامه صبحانه ایرانی (شبکه ۲)سرم ضدلک
117/000/000 T

مجموع هزینه:234/000/000 T
"""

HAJIZADEH = """اعلام   هزینه  شرکت 5040 پیام رسان
1405/08/09
 حاجی زاده
مجموع با ارزش افزوده 18.000.000
ایتا پریماه    6.000.000
شتاب    12.000.000

ضدلک 2.000.000
جوانساز 16.000.000
"""

ZANDI = """.اعلام هزینه با ارزش افزوده
مورخ 1405/08/09
اینفلوئنسری 5040 زندی

ادوایس:
69.850.000t
ترند:
7.920.000t
آرتان:
0t
مستقیم:
152.405.000t
مجموع:
230.175.000t

➖➖➖➖
دمنوش :
36.520.000t
جلبک :
0t
جوانساز:
73.150.000t
بلیچینگ:
0t
شامپو :
0t
دی دی کرم :
49.500.000t
قهوه لاغری :
46.805.000t
دور چشم :
24.200.000t
حجم دهنده لب :
0t
"""

PAGES = """پیج های اینستاگرام 5040
 05/08/09
دمنوش با ارزش افزوده:
8.800.000
جلبک با ارزش افزوده :
7.700.000
قهوه با ارزش افزوده:
0
بیلیچینگ بارزش افزوده :
0
شامپو با ارزش افزوده:
0
جوانساز با ارزش افزوده :
3.300.000
دی دی کرم با ارزش افزوده:
7.7000.000
کرم دور چشم با ارزش افزوده:
0
➖➖➖➖➖➖➖
ادوایس با ارزش افزوده:
0
ترند با ارزش افزوده:
0
مستقیم با ارزش افزوده:
27.500.000
➖➖➖➖➖➖➖➖
مجموع با ارزش افزوده :
27.500.000
"""


def nonzero(d):
    return {k: v for k, v in d.items() if v}


def test_soltani_prefers_vat_amounts():
    m = parse_message(SOLTANI)
    assert m.ok, m.errors
    assert (m.company, m.date, m.supervisor, m.platform, m.total) == ("54", "1405/08/09", "سلطانی", "اینفلو", 50_710_000)
    assert m.agencies == {"ادوایس": 34_870_000, "ترند": 15_840_000}
    assert m.products == {"دمنوش": 18_000_000, "دی دی کرم": 21_110_000, "قهوه ساشه ای": 6_600_000,
                          "شامپو اسپیرولینا": 5_000_000}


def test_shirmohammadi_label_on_previous_line():
    m = parse_message(SHIRMOHAMMADI)
    assert m.ok, m.errors
    assert (m.supervisor, m.platform, m.total) == ("شیرمحمدی", "اینفلو", 158_235_000)
    assert m.agencies == {"ادوایس": 122_815_000, "ترند": 5_940_000, "مستقیم": 14_850_000, "ارتان": 14_630_000}
    assert nonzero(m.products) == {"جلبک": 10_890_000, "دمنوش": 66_110_000, "دی دی کرم": 14_630_000,
                                   "کرم جوانساز": 19_800_000, "قهوه لاغری": 6_875_000,
                                   "شامپو اسپیرولینا": 39_930_000}


def test_tv_is_borzogi_and_line_is_both_channel_and_product():
    m = parse_message(TV)
    assert m.ok, m.errors
    assert (m.date, m.supervisor, m.platform, m.total) == ("1405/08/09", "بزرگی", "صدا و سیما", 234_000_000)
    assert m.agencies == {"شبکه 2": 234_000_000}
    assert m.products == {"دی دی کرم": 117_000_000, "ضدلک": 117_000_000}


def test_hajizadeh_label_and_amount_on_same_line():
    m = parse_message(HAJIZADEH)
    assert m.ok, m.errors
    assert (m.supervisor, m.platform, m.total) == ("حاجی زاده", "پیامرسان", 18_000_000)
    assert m.agencies == {"ایتا پریماه": 6_000_000, "شتاب": 12_000_000}
    assert m.products == {"ضدلک": 2_000_000, "کرم جوانساز": 16_000_000}


def test_zandi():
    m = parse_message(ZANDI)
    assert m.ok, m.errors
    assert (m.supervisor, m.platform, m.total) == ("زندی", "اینفلو", 230_175_000)
    assert nonzero(m.agencies) == {"ادوایس": 69_850_000, "ترند": 7_920_000, "مستقیم": 152_405_000}
    assert nonzero(m.products) == {"دمنوش": 36_520_000, "کرم جوانساز": 73_150_000, "دی دی کرم": 49_500_000,
                                   "قهوه لاغری": 46_805_000, "کرم دور چشم خاویار": 24_200_000}


def test_pages_is_amirmahdi_and_odd_separator_is_read():
    # «7.7000.000» = ۷٬۷۰۰٬۰۰۰ (کاربر: جداکننده‌ی نامرتب مغایرت نیست)؛ جمع محصولات هم با مجموع می‌خواند.
    m = parse_message(PAGES)
    assert (m.date, m.supervisor, m.platform, m.total) == ("1405/08/09", "امیرمهدی", "اینفلو", 27_500_000)
    assert nonzero(m.agencies) == {"مستقیم": 27_500_000}
    assert m.ok, m.errors


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ad_cost"


def fixture(name):
    sender, text = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").split("\n---\n", 1)
    return parse_message(text, sender, 1405)


def test_fakhari_word_date_and_company_from_supervisor():
    m = fixture("fakhari_word_date_no_company")
    assert m.ok, m.errors
    assert (m.company, m.date, m.supervisor, m.platform, m.total) == ("54", "1405/08/08", "فخاری", "اینفلو", 644_138_000)
    assert sum(m.products.values()) == 644_138_000


def test_tashakori_amount_then_toman_line():
    m = fixture("tashakori_toman_lines")
    assert m.ok, m.errors
    assert (m.date, m.supervisor, m.total) == ("1405/08/08", "تشکری", 511_060_000)
    assert m.agencies["مستقیم"] == 61_820_000


def test_eini_kol_is_total_and_trailing_influ():
    m = fixture("eini_kol_total")
    assert m.ok, m.errors
    assert m.total == 498_630_000
    assert m.agencies == {"ترند": 225_060_000, "ادوایس": 209_770_000, "ارتان": 15_400_000, "مستقیم": 48_400_000}


def test_parvaz_supervisor_from_sender_and_products_only():
    m = fixture("parvaz_sender_products_only")
    assert m.ok, m.errors
    assert (m.company, m.supervisor, m.platform, m.total) == ("54", "پرواز", "پیامک", 211_146_709)
    assert m.agencies == {"پیامک": 211_146_709}
    assert m.products["سفیدکننده دندان"] == 42_352_748


def test_ranjbaran_dotted_date_and_latin_sender():
    m = fixture("ranjbaran_dotted_date_latin_sender")
    assert m.ok, m.errors
    assert (m.company, m.date, m.supervisor, m.platform, m.total) == ("54", "1405/08/08", "رنجبران", "مدیا", 54_989_000)


SATELLITE = """اعلام هزینه ماهواره 5040 - جلبک 

9 آبان 

221.118.012 میلیون تومان"""


def test_satellite_single_amount_is_total_and_supervisor_from_latin_sender():
    m = parse_message(SATELLITE, "Amirreza Eskandari", 1405)
    assert m.ok, m.errors
    assert (m.company, m.date, m.supervisor, m.platform, m.total) == ("54", "1405/08/09", "اسکندری", "ماهواره", 221_118_012)
    assert m.agencies == {"ماهواره": 221_118_012}
    assert m.products == {"جلبک": 221_118_012}


SATELLITE_PERSIAN_SEPARATOR = """اعلام هزینه ۵۰۴۰ – ماهواره

۱ آبان

 ۲۳٬۳۲۱٬۰۴۰ میلیون تومان"""


def test_satellite_persian_thousands_separator_and_product_is_jelbak():
    m = parse_message(SATELLITE_PERSIAN_SEPARATOR, "Amirreza Eskandari", 1405)
    assert m.ok, m.errors
    assert (m.date, m.supervisor, m.total) == ("1405/08/01", "اسکندری", 23_321_040)
    assert m.agencies == {"ماهواره": 23_321_040}
    assert m.products == {"جلبک": 23_321_040}


PARVAZ_WITH_OUTSIDE = """تاریخ. 1405/08/09
پیامک (تفکیک محصول 

جلبک:                           4,756,232

جوانساز:                          77,703,207

دمنوش:                       198,905,284

دندان:                         41,172,251

شامپو:                         33,938,964

دی دی:                        38,574,102

قهوه:                        9,233,458


مجموع+10%:             

404,283,498

➖➖➖➖➖➖➖➖➖➖➖➖


پیامک خارج از شرکت:

تپسل:

قهوه:            10,000,000
دمنوش:        10,000,000



مجموع+10%:             

  20,000,000


➖➖➖➖➖➖➖➖➖➖➖➖

مجموع کل +10%:        
424,283,498"""


def test_parvaz_outside_sms_products_are_added_and_single_agency_gets_grand_total():
    # تأیید کاربر: محصولات «خارج از شرکت» با قبلی جمع می‌شوند و کل مبلغ یک عاملیت «پیامک» است.
    m = parse_message(PARVAZ_WITH_OUTSIDE, "آلما پرواز", 1405)
    assert m.ok, m.errors
    assert (m.supervisor, m.platform, m.total) == ("پرواز", "پیامک", 424_283_498)
    assert m.agencies == {"پیامک": 424_283_498}
    assert m.products["دمنوش"] == 208_905_284
    assert m.products["قهوه ساشه ای"] == 19_233_458


GOOGLE_OLD = """اعلام هزینه (تومان) همکده (گوگل ادز) به تفکیک تاریخ :
 1405/05/29
 مجموع :                                              61,228,340
 مجموع با ارزش افزوده:                                64,289,757
 ———————————
 خانواده              30,298,560
 کلی                  3,770,260
 تلفنی               16,373,335
 خارج               272,960
 فرزند              10,513,225"""


def test_google_ads_vat_total_and_topics_scaled_to_vat():
    # قاعده‌ی کاربر: همیشه عدد نهایی با ارزش افزوده
    m = parse_message(GOOGLE_OLD, "حسین امیری", 1405)
    assert m.ok, m.errors
    assert (m.company, m.supervisor, m.platform, m.total) == ("HK", "گوگل ادز", "گوگل ادز", 64_289_757)
    assert m.agencies == {"گوگل ادز": 64_289_757}
    assert sum(m.products.values()) == 64_289_757
    assert m.products["خارج"] == 272_960 * 64_289_757 // 61_228_340


def test_google_ads_test_campaign_is_separate_supervisor():
    text = GOOGLE_OLD.replace("همکده (گوگل ادز)", "گوگل ادز همکده (تست علی اصغر)")
    m = parse_message(text, "حسین امیری", 1405)
    assert (m.supervisor, m.platform) == ("گوگل ادز(تست)", "گوگل ادز(تست)")


def test_product_with_raw_and_vat_amount_takes_vat():
    text = """هزینه بلاگری 5040(سلطانی )
 تاریخ1405/08/09
 مجموع : 11.000.000 با ارزش افزوده
دمنوش : 10.000.000
دمنوش با ارزش افزوده: 11.000.000
ادوایس با ارزش افزوده: 11.000.000"""
    m = parse_message(text, None, 1405)
    assert m.ok, m.errors
    assert m.products == {"دمنوش": 11_000_000}


def test_amount_separators_are_never_a_mismatch():
    # کاربر: جداکننده‌ی سه‌رقمی نقطه، کاما، «/» یا هیچ است؛ «7.7000.000» همان ۷٬۷۰۰٬۰۰۰ است.
    from ad_cost.telegram_parser import _parse_amount
    errors = []
    assert [_parse_amount(s, errors) for s in ("7.7000.000", "12.00.000", ".9.000.000", "117/000/000",
                                               "23,321,040", "7700000")] == [
        7700000, 12000000, 9000000, 117000000, 23321040, 7700000]
    assert errors == []
