"""
تبدیل پیام‌های گروه تلگرام «اعلام هزینه تبلیغات 1405» به ردیف‌های همان دو جدول اکسل
(`ADV_AGN_<CO>`: سرپرست × بستر × عاملیت، و `ADV_PRD_<CO>`: سرپرست × محصول).

پیام‌ها متن آزادند، ولی الگوی مشترک دارند: یک سرتیتر (شرکت، سرپرست، بستر، تاریخ)، بعد
خط‌های «برچسب: مبلغ» (برچسب و مبلغ گاهی در یک خط، گاهی در دو خط پشت‌سرهم) و یک «مجموع».
هر برچسب یا محصول است (طبق PRODUCT_ALIASES)، یا «مجموع»، یا وگرنه عاملیت.

نام‌ها با اکسل یکی می‌شوند (مثلاً «دی دی» → «دی دی کرم»، «آرتان» → «ارتان»). مبالغ با
ارزش افزوده و به همان واحدی که در پیام آمده (تومان) ذخیره می‌شوند، مثل اکسل.

پیام فقط وقتی «ok» است که جمع عاملیت‌ها و جمع محصولات هر کدام با «مجموع» پیام برابر باشد
و همه‌ی مبالغ خوش‌فرم باشند (مثلاً «7.7000.000» خطاست). بقیه برای بررسی دستی برمی‌گردند.
"""
import re
from dataclasses import dataclass, field

# کلید: شکل نرمال‌شده‌ی برچسب در پیام، مقدار: نام محصول در اکسل. ترتیب مهم است (طولانی‌تر اول).
PRODUCT_ALIASES = [
    ("قهوه ساشه", "قهوه ساشه ای"),
    ("قهوه لاغری", "قهوه لاغری"), ("قهوا لاغری", "قهوه لاغری"), ("قهوه", "قهوه"),  # «قهوه» خالی: PLAIN_COFFEE
    ("شامپو", "شامپو اسپیرولینا"),
    ("دمنوش", "دمنوش"),
    ("ضد چروک", "ضد چروک"), ("ضدچروک", "ضد چروک"),
    ("دی دی", "دی دی کرم"),
    ("سفیدکننده", "سفیدکننده دندان"), ("سفید کننده", "سفیدکننده دندان"),
    ("بلیچینگ", "سفیدکننده دندان"), ("بیلیچینگ", "سفیدکننده دندان"), ("بلیچ", "سفیدکننده دندان"),
    ("دندان", "سفیدکننده دندان"), ("سفید", "سفیدکننده دندان"),
    ("کبد", "کبد"),
    ("ضد افتاب", "ضد افتاب"), ("ضد آفتاب", "ضد افتاب"),
    ("ضد لک", "ضدلک"), ("ضدلک", "ضدلک"),
    ("جلبک", "جلبک"),
    ("اتو", "اتو لباس"),
    ("لوسیون", "لوسیون روشن"),
    ("جوانساز", "کرم جوانساز"), ("جوان ساز", "کرم جوانساز"),
    ("ضد جوش", "ضد جوش"), ("ضدجوش", "ضد جوش"),
    ("دور چشم", "کرم دور چشم خاویار"), ("دورچشم", "کرم دور چشم خاویار"), ("خاویار", "کرم دور چشم خاویار"),
    ("فیلر", "فیلر حجم دهنده لب"), ("حجم دهنده لب", "فیلر حجم دهنده لب"),
]
TOTAL_LABELS = ("مجموع", "جمع", "کل", "نهایی")  # «هزینه نهایی با ارزش افزوده» (رومزپور)

# همکده محصول ندارد؛ به‌تفکیک «موضوع» مشاوره اعلام می‌کند (مثل شیت‌های «…-موضوع» اکسل همکده).
# در ParsedMessage برای همکده، `products` همین موضوع‌هاست. ترتیب مهم است (طولانی‌تر اول).
TOPIC_ALIASES = [
    ("تربیت فرزند", "تربیت فرزند"), ("تربیت فرند", "تربیت فرزند"), ("فرزند", "فرزند"),
    ("زناشویی", "زناشویی"), ("خیانت", "خیانت"), ("افسردگی", "افسردگی"), ("استرس", "استرس"),
    ("خانواده", "خانواده"), ("تلفنی", "تلفنی"), ("خارج", "خارج"), ("کلی", "کلی"),
]
# «قهوه» بدون «لاغری»/«ساشه»: اکسل 5040 از ۱۴۰۵/۰۷/۲۹ آن را «قهوه ساشه ای» ثبت
# کرده و قبلش «قهوه لاغری» (بررسی‌شده با اکسپورت تلگرام در برابر اکسل).
PLAIN_COFFEE_SACHET_FROM = "1405/07/29"
# ماهواره‌ی 5040 فقط جلبک تبلیغ می‌کند (اعلام در گروه، ۱۴۰۵/۰۸/۰۹)؛ پیام‌هایش محصول ندارند.
SATELLITE_PRODUCT_54 = "جلبک"
# ماهواره‌ی همکده (اسکندری) موضوع ندارد؛ کل مبلغ «کلی» ثبت می‌شود (آرشیو هزینه فقط به تفکیک سرپرست است).
SATELLITE_TOPIC_HK = "کلی"
AGENCY_ALIASES = {"آرتان": "ارتان"}

