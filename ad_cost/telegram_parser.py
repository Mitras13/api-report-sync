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
    ("قهوه لاغری", "قهوه لاغری"), ("قهوا لاغری", "قهوه لاغری"), ("قهوه", "قهوه لاغری"),
    ("شامپو", "شامپو اسپیرولینا"),
    ("دمنوش", "دمنوش"),
    ("ضد چروک", "ضد چروک"), ("ضدچروک", "ضد چروک"),
    ("دی دی", "دی دی کرم"),
    ("سفیدکننده", "سفیدکننده دندان"), ("سفید کننده", "سفیدکننده دندان"),
    ("بلیچینگ", "سفیدکننده دندان"), ("بیلیچینگ", "سفیدکننده دندان"),
    ("کبد", "کبد"),
    ("ضد افتاب", "ضد افتاب"), ("ضد آفتاب", "ضد افتاب"),
    ("ضد لک", "ضدلک"), ("ضدلک", "ضدلک"),
    ("جلبک", "جلبک"),
    ("اتو", "اتو لباس"),
    ("لوسیون", "لوسیون روشن"),
    ("جوانساز", "کرم جوانساز"), ("جوان ساز", "کرم جوانساز"),
    ("ضد جوش", "ضد جوش"), ("ضدجوش", "ضد جوش"),
    ("دور چشم", "کرم دور چشم خاویار"),
    ("فیلر", "فیلر حجم دهنده لب"), ("حجم دهنده لب", "فیلر حجم دهنده لب"),
]
AGENCY_ALIASES = {"آرتان": "ارتان"}

SUPERVISORS = ["اسکندری", "امیرمهدی", "بختیاری", "بزرگی", "پرواز", "تشکری", "حاجی زاده", "رنجبران",
               "زندی", "سلطانی", "شیرمحمدی", "صالحی", "صدفی", "عینی", "فخاری", "قشمی", "مددی", "منتظری"]
# پیام‌هایی که اسم سرپرست ندارند: کلیدواژه‌ی سرتیتر -> سرپرست.
SUPERVISOR_BY_KEYWORD = [("صدا و سیما", "بزرگی"), ("پیج های اینستاگرام", "امیرمهدی")]
PLATFORM_BY_KEYWORD = [("صدا و سیما", "صدا و سیما"), ("پیام رسان", "پیامرسان"), ("بلاگری", "اینفلو"),
                       ("اینفلو", "اینفلو"), ("پیج های اینستاگرام", "اینفلو"), ("پیامک", "پیامک"),
                       ("مدیا", "مدیا"), ("یکتانت", "یکتانت")]

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DATE = re.compile(r"(\d{2,4})/(\d{1,2})/(\d{1,2})")
# مبلغ در انتهای خط، با واحد و «با ارزش افزوده» اختیاری بعدش.
_AMOUNT = re.compile(r"(\d[\d.,/]*)\s*(?:t|T|تومان|ت)?\s*(?:با ارزش افزوده)?\s*$")
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
    return re.sub(r"[ \t]+", " ", text)


def _parse_amount(raw: str, errors: list):
    groups = re.split(r"[.,/]", raw)
    if len(groups) > 1 and (not 1 <= len(groups[0]) <= 3 or any(len(g) != 3 for g in groups[1:])):
        errors.append(f"مبلغ بدفرم: {raw}")
    return int("".join(groups))


def _product(label: str):
    for alias, name in PRODUCT_ALIASES:
        if alias in label:
            return name
    return None


def _clean_label(label: str) -> str:
    label = _VAT.sub("", label)
    label = re.sub(r"[:：\-]", " ", label)
    label = re.sub(r"^\s*اینفلو\s*", "", label)  # «اینفلوادوایس» / «اینفلو ترند»
    label = re.sub(r"^\s*هزینه\s+", "", label)
    return " ".join(label.split())


def _first(text: str, table):
    for key, value in table:
        if key in text:
            return value
    return None


def parse_message(text: str) -> ParsedMessage:
    text = normalize(text)
    msg = ParsedMessage()
    msg.company = "HK" if "همکده" in text else "54" if "5040" in text else None
    m = _DATE.search(text)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        msg.date = f"{y + 1400 if y < 100 else y}/{mo:02d}/{d:02d}"
    header = text.replace("صداوسیما", "صدا و سیما")
    msg.supervisor = next((s for s in SUPERVISORS if s in header), None) or _first(header, SUPERVISOR_BY_KEYWORD)
    msg.platform = _first(header, PLATFORM_BY_KEYWORD)

    vat_seen = set()
    pending = None
    for line in text.splitlines():
        line = re.sub(r"(?<!\d)5040(?!\d)", "", line).strip(" .➖")  # کد شرکت در سرتیتر، مبلغ نیست
        if not line or _DATE.search(line):
            continue
        am = _AMOUNT.search(line)
        if not am:
            pending = line
            continue
        label = line[:am.start()].strip() or pending or ""
        pending = None
        amount = _parse_amount(am.group(1), msg.errors)
        is_vat = bool(_VAT.search(label))
        label = _clean_label(label.replace("صداوسیما", "صدا و سیما"))

        if label.startswith("مجموع"):
            msg.total = amount
            continue
        channel = _CHANNEL.search(label)
        product = _product(label)
        if channel:  # صدا و سیما: «برنامه … (شبکه ۲) دی دی کرم» هم عاملیت است هم محصول
            agency = f"شبکه {channel.group(1)}"
        elif product:
            msg.products[product] = msg.products.get(product, 0) + amount
            continue
        else:
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

    for name, value in [("شرکت", msg.company), ("تاریخ", msg.date), ("سرپرست", msg.supervisor),
                        ("بستر", msg.platform), ("مجموع", msg.total)]:
        if value is None:
            msg.errors.append(f"{name} پیدا نشد")
    if msg.total is not None:
        for name, part in [("عاملیت‌ها", msg.agencies), ("محصولات", msg.products)]:
            if part and sum(part.values()) != msg.total:
                msg.errors.append(f"جمع {name} ({sum(part.values()):,}) ≠ مجموع ({msg.total:,})")
        if not msg.products:
            msg.errors.append("هیچ محصولی پیدا نشد")
    return msg
