"""انتخاب آخرین اعلام هزینه برای هر روز و سرپرست (ad_cost/telegram_loader.py: pick_latest)."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ad_cost.telegram_loader import pick_latest  # noqa: E402
from ad_cost.telegram_parser import ParsedMessage  # noqa: E402


def msg(total, ok=True, date="1405/08/09", supervisor="زندی", platform="اینفلو"):
    return ParsedMessage(company="54", date=date, supervisor=supervisor, platform=platform, total=total,
                         errors=[] if ok else ["جمع عاملیت‌ها ≠ مجموع"])


def at(hour):
    return datetime(2026, 11, 1, hour)


def test_later_announcement_replaces_earlier():
    parsed = {(1, 10): (msg(100), "loaded", at(9)), (1, 11): (msg(120), "loaded", at(10))}
    assert pick_latest(parsed) == {(1, 11)}


def test_edit_time_counts_as_announcement_time():
    # پیام ۱۰ ساعت ۹ فرستاده شده ولی ساعت ۱۱ ویرایش شده: آخرین اعلام همان است
    parsed = {(1, 10): (msg(100), "loaded", at(11)), (1, 11): (msg(120), "loaded", at(10))}
    assert pick_latest(parsed) == {(1, 10)}


def test_latest_with_error_is_still_loaded_with_its_total():
    # کاربر: حتی اعلام خطادار ثبت می‌شود و با ادیت/اصلاح عدد درست جایش می‌نشیند.
    parsed = {(1, 10): (msg(100), "loaded", at(9)), (1, 11): (msg(120, ok=False), "needs_review", at(10))}
    assert pick_latest(parsed) == {(1, 11)}


def test_balanced_puts_gap_under_unsplit():
    # فخاری ۰۸/۰۶: عاملیت‌ها = مجموع ۵۵۷٫۱۵، محصولات ۵۵۵٫۱۵
    from ad_cost.telegram_loader import balanced
    p = ParsedMessage(company="54", date="1405/08/06", supervisor="فخاری", platform="اینفلو", total=557150000,
                      agencies={"ترند": 56760000, "ادوایس": 141790000, "مستقیم": 312400000, "ارتان": 46200000},
                      products={"دمنوش": 40020000, "کرم جوانساز": 252560000, "شامپو اسپیرولینا": 138050000,
                                "دی دی کرم": 124520000, "جلبک": 0})
    agencies, products = balanced(p)
    assert agencies == p.agencies
    assert products["تقسیم‌نشده"] == 2000000 and "جلبک" not in products
    assert sum(products.values()) == 557150000


def test_unparsed_key_does_not_replace_anything():
    parsed = {(1, 10): (msg(100), "loaded", at(9)),
              (1, 11): (msg(120, ok=False, supervisor=None), "needs_review", at(10))}
    assert pick_latest(parsed) == {(1, 10)}


def test_other_days_supervisors_platforms_are_independent():
    parsed = {(1, 10): (msg(100), "loaded", at(9)),
              (1, 11): (msg(100, date="1405/08/08"), "loaded", at(10)),
              (1, 12): (msg(100, supervisor="عینی"), "loaded", at(10)),
              (1, 13): (msg(100, platform="پیامرسان"), "loaded", at(10))}
    assert pick_latest(parsed) == {(1, 10), (1, 11), (1, 12), (1, 13)}


def test_before_cutoff_and_ignored_are_not_candidates():
    parsed = {(1, 10): (msg(100), "loaded", at(9)), (1, 11): (msg(120), "before_cutoff", at(10))}
    assert pick_latest(parsed) == {(1, 10)}


# --- اصلاح تاریخ با ریپلای (parse_all)
from ad_cost.telegram_loader import parse_all  # noqa: E402
from ad_cost.telegram_parser import parse_date_fix  # noqa: E402

FAKHARI_0808 = """❌اعلام هزینه با ارزش افزوده ❌
8  ابان  فخاری
ترند: 100
ادوایس : 200
جمع کل  :
300
➖➖➖➖
دمنوش : 300"""


def row(msg_id, text, hour, reply_to=None, sender="Elmira"):
    return {"key": (1, msg_id), "text": text, "at": at(hour), "sender": sender, "sent_at": at(hour), "reply_to": reply_to}


def test_date_fix_texts_from_the_group():
    assert parse_date_fix("همکده قشمی\n❌ادیت تاریخ ❌\n❌۱۴۰۵/۰۸/۰۹❌") == "1405/08/09"
    assert parse_date_fix("اصلاح تاریخ ۱۴۰۵/۰۸/۰۶") == "1405/08/06"
    assert parse_date_fix("31 شهریور درسته") == "1405/06/31"
    assert parse_date_fix("1405.06.07") == "1405/06/07"
    # یادداشت، نه اصلاحیه
    assert parse_date_fix("سلام وقت بخیر ، هزینه 3 ابان خانم فخاری رو کلی گذاشتم ، خودشون میان کامل میکنن") is None
    # پیام کامل با مبلغ اصلاحیه‌ی تاریخ نیست (اعلام جدید است)
    assert parse_date_fix(FAKHARI_0808) is None


def test_reply_moves_message_to_corrected_date():
    parsed = parse_all([row(10, FAKHARI_0808, 9), row(11, "❌ادیت تاریخ❌ 9 آبان", 10, reply_to=10)], cutoff=None)
    p, status, when = parsed[(1, 10)]
    assert (p.date, status, when) == ("1405/08/09", "loaded", at(10))
    assert parsed[(1, 11)][1] == "date_fix"
    assert pick_latest(parsed) == {(1, 10)}


def test_corrected_message_no_longer_replaces_real_announcement_of_old_date():
    # پیام ۹ تاریخ ۰۸/۰۸ واقعی است؛ پیام ۱۰ به اشتباه ۰۸/۰۸ زده شده و بعداً به ۰۸/۰۹ اصلاح شده.
    real_0808 = FAKHARI_0808.replace("300", "999").replace("100", "799")
    parsed = parse_all([row(9, real_0808, 8), row(10, FAKHARI_0808, 9),
                        row(11, "اصلاح تاریخ ۱۴۰۵/۰۸/۰۹", 10, reply_to=10)], cutoff=None)
    assert pick_latest(parsed) == {(1, 9), (1, 10)}
    assert parsed[(1, 9)][0].date == "1405/08/08"
    assert parsed[(1, 10)][0].date == "1405/08/09"


def test_date_fix_reply_to_unknown_message_is_ignored():
    parsed = parse_all([row(11, "اصلاح تاریخ ۱۴۰۵/۰۸/۰۹", 10, reply_to=999)], cutoff=None)
    assert parsed[(1, 11)][1] == "ignored"


def test_full_reply_with_date_edit_keyword_replaces_original():
    # مهرانی: پیام ۰۸/۰۸، بعد ریپلای کامل «#ادیت تاریخ» با تاریخ ۰۸/۰۹ → فقط ۰۸/۰۹ می‌ماند
    fixed = "#ادیت تاریخ\n" + FAKHARI_0808.replace("8  ابان", "9  ابان")
    parsed = parse_all([row(10, FAKHARI_0808, 9), row(11, fixed, 10, reply_to=10)], cutoff=None)
    assert parsed[(1, 10)][1] == "superseded"
    assert pick_latest(parsed) == {(1, 11)}


def test_next_day_report_as_reply_keeps_previous_day():
    # زندی/عینی/تشکری گزارش هر روز را زیر گزارش دیروز می‌فرستند
    nextday = FAKHARI_0808.replace("8  ابان", "9  ابان")
    parsed = parse_all([row(10, FAKHARI_0808, 9), row(11, nextday, 23, reply_to=10)], cutoff=None)
    assert pick_latest(parsed) == {(1, 10), (1, 11)}


def test_edit_word_above_date_label_is_not_a_date_edit():
    # عینی: «5040 عینی ادیت\n\nتاریخ 1405/06/27» زیر پیام ۰۶/۲۵ → گزارش روز جدید، ۰۶/۲۵ می‌ماند
    nextday = "ادیت\n\n" + FAKHARI_0808.replace("8  ابان", "9  ابان")
    parsed = parse_all([row(10, FAKHARI_0808, 9), row(11, nextday, 23, reply_to=10)], cutoff=None)
    assert pick_latest(parsed) == {(1, 10), (1, 11)}


def test_hamkadeh_satellite_is_loaded_but_tv_is_ignored():
    # کاربر (طبق آرشیو هزینه): ماهواره (اسکندری) و مدیای (رنجبران) «همکده» جزو همکده‌اند؛ صدا و سیما نه.
    sat = "اعلام هزینه ماهواره همکده \n\n9 آبان \n\n6.046.196 میلیون تومان"
    tv = "هزینه تبلیغات صدا و سیما همکده\nمورخ 1405/08/09\nبرنامه شبکه تهران 70/500/000\nمجموع هزینه:70/500/000 T"
    parsed = parse_all([row(10, sat, 9, sender="Amirreza Eskandari"), row(11, tv, 9)], cutoff=None)
    p, status, _ = parsed[(1, 10)]
    assert status == "loaded"
    assert (p.company, p.supervisor, p.total) == ("HK", "اسکندری", 6046196)
    assert p.agencies == {"ماهواره": 6046196} and p.products == {"کلی": 6046196}
    assert parsed[(1, 11)][1] == "ignored"


def test_wrong_month_is_moved_to_next_month():
    # سلطانی ۲۰۲۶-۰۹-۰۶ (۱۴۰۵/۰۶/۱۵) نوشت «1405/05/13»؛ آرشیو هزینه آن را ۱۴۰۵/۰۶/۱۳ ثبت کرده.
    from datetime import datetime
    from ad_cost.telegram_loader import _wrong_month_fix
    assert _wrong_month_fix("1405/05/13", datetime(2026, 9, 6, 10, 53)) == "1405/06/13"
    assert _wrong_month_fix("1405/06/13", datetime(2026, 9, 6, 10, 53)) is None  # تاریخ درست
    assert _wrong_month_fix("1405/04/13", datetime(2026, 9, 6, 10, 53)) == "1405/06/13"  # هر ماه اشتباهی
    assert _wrong_month_fix("1405/04/25", datetime(2026, 9, 6, 10, 53)) is None  # ۲۵ مرداد و شهریور دورند
    assert _wrong_month_fix("1405/05/31", datetime(2026, 9, 6, 10, 53)) is None  # ۳۱ شهریور بعد از ارسال است


def _row_at(msg_id, text, sent, edited=None):
    return {"key": (1, msg_id), "text": text, "at": edited or sent, "sender": "x", "sent_at": sent, "reply_to": None}


PARVAZ = "هزینه پیامک 5040 پرواز\n{d}\nجلبک: {v}\nمجموع: {v}"


def test_same_day_announcement_followed_by_real_one_belongs_to_previous_day():
    # پرواز: ۲۰۲۶-۱۰-۲۷ (۱۴۰۵/۰۸/۰۵) «1405/08/05» زد ولی مال ۰۸/۰۴ بود؛ ۰۸/۰۵ واقعی فردایش آمد.
    rows = [_row_at(1, PARVAZ.format(d="1405/08/05", v="347.751.148"), datetime(2026, 10, 27, 9, 2)),
            _row_at(2, PARVAZ.format(d="1405/08/05", v="280.601.401"), datetime(2026, 10, 28, 9, 5))]
    parsed = parse_all(rows, cutoff=None)
    assert parsed[(1, 1)][0].date == "1405/08/04"
    assert parsed[(1, 2)][0].date == "1405/08/05"
    assert pick_latest(parsed) == {(1, 1), (1, 2)}


def test_later_edit_marker_wins_over_earlier_message_edited_later():
    base = "اعلام هزینه\nمورخ 1405/08/08\nهمکده رضایی\nادوایس: {v}\nکلی: {v}\nمجموع: {v}"
    rows = [_row_at(1, base.format(v="55,660,000"), datetime(2026, 10, 31, 9, 12), datetime(2026, 10, 31, 16, 9)),
            _row_at(2, "ادیت❌\n" + base.format(v="60,830,000"), datetime(2026, 10, 31, 9, 17),
                    datetime(2026, 10, 31, 16, 7))]
    assert pick_latest(parse_all(rows, cutoff=None)) == {(1, 2)}


def test_platformless_placeholder_is_superseded_by_later_full_message():
    rows = [_row_at(1, "اعلام هزینه با ارزش افزوده\n3 ابان فخاری\nجمع کل : 506.000.000", datetime(2026, 10, 26, 9, 31)),
            _row_at(2, "اعلام هزینه با ارزش افزوده\n3 ابان فخاری\nترند: 471570000\nجمع کل : 471570000\n"
                       "دمنوش : 471570000", datetime(2026, 10, 26, 12, 56))]
    parsed = parse_all(rows, cutoff=None)
    assert parsed[(1, 1)][1] == "superseded"


def test_wrong_month_name_in_later_month():
    # تشکری ۲۰۲۶-۱۰-۱۳ (۱۴۰۵/۰۷/۲۱) نوشت «20مرداد»؛ آرشیو هزینه ۱۴۰۵/۰۷/۲۰.
    from datetime import datetime
    from ad_cost.telegram_loader import _wrong_month_fix
    assert _wrong_month_fix("1405/05/20", datetime(2026, 10, 13, 8, 56)) == "1405/07/20"


def test_auto_date_fix_is_flagged_for_reply():
    from ad_cost.telegram_loader import mismatch_text
    rows = [_row_at(1, PARVAZ.format(d="1405/08/05", v="347.751.148"), datetime(2026, 10, 27, 9, 2)),
            _row_at(2, PARVAZ.format(d="1405/08/05", v="280.601.401"), datetime(2026, 10, 28, 9, 5))]
    p, status, _ = parse_all(rows, cutoff=None)[(1, 1)]
    assert status == "needs_review" and p.date == "1405/08/04"
    text = mismatch_text(p.errors, p.supervisor, p.date, p.total)
    assert "📅 تاریخ پیام احتمالاً اشتباه است" in text and "1405/08/04" in text and "🧮" not in text
    split = mismatch_text(["جمع محصولات (555,150,000) ≠ مجموع (557,150,000)"], "فخاری", "1405/08/06", 557150000)
    assert "(فخاری 1405/08/06)" in split and "🧮" in split and "2,000,000 کمتر" in split
    assert "مجموع 557,150,000 تومان ثبت شد" in split