SUPERVISORS = ["اسکندری", "امیرمهدی", "بختیاری", "بزرگی", "پرواز", "تشکری", "حاجی زاده", "رنجبران",
               "زندی", "سلطانی", "شیرمحمدی", "صالحی", "صدفی", "عینی", "فخاری", "قشمی", "مددی", "منتظری",
               # همکده
               "عزآبادی", "رومزپور", "رضایی پور", "رضایی", "ریاحی", "دوستی", "هستی", "وفاداران", "زوار",
               "مهرانی", "گوگل ادز"]
SUPERVISORS.sort(key=len, reverse=True)  # «رضایی پور» قبل از «رضایی»
# پیام‌هایی که اسم سرپرست ندارند: کلیدواژه‌ی سرتیتر -> سرپرست.
SUPERVISOR_BY_KEYWORD = [("صدا و سیما", "بزرگی"), ("پیج های اینستاگرام", "امیرمهدی"),
                         ("سرپرست تست 1", "تست 1 قلی پور")]  # همکده، از ۱۴۰۵/۰۸/۰۹؛ اسم ستون آرشیو هزینه
# اسم لاتین فرستنده (با حروف کوچک) -> سرپرست، برای پیام‌هایی که اسم سرپرست در متن ندارند.
SUPERVISOR_BY_SENDER = {"ranjbaran": "رنجبران", "eskandari": "اسکندری", "romezpour": "رومزپور"}
# سرپرست‌هایی که فقط برای 5040 کار می‌کنند: اگر «5040» در پیام نیامده باشد، شرکت از سرپرست معلوم است.
SUPERVISORS_54_ONLY = {"فخاری", "تشکری", "عینی", "پرواز", "رنجبران", "سلطانی", "شیرمحمدی", "بزرگی",
                       "اسکندری", "بختیاری", "صدفی", "مددی", "منتظری", "صالحی"}
JALALI_MONTHS = {"فروردین": 1, "اردیبهشت": 2, "خرداد": 3, "تیر": 4, "مرداد": 5, "شهریور": 6, "مهر": 7,
                 "آبان": 8, "ابان": 8, "آذر": 9, "اذر": 9, "دی": 10, "بهمن": 11, "اسفند": 12}
PLATFORM_BY_KEYWORD = [("صدا و سیما", "صدا و سیما"), ("پیام رسان", "پیامرسان"), ("بلاگری", "اینفلو"),
                       ("اینفلو", "اینفلو"), ("پیج های اینستاگرام", "اینفلو"), ("پیامک", "پیامک"),
                       ("مدیا", "مدیا"), ("یکتانت", "یکتانت"), ("ماهواره", "ماهواره"), ("گوگل ادز", "گوگل ادز")]

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DATE = re.compile(r"(\d{2,4})/(\d{1,2})/(\d{1,2})|(?<![\d.])(14\d\d)\.(\d{1,2})\.(\d{1,2})(?![\d.])")
# «7 آبان» یا «11مرداد» (بدون سال)
_DATE_WORDS = re.compile(r"(?<![\d.,])(\d{1,2})\s*(" + "|".join(JALALI_MONTHS) + r")(?![؀-ۿ])(?!\s*دی)")
# عاملیت‌های اینفلوئنسری: پیامی که بستر را نگفته ولی همین عاملیت‌ها را دارد، «اینفلو» است.
INFLUENCER_AGENCIES = {"ترند", "ادوایس", "مستقیم", "ارتان"}
# مبلغ در انتهای خط، با واحد و «با ارزش افزوده» اختیاری بعدش.
# «221.118.012 میلیون تومان» (ماهواره) هم تومان است؛ «میلیون» فقط بخشی از واحد نوشته‌شده است.
_AMOUNT = re.compile(r"(\d[\d.,/]*)\s*(?:t|T|(?:میلیون\s*)?تومان|ت)?\s*(?:با ارزش افزوده)?\s*$")
_VAT = re.compile(r"با\s*ا?رزش\s*افزوده")
_CHANNEL = re.compile(r"شبکه\s*(\d+)")


@dataclass
class ParsedMessage:
    company: str = None
    date: str = None
    supervisor: str = None
    platform: str = None
    total: int = None
    agencies: dict = field(default_factory=dict)   # عاملیت -> مبلغ
    products: dict = field(default_factory=dict)   # محصول -> مبلغ
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize(text: str) -> str:
    text = text.translate(_DIGITS).replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    text = text.replace("٬", ",").replace("،", ",")  # جداکننده‌ی هزارگان فارسی/عربی
    return re.sub(r"[ \t]+", " ", text)


def _parse_amount(raw: str, errors: list):
    """مبلغ به تومان. جداکننده‌ی سه‌رقمی نقطه، کاما، «/» یا هیچ است (کاربر: مغایرت نیست). تعداد گروه‌ها
    بزرگی عدد را تعیین می‌کند و هر گروه بعد از اولی سه رقم است: «7.7000.000» = ۷٬۷۰۰٬۰۰۰ (صفر اضافه)،
    «12.00.000» = ۱۲٬۰۰۰٬۰۰۰، «.9.000.000» = ۹٬۰۰۰٬۰۰۰."""
    groups = [g for g in re.split(r"[.,/]", raw) if g]
    head, rest = groups[0], groups[1:]
    return int(head + "".join(g[:3].ljust(3, "0") for g in rest))


def _product(label: str):
    for alias, name in PRODUCT_ALIASES:
        if alias in label:
            return name
    return None


def _topic(label: str):
    for alias, name in TOPIC_ALIASES:
        if alias in label:
            return name
    return None


def _clean_label(label: str) -> str:
    label = _VAT.sub("", label)
    label = re.sub(r"[:：\-]", " ", label)
    label = re.sub(r"\+?\s*10\s*%", "", label)  # «مجموع+10%»
    label = re.sub(r"^\s*اینفلو\s*|\s*اینفلو\s*$", "", label)  # «اینفلوادوایس» / «اینفلو ترند» / «ترند اینفلو»
    label = re.sub(r"^\s*(هزینه|مشاوره)(\s+|$)", "", label)
    return " ".join(label.split())


def _first(text: str, table):
    for key, value in table:
        if key in text:
            return value
    return None


DATE_FIX_KEYWORDS = ("ادیت", "اصلاح", "درست", "تاریخ", "مورخ")


def parse_date_fix(text: str, sent_year: int = 1405):
    """تاریخ جدید، اگر این متن (که ریپلای به یک اعلام هزینه است) اصلاحیه‌ی تاریخ باشد؛ وگرنه None.
    اصلاحیه: تاریخ دارد، هیچ مبلغی ندارد، و یا کلمه‌ای مثل «ادیت/اصلاح تاریخ/درسته» دارد یا تقریباً فقط
    یک تاریخ است (مثل «1405.06.07»). یادداشتی مثل «هزینه 3 آبان فخاری را کلی گذاشتم» اصلاحیه نیست."""
    p = parse_message(text, None, sent_year)
    if not p.date or p.total is not None or p.agencies or p.products:
        return None
    norm = normalize(text)
    rest = _DATE_WORDS.sub(" ", _DATE.sub(" ", norm))
    rest = re.sub(r"[^؀-ۿa-zA-Z]+", " ", rest).split()
    if any(k in norm for k in DATE_FIX_KEYWORDS) or len(rest) <= 2:
        return p.date
    return None


def parse_message(text: str, sender: str = None, sent_year: int = 1405, date: str = None) -> ParsedMessage:
    """`sender`: اسم فرستنده در تلگرام (مثلاً «آلما پرواز») وقتی اسم سرپرست در متن نیست.
    `sent_year`: سال شمسی ارسال، برای تاریخ‌های بدون سال مثل «7 آبان».
    `date`: تاریخ اصلاح‌شده با ریپلای (parse_date_fix)؛ جای تاریخ داخل متن می‌نشیند."""
    text = normalize(text)
    msg = ParsedMessage()
    m = _DATE.search(text)
    w = _DATE_WORDS.search(text)
    if date:
        msg.date = date
    elif m:
        y, mo, d = (int(g) for g in m.groups() if g is not None)
        msg.date = f"{y + 1400 if y < 100 else y}/{mo:02d}/{d:02d}"
    elif w:
        msg.date = f"{sent_year}/{JALALI_MONTHS[w.group(2)]:02d}/{int(w.group(1)):02d}"
    header = text.replace("صداوسیما", "صدا و سیما")
    sender = normalize(sender or "")
    msg.supervisor = (next((s for s in SUPERVISORS if s in header), None) or _first(header, SUPERVISOR_BY_KEYWORD)
                      or next((s for s in SUPERVISORS if s in sender), None)
                      or next((v for k, v in SUPERVISOR_BY_SENDER.items() if k in sender.lower()), None))
    msg.company = ("HK" if "همکده" in text else "54" if "5040" in text
                   else "54" if msg.supervisor in SUPERVISORS_54_ONLY or msg.supervisor == "حاجی زاده" else None)
    # حاجی زاده برای هر دو شرکت اعلام می‌کند ولی پیام همکده‌اش همیشه «همکده» دارد؛ بی‌نشان = 5040 (طبق آرشیو هزینه).
    # بستر فقط از سرتیتر (خط‌های قبل از اولین مبلغ)؛ «مدیا: 0T» در بدنه‌ی پیام دوستی عاملیت است، نه بستر.
    head_lines = []
    for line in header.splitlines():
        if _AMOUNT.search(re.sub(r"(?<!\d)5040(?!\d)", "", line).strip(" .➖")) and not (
                _DATE.search(line) or _DATE_WORDS.search(line)):
            break
        head_lines.append(line)
    msg.platform = _first("\n".join(head_lines), PLATFORM_BY_KEYWORD)
    # «گوگل ادز همکده (تست علی اصغر)» کمپین جداست؛ در اکسل همکده ستون «گوگل ادز(تست)».
    if msg.supervisor == "گوگل ادز" and "تست" in "\n".join(head_lines):
        msg.supervisor = msg.platform = "گوگل ادز(تست)"
    hk = msg.company == "HK"

    vat_seen = set()
    pending = None
    section = None  # اسم عاملیت بالای «هزینه: … / هزینه با ارزش افزوده: …» (پیامک رومزپور)
    total_is_vat = False
    pre_vat_total = None  # «مجموع» بدون ارزش افزوده، وقتی «مجموع با ارزش افزوده» هم آمده
    product_vat_seen = set()
    amounts_seen = 0
    for line in text.splitlines():
        line = re.sub(r"(?<!\d)5040(?!\d)", "", line).strip(" .➖")  # کد شرکت در سرتیتر، مبلغ نیست
        # «سرپرست تست 1»: عدد اسم سرپرست، مبلغ نیست
        if not line or _DATE.search(line) or _DATE_WORDS.search(line) or line.startswith("سرپرست"):
            continue
        am = _AMOUNT.search(line)
        if not am:
            pending = line
            cleaned = _clean_label(line)
            if cleaned and not cleaned.split(" ")[0] in TOTAL_LABELS:
                section = cleaned
            continue
        label = line[:am.start()].strip() or pending or ""
        pending = None
        amount = _parse_amount(am.group(1), msg.errors)
        amounts_seen += 1
        is_vat = bool(_VAT.search(label))
        label = _clean_label(label.replace("صداوسیما", "صدا و سیما"))

        if label.split(" ")[0] in TOTAL_LABELS if label else False:
            # «مجموع» و «مجموع با ارزش افزوده» هر دو آمده باشند (گوگل ادز): با ارزش افزوده.
            if is_vat and msg.total is not None and not total_is_vat:
                pre_vat_total = msg.total
            if is_vat or not total_is_vat:
                msg.total, total_is_vat = amount, is_vat
            elif not is_vat:
                pre_vat_total = amount
            continue
        if not label and section:
            label = section
        channel = _CHANNEL.search(label)
        product = _topic(label) if hk else _product(label)
        if channel:  # صدا و سیما: «برنامه … (شبکه ۲) دی دی کرم» هم عاملیت است هم محصول
            agency = f"شبکه {channel.group(1)}"
        elif product:
            # مثل عاملیت: اگر هم خام و هم «با ارزش افزوده» آمده، فقط با ارزش افزوده. تکرار بدون این
            # برچسب (مثل «پیامک خارج از شرکت» پرواز) جمع می‌شود.
            if product in msg.products and (product in product_vat_seen) != is_vat:
                if is_vat:
                    msg.products[product] = amount
                    product_vat_seen.add(product)
            else:
                msg.products[product] = msg.products.get(product, 0) + amount
                if is_vat:
                    product_vat_seen.add(product)
            continue
        else:
            # سلطانی: «ایتا و روبیکا پریماه» و در خط با ارزش افزوده «ایتاو روبیکا پریماه»؛ باید یک عاملیت باشند.
            label = re.sub(r"ایتاو(?=\s)", "ایتا و", label)
            agency = AGENCY_ALIASES.get(label, label)
        if not agency:
            msg.errors.append(f"مبلغ بدون برچسب: {am.group(1)}")
            continue
        # «ادوایس» و «ادوایس با ارزش افزوده» هر دو آمده باشند: فقط با ارزش افزوده.
        if agency in msg.agencies and (agency in vat_seen) != is_vat:
            if is_vat:
                msg.agencies[agency] = amount
                vat_seen.add(agency)
        else:
            msg.agencies[agency] = msg.agencies.get(agency, 0) + amount
            if is_vat:
                vat_seen.add(agency)
        if channel and product:
            msg.products[product] = msg.products.get(product, 0) + amount

    if "قهوه" in msg.products:
        coffee = ("قهوه ساشه ای" if msg.date and msg.date >= PLAIN_COFFEE_SACHET_FROM else "قهوه لاغری")
        msg.products[coffee] = msg.products.get(coffee, 0) + msg.products.pop("قهوه")
    # گوگل ادز (قدیمی): موضوع‌ها فقط بدون ارزش افزوده آمده‌اند (جمعشان = «مجموع» خام) ولی «مجموع با ارزش
    # افزوده» هم هست. عدد نهایی باید با ارزش افزوده باشد، پس موضوع‌ها به همان نسبت بزرگ می‌شوند
    # (باقی‌مانده‌ی گرد کردن روی بزرگ‌ترین موضوع).
    if (pre_vat_total and total_is_vat and msg.products and not product_vat_seen
            and sum(msg.products.values()) == pre_vat_total and msg.total != pre_vat_total):
        scaled = {k: v * msg.total // pre_vat_total for k, v in msg.products.items()}
        biggest = max(scaled, key=lambda k: msg.products[k])
        scaled[biggest] += msg.total - sum(scaled.values())
        msg.products = scaled
    # پیام تک‌مبلغی بدون «مجموع» (مثل «ماهواره 5040 - جلبک / 9 آبان / 221.118.012»): همان مبلغ کل است.
    if msg.total is None and amounts_seen == 1:
        msg.total = sum(msg.products.values()) + sum(msg.agencies.values())
    if msg.platform == "ماهواره" and msg.company == "54" and msg.total is not None:
        msg.products = {SATELLITE_PRODUCT_54: msg.total}
        msg.agencies = {"ماهواره": msg.total}
    elif msg.platform == "ماهواره" and msg.company == "HK" and msg.total is not None:
        msg.products = {SATELLITE_TOPIC_HK: msg.total}
        msg.agencies = {"ماهواره": msg.total}
    elif msg.company == "HK" and amounts_seen == 1 and not msg.products and msg.total is not None:
        # پیام تک‌مبلغی همکده بدون موضوع و عاملیت («سرپرست تست 1 / 710,600,000 تومان»)
        msg.products = {SATELLITE_TOPIC_HK: msg.total}
        msg.agencies = {"نامشخص": msg.total}
    nonzero_agencies = {a for a, v in msg.agencies.items() if v}
    if msg.platform is None and msg.agencies and nonzero_agencies <= INFLUENCER_AGENCIES:
        msg.platform = "اینفلو"
    if msg.platform is None and hk:
        msg.platform = "نامشخص"  # اکسل همکده بستر ندارد (فقط سرپرست × عاملیت)
    # پیامی که فقط تفکیک محصول دارد (مثل پیامک پرواز): کل مبلغ یک عاملیت هم‌نام بستر است، مثل اکسل.
    if not msg.agencies and msg.products and msg.platform and msg.total is not None:
        msg.agencies[msg.platform] = msg.total

    # پیام «مجموع: 0» (روز بی‌هزینه) محصول و بستر لازم ندارد.
    zero = msg.total == 0
    for name, value in [("شرکت", msg.company), ("تاریخ", msg.date), ("سرپرست", msg.supervisor),
                        ("بستر", msg.platform or ("-" if zero else None)), ("مجموع", msg.total)]:
        if value is None:
            msg.errors.append(f"{name} پیدا نشد")
    if msg.total is not None:
        for name, part in [("عاملیت‌ها", msg.agencies), ("موضوع‌ها" if hk else "محصولات", msg.products)]:
            if part and sum(part.values()) != msg.total:
                msg.errors.append(f"جمع {name} ({sum(part.values()):,}) ≠ مجموع ({msg.total:,})")
        if not msg.products and not zero:
            msg.errors.append("هیچ موضوعی پیدا نشد" if hk else "هیچ محصولی پیدا نشد")
    return msg
