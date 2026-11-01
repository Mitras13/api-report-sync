"""
خواندن پیام‌های گروه «اعلام هزینه تبلیغات» و لود آن‌ها در ADV_AGN_<CO> / ADV_PRD_<CO>.

دو منبع پیام، هر دو اول به‌صورت خام در dbo.ADV_TG_MSG ذخیره می‌شوند:
- ربات (`@API_analizgozareshatbot`, توکن در tokens/telegram_bot.txt) با getUpdates. تلگرام
  آپدیت‌ها را فقط ۲۴ ساعت نگه می‌دارد، پس این باید حداقل روزی یک بار (ترجیحاً ساعتی) اجرا شود.
  ربات فقط پیام‌های بعد از عضویتش را می‌بیند و باید ادمین گروه باشد (privacy mode).
- اکسپورت Telegram Desktop برای تاریخچه‌ی قبل از ربات: JSON (`--export result.json`) یا HTML
  (`--export <پوشه‌ی ChatExport_…>`).

بعد هر پیام با ad_cost/telegram_parser.py پارس می‌شود. برای هر (شرکت، تاریخ، سرپرست، بستر)
فقط آخرین اعلام حساب می‌شود (پیام ویرایش‌شده یا اعلام دوباره، جایگزین قبلی است؛ pick_latest).
ردیف‌ها با `_SourceFile = 'telegram:<chat_id>:<message_id>'` نوشته می‌شوند و
scripts/load_ad_cost.py این ردیف‌ها را دست نمی‌زند.
تاریخ‌های قبل از TELEGRAM_FROM (برای هر شرکت) از اکسل می‌آیند و از تلگرام لود نمی‌شوند.
جدول‌ها: 5040 → ADV_AGN_54 / ADV_PRD_54، همکده → ADV_AGN_HK / ADV_TOP_HK (موضوع).

وضعیت هر پیام در ADV_TG_MSG.[Status]:
  loaded / needs_review (جمع نمی‌خواند یا تاریخ اشتباه؛ [Errors] را ببین) / superseded (پیام
  جدیدتری برای همان روز و سرپرست آمده) / before_cutoff / ignored (پیام غیرهزینه‌ای).

ربات به پیام‌های needs_review در خود گروه ریپلای می‌زند و خطا را اعلام می‌کند (یک بار برای هر
مجموعه خطا). اگر پیام بعداً ویرایش و درست شد، «برطرف شد» را ریپلای می‌کند.

اجرا:
    python -m ad_cost.telegram_loader                       # ربات
    python -m ad_cost.telegram_loader --export result.json  # تاریخچه
"""
import argparse
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import jdatetime
import requests

from ad_cost.telegram_parser import SUPERVISORS_54_ONLY, parse_date_fix, parse_message
from db.sql_loader import get_connection

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / "tokens" / "telegram_bot.txt"
SQL_SERVER = "localhost"
SQL_DATABASE = "Mitra_sarkhosh"
CHAT_TITLE_KEYWORD = "اعلام هزینه"
GROUP_CHAT_ID = -1003764661569  # سوپرگروه «اعلام هزینه تبلیغات 1405»؛ برای اکسپورت HTML که شناسه ندارد
GROUP_TITLE = "اعلام هزینه تبلیغات 1405"
# از این روز به بعد گزارش نهایی از تلگرام است و قبلش از اکسل (کاربر، ۲۰۲۶-۱۱-۰۱: تلگرام با آرشیو هزینه
# بهتر از اکسل‌ها می‌خواند). اولین پیام‌های اکسپورت گروه: همکده ۰۵/۱۰، 5040 ۰۵/۱۱.
TELEGRAM_FROM = {"54": "1405/05/11", "HK": "1405/05/10"}
# جدول‌ها: عاملیت و (5040: محصول، همکده: موضوع)
AGN_TABLE = {"54": "ADV_AGN_54", "HK": "ADV_AGN_HK"}
DETAIL_TABLE = {"54": ("ADV_PRD_54", "محصول"), "HK": ("ADV_TOP_HK", "موضوع")}
SOURCE_PREFIX = "telegram:"
# «ادیت تاریخ» در یک خط؛ «ادیت» بالای پیام + «تاریخ: …» در خط بعد یعنی ادیت هزینه، نه تاریخ (عینی، شیرمحمدی).
DATE_EDIT_RE = re.compile(r"(ادیت|اصلاح)[ \t]*(ی[ \t]*)?تاریخ")
# «ادیت❌» در خط اول پیام: اعلام اصلاح‌شده‌ی همان روز
EDIT_MARK_RE = re.compile(r"ادیت|اصلاح")
# تاریخی که ربات خودش اصلاح کرده (ماه اشتباه، یا روز بعد به‌جای همان روز): ثبت می‌شود و ریپلای می‌خورد.
DATE_WARNING = "تاریخ پیام {wrong} است، ولی با زمان ارسال به نظر می‌رسد مربوط به {used} باشد؛ فعلاً {used} ثبت شد"
# سرپرست‌های 5040 که برای همکده هم هزینه اعلام می‌کنند (پیامشان «همکده» دارد): ماهواره و مدیا.
HK_ALSO = {"اسکندری", "رنجبران"}

logger = logging.getLogger("ad_cost.telegram")

DDL = """
IF OBJECT_ID('dbo.ADV_TG_MSG', 'U') IS NULL
CREATE TABLE dbo.ADV_TG_MSG (
    ChatId BIGINT NOT NULL, MessageId BIGINT NOT NULL, ChatTitle NVARCHAR(200) NULL,
    SentAt DATETIME2(0) NOT NULL, EditedAt DATETIME2(0) NULL, Sender NVARCHAR(200) NULL,
    [Text] NVARCHAR(MAX) NOT NULL, Source NVARCHAR(10) NOT NULL,
    Company NVARCHAR(5) NULL, ReportDate NVARCHAR(10) NULL, Supervisor NVARCHAR(100) NULL,
    Platform NVARCHAR(100) NULL, Total BIGINT NULL,
    Status NVARCHAR(20) NOT NULL DEFAULT 'new', Errors NVARCHAR(MAX) NULL, ProcessedAt DATETIME2(0) NULL,
    CONSTRAINT PK_ADV_TG_MSG PRIMARY KEY (ChatId, MessageId)
);
IF OBJECT_ID('dbo.ADV_TG_STATE', 'U') IS NULL
CREATE TABLE dbo.ADV_TG_STATE (LastUpdateId BIGINT NOT NULL);
IF COL_LENGTH('dbo.ADV_TG_MSG', 'RepliedErrors') IS NULL
ALTER TABLE dbo.ADV_TG_MSG ADD RepliedErrors NVARCHAR(MAX) NULL, RepliedAt DATETIME2(0) NULL;
IF COL_LENGTH('dbo.ADV_TG_MSG', 'ReplyToId') IS NULL
ALTER TABLE dbo.ADV_TG_MSG ADD ReplyToId BIGINT NULL;
""" + "".join(f"""
IF OBJECT_ID('dbo.{t}', 'U') IS NULL
CREATE TABLE dbo.[{t}] (
    [تاریخ] NVARCHAR(10) NOT NULL, [تاریخ میلادی] DATE NOT NULL, [ماه] NVARCHAR(7) NOT NULL,
    [سرپرست] NVARCHAR(100) NOT NULL, [مدیر] NVARCHAR(100) NULL,
    [بستر] NVARCHAR(100) NULL, [عاملیت] NVARCHAR(100) NULL,
    [مبلغ] BIGINT NOT NULL, [مغایرت] NVARCHAR(400) NULL,
    [ردیف اکسل] INT NOT NULL, [_SourceFile] NVARCHAR(400) NOT NULL, [_LoadedAt] DATETIME2(0) NOT NULL
);
IF COL_LENGTH(N'dbo.{t}', N'مغایرت') < 800 ALTER TABLE dbo.[{t}] ALTER COLUMN [مغایرت] NVARCHAR(400) NULL;
""" for t in AGN_TABLE.values()) + "".join(f"""
IF OBJECT_ID('dbo.{t}', 'U') IS NULL
CREATE TABLE dbo.[{t}] (
    [تاریخ] NVARCHAR(10) NOT NULL, [تاریخ میلادی] DATE NOT NULL, [ماه] NVARCHAR(7) NOT NULL,
    [سرپرست] NVARCHAR(100) NOT NULL, [مدیر] NVARCHAR(100) NULL,
    [{col}] NVARCHAR(100) NOT NULL, [مبلغ] BIGINT NOT NULL, [توضیحات] NVARCHAR(MAX) NULL,
    [ردیف اکسل] INT NOT NULL, [_SourceFile] NVARCHAR(400) NOT NULL, [_LoadedAt] DATETIME2(0) NOT NULL
);
""" for t, col in DETAIL_TABLE.values())
TABLES = list(AGN_TABLE.values()) + [t for t, _ in DETAIL_TABLE.values()]


def _api(method: str, **params):
    """صدا زدن Bot API با چند بار تلاش (اتصال از پشت VPN گاهی قطع می‌شود)."""
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    for attempt in range(4):
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=60)
            body = r.json()
            if not body.get("ok"):
                raise RuntimeError(f"{method}: {body.get('description')}")
            return body["result"]
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 3:
                raise
            logger.warning("%s: connection problem, retrying", method)
            time.sleep(5 * (attempt + 1))


def _upsert_message(cur, chat_id, message_id, title, sent_at, edited_at, sender, text, source, reply_to=None):
    cur.execute("SELECT EditedAt, [Text] FROM dbo.ADV_TG_MSG WHERE ChatId = ? AND MessageId = ?", chat_id, message_id)
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO dbo.ADV_TG_MSG (ChatId, MessageId, ChatTitle, SentAt, EditedAt, Sender, [Text], Source, ReplyToId)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            chat_id, message_id, title, sent_at, edited_at, sender, text, source, reply_to)
    elif row[1] != text:  # ویرایش شده: دوباره پارس شود
        cur.execute("UPDATE dbo.ADV_TG_MSG SET [Text] = ?, EditedAt = ?, Status = 'new' WHERE ChatId = ? AND MessageId = ?",
                    text, edited_at or datetime.now(), chat_id, message_id)


def _sender(user: dict) -> str:
    name = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x)
    return f"{name} (@{user['username']})" if user.get("username") else name or None


def _utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().replace(tzinfo=None)


def fetch_bot_updates(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT MAX(LastUpdateId) FROM dbo.ADV_TG_STATE")
    last = cur.fetchone()[0]
    offset = None if last is None else last + 1
    stored = 0
    while True:
        params = {"timeout": 0, "allowed_updates": ["message", "edited_message"]}
        if offset is not None:
            params["offset"] = offset
        updates = _api("getUpdates", **params)
        if not updates:
            break
        for u in updates:
            m = u.get("message") or u.get("edited_message")
            text = (m or {}).get("text") or (m or {}).get("caption")
            chat = (m or {}).get("chat", {})
            if text and CHAT_TITLE_KEYWORD in (chat.get("title") or ""):
                _upsert_message(cur, chat["id"], m["message_id"], chat.get("title"), _utc(m["date"]),
                                _utc(m["edit_date"]) if m.get("edit_date") else None,
                                _sender(m.get("from", {})), text, "bot",
                                (m.get("reply_to_message") or {}).get("message_id"))
                stored += 1
            offset = u["update_id"] + 1
        # آفست فقط بعد از ذخیره‌ی پیام‌ها جلو می‌رود؛ اگر commit نشود، تلگرام دوباره می‌فرستد.
        cur.execute("DELETE FROM dbo.ADV_TG_STATE; INSERT INTO dbo.ADV_TG_STATE VALUES (?)", offset - 1)
        conn.commit()
    return stored


def read_export_json(path: Path) -> list:
    """پیام‌های result.json اکسپورت تلگرام دسکتاپ، هم‌شکل read_export_html (به‌اضافه‌ی زمان ویرایش)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    # اکسپورت شناسه‌ی سوپرگروه را بدون پیشوند -100 می‌دهد؛ ربات با آن.
    chat_id = int(data["id"])
    if data.get("type", "").endswith("supergroup") and chat_id > 0:
        chat_id = int(f"-100{chat_id}")
    out = []
    for m in data.get("messages", []):
        if m.get("type") != "message":
            continue
        raw = m.get("text")
        text = raw if isinstance(raw, str) else "".join(p if isinstance(p, str) else p.get("text", "") for p in raw or [])
        if not text.strip():
            continue
        edited = m.get("edited")
        out.append({"id": m["id"], "date": datetime.fromisoformat(m["date"]),
                    "edited": datetime.fromisoformat(edited) if edited else None,
                    "from": m.get("from"), "text": text, "chat_id": chat_id, "chat": data.get("name"),
                    "reply_to": m.get("reply_to_message_id")})
    return out


def import_export(conn, path: Path) -> int:
    cur = conn.cursor()
    msgs = read_export_json(path)
    for m in msgs:
        _upsert_message(cur, m["chat_id"], m["id"], m["chat"], m["date"], m["edited"], m["from"], m["text"], "export",
                        m["reply_to"])
    conn.commit()
    return len(msgs)


class _ExportHTMLParser(HTMLParser):
    """پیام‌های messages*.html اکسپورت HTML تلگرام دسکتاپ: (id, زمان، فرستنده، متن)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.messages, self._msg, self._field, self._depth, self._sender = [], None, None, 0, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "div" and "message" in cls and "default" in cls:
            self._msg = {"id": int(a["id"].removeprefix("message")), "text": "", "from": None, "date": None,
                         "reply_to": None}
            self.messages.append(self._msg)
        elif self._msg is not None and tag == "div" and self._field is None:
            if "date" in cls and "details" in cls and a.get("title"):
                self._msg["date"] = a["title"]
            elif cls == ["from_name"]:
                self._field, self._depth = "from", 1
            elif cls == ["text"]:
                self._field, self._depth = "text", 1
        elif self._msg is not None and tag == "a" and (a.get("onclick") or "").startswith("return GoToMessage("):
            if self._msg["reply_to"] is None and self._field is None:
                self._msg["reply_to"] = int(a["onclick"].removeprefix("return GoToMessage(").rstrip(")"))
        elif self._field and tag == "div":
            self._depth += 1
        elif self._field == "text" and tag == "br":
            self._msg["text"] += "\n"

    def handle_endtag(self, tag):
        if self._field and tag == "div":
            self._depth -= 1
            if self._depth == 0:
                self._field = None

    def handle_data(self, data):
        if self._field == "text":
            self._msg["text"] += data
        elif self._field == "from":
            self._msg["from"] = (self._msg["from"] or "") + data


def read_export_html(folder: Path) -> list:
    files = sorted(folder.glob("messages*.html"), key=lambda p: int(p.stem.removeprefix("messages") or 1))
    out, sender = [], None
    for f in files:
        p = _ExportHTMLParser()
        p.feed(f.read_text(encoding="utf-8"))
        for m in p.messages:
            sender = (m["from"] or "").strip() or sender  # پیام‌های پشت‌سرهمِ یک نفر اسم ندارند
            text = "\n".join(line.strip() for line in m["text"].strip("\n").splitlines())
            if not text.strip() or not m["date"]:
                continue
            # «31.10.2026 13:57:51 UTC+03:30» -> ساعت محلی همین سیستم
            sent = datetime.strptime(m["date"].split(" UTC")[0], "%d.%m.%Y %H:%M:%S")
            out.append({"id": m["id"], "date": sent, "edited": None, "from": sender, "text": text,
                        "reply_to": m["reply_to"]})
    return out


def import_export_html(conn, folder: Path) -> int:
    cur = conn.cursor()
    msgs = read_export_html(folder)
    for m in msgs:
        _upsert_message(cur, GROUP_CHAT_ID, m["id"], GROUP_TITLE, m["date"], None, m["from"], m["text"], "export",
                        m["reply_to"])
    conn.commit()
    return len(msgs)


def _manager_lookup(cur, company: str) -> dict:
    """آخرین مدیر شناخته‌شده‌ی هر سرپرست (از ردیف‌های اکسل)."""
    cur.execute(f"""
        SELECT [سرپرست], [مدیر] FROM (
            SELECT [سرپرست], [مدیر], ROW_NUMBER() OVER (PARTITION BY [سرپرست] ORDER BY [تاریخ] DESC) rn
            FROM dbo.[{DETAIL_TABLE[company][0]}] WHERE [مدیر] IS NOT NULL) x WHERE rn = 1""")
    return dict(cur.fetchall())


def pick_latest(parsed: dict) -> set:
    """کلید پیام‌هایی که باید لود شوند: برای هر (شرکت، تاریخ، سرپرست، بستر) فقط آخرین اعلام.
    سرپرست‌ها هزینه را با پیام جدید (یا ویرایش) اصلاح می‌کنند، پس آخرین اعلام معتبر است. اعلام خطادار
    (needs_review) هم لود می‌شود، با «مجموع» خودش (`balanced`)، و ربات ریپلای مغایرت می‌زند؛ با ادیت یا
    پیام اصلاحی عدد درست جایش می‌نشیند (خواسته‌ی کاربر؛ آرشیو هزینه هم همین را ثبت کرده).
    پیامی که تاریخ/سرپرست/شرکتش پارس نشده یا هیچ مبلغی ندارد، جانشین چیزی نمی‌شود.

    `parsed`: {(chat_id, msg_id): (ParsedMessage, status, زمان اعلام = ویرایش یا ارسال)}"""
    latest = {}
    for key, (p, status, at) in parsed.items():
        if status not in ("loaded", "needs_review"):
            continue
        k = (p.company, p.date, p.supervisor, p.platform or UNKNOWN)
        if None in k or _total(p) is None:
            continue
        if k not in latest or (parsed[latest[k]][2], latest[k][1]) < (at, key[1]):
            latest[k] = key
    return set(latest.values())


UNKNOWN = "نامشخص"
UNSPLIT = "تقسیم‌نشده"  # مثل لودر اکسل: اختلاف جمع ریزها با مجموع


def _total(p):
    if p.total is not None:
        return p.total
    if p.agencies:
        return sum(p.agencies.values())
    if p.products:
        return sum(p.products.values())
    return None


def balanced(p) -> tuple[dict, dict]:
    """(عاملیت‌ها، محصول‌ها/موضوع‌ها) که جمع هر کدام برابر «مجموع» پیام است؛ کسری یا اضافه زیر «تقسیم‌نشده»."""
    total = _total(p) or 0
    out = []
    for parts in (p.agencies, p.products):
        parts = {k: v for k, v in parts.items() if v}
        gap = total - sum(parts.values())
        if gap:
            parts[UNSPLIT] = parts.get(UNSPLIT, 0) + gap
        out.append(parts)
    return out[0], out[1]


def _wrong_month_fix(date: str | None, sent_at) -> str | None:
    """تاریخ با ماه قبلیِ اشتباه (سلطانی کل شهریور «1405/05/..» زد؛ آرشیو هزینه آن را شهریور ثبت کرده).

    هزینه‌ی هر روز تا چند روز بعد اعلام می‌شود. اگر تاریخ پیام بیش از ۲۰ روز قبل از ارسال باشد ولی همان روز
    در ماه بعد ۰ تا ۷ روز قبل از ارسال بیفتد، ماه بعد درست است."""
    if not date or sent_at is None:
        return None
    y, m, d = map(int, date.split("/"))
    sent = jdatetime.date.fromgregorian(date=sent_at.date())
    # تشکری هم در مهر «20مرداد» زد: ماه کاملاً اشتباه است، پس همان روزِ ماه در ماه ارسال یا ماه قبلش.
    try:
        if (sent - jdatetime.date(y, m, d)).days <= 20:
            return None
    except ValueError:
        return None
    prev_month = (sent.year - (sent.month == 1), 12 if sent.month == 1 else sent.month - 1)
    for cy, cm in ((sent.year, sent.month), prev_month):
        try:
            cand = jdatetime.date(cy, cm, d)
        except ValueError:
            continue
        if 0 <= (sent - cand).days <= 7:
            return cand.strftime("%Y/%m/%d")
    return None


def parse_all(rows: list, cutoff: str | dict | None = None) -> dict:
    """پارس همه‌ی پیام‌ها، با اعمال اصلاحیه‌های تاریخ.

    سرپرست‌ها گاهی تاریخ را اشتباه می‌زنند و بعد زیر همان پیام ریپلای می‌کنند («❌ادیت تاریخ❌ ۱۴۰۵/۰۸/۰۹»،
    «31 شهریور درسته»). چنین ریپلایی (parse_date_fix) تاریخ پیام اصلی را عوض می‌کند و زمان اعلام پیام
    اصلی هم زمان همین اصلاحیه می‌شود (آخرین اعلام برای آن روز است). خود اصلاحیه وضعیت date_fix می‌گیرد.

    `rows`: [{"key": (chat_id, msg_id), "text", "at": زمان ویرایش یا ارسال, "sender", "sent_at", "reply_to"}]
    خروجی: {key: (ParsedMessage, status, زمان اعلام)} برای pick_latest."""
    def year(r):
        return jdatetime.date.fromgregorian(date=r["sent_at"].date()).year

    by_key = {r["key"]: r for r in rows}
    fixes = {}  # کلید پیام اصلی -> (تاریخ جدید، زمان اصلاحیه)
    fix_keys = set()
    replaced = set()  # پیام‌هایی که با ریپلای «ادیت تاریخ» کامل جایگزین شده‌اند
    for r in sorted(rows, key=lambda r: r["at"]):
        if r.get("reply_to") is None:
            continue
        parent = (r["key"][0], r["reply_to"])
        if parent not in by_key:
            continue
        new_date = parse_date_fix(r["text"], year(r))
        if new_date:
            fixes[parent] = (new_date, r["at"])
            fix_keys.add(r["key"])
        elif DATE_EDIT_RE.search(r["text"]):
            # ریپلای کامل با «#ادیت تاریخ»: خودش اعلام جدید است و پیام اصلی (تاریخ اشتباه) کنار می‌رود.
            # ریپلای کامل بدون این کلمه‌ها اعلام روز بعد است (سرپرست‌ها گزارش هر روز را زیر گزارش دیروز
            # می‌فرستند) و به پیام اصلی کاری ندارد.
            replaced.add(parent)

    def status_of(r, p):
        if r["key"] in fix_keys:
            status = "date_fix"
        elif r["key"] in replaced and r["key"] not in fixes:
            status = "superseded"
        elif p.total is None and not p.agencies and not p.products:
            status = "ignored"
        elif p.company == "HK" and p.supervisor in SUPERVISORS_54_ONLY - HK_ALSO:
            # سرپرست فقط-5040 با کلمه‌ی «همکده» در پیام (مثل «صدا و سیما همکده» بزرگی) وارد همکده نمی‌شود.
            # ماهواره‌ی اسکندری و مدیای رنجبران استثنا هستند (`HK_ALSO`)؛ آرشیو هزینه آن‌ها را جزو همکده آورده.
            status = "ignored"
        elif p.date and (c := cutoff.get(p.company) if isinstance(cutoff, dict) else cutoff) and p.date < c:
            status = "before_cutoff"
        else:
            status = "loaded" if p.ok else "needs_review"
        return status

    parsed = {}
    for r in rows:
        date, at = None, r["at"]
        if r["key"] in fixes:
            date, fix_at = fixes[r["key"]]
            at = max(at, fix_at)
        p = parse_message(r["text"], r["sender"], year(r), date=date)
        if date is None and (shifted := _wrong_month_fix(p.date, r["sent_at"])):
            wrong = p.date
            p = parse_message(r["text"], r["sender"], year(r), date=shifted)
            p.errors.append(DATE_WARNING.format(wrong=wrong, used=shifted))
        parsed[r["key"]] = (p, status_of(r, p), at)

    # چند اعلام برای یک (شرکت، تاریخ، سرپرست، بستر)
    groups = defaultdict(list)
    for k, (p, st, _) in parsed.items():
        if st in ("loaded", "needs_review") and p.date:
            groups[(p.company, p.date, p.supervisor, p.platform)].append(k)
    for key, ks in groups.items():
        if len(ks) < 2:
            continue
        ks.sort(key=lambda k: by_key[k]["sent_at"])
        # پرواز ۲۰۲۶-۱۰-۲۷ هزینه‌ی ۰۸/۰۴ را با تاریخ «08/05» زد و فردایش ۰۸/۰۵ واقعی را. هزینه‌ی هر روز صبح
        # فردا اعلام می‌شود؛ پس اولین پیامی که همان روزِ تاریخش فرستاده شده، وقتی پیام دیگری برای همان روز
        # بعد از آن روز آمده و روز قبلش اعلامی ندارد، مال روز قبل است (طبق آرشیو هزینه).
        first = ks[0]
        prev = (jdatetime.date(*map(int, key[1].split("/"))) - timedelta(days=1)).strftime("%Y/%m/%d")
        if (first not in fixes and _jalali(by_key[first]["sent_at"]) == key[1]
                and _jalali(by_key[ks[-1]]["sent_at"]) > key[1] and (key[0], prev, key[2], key[3]) not in groups):
            r = by_key[first]
            p = parse_message(r["text"], r["sender"], year(r), date=prev)
            p.errors.append(DATE_WARNING.format(wrong=key[1], used=prev))
            parsed[first] = (p, status_of(r, p), parsed[first][2])
            ks = ks[1:]
        # «ادیتِ» بعدی بر اعلام‌های قبلی همان روز مقدم است، حتی اگر آن‌ها بعدش (مثلاً بی‌تغییر) ویرایش شده
        # باشند (رضایی همکده ۰۸/۰۸: پیام اول ۱۶:۰۹ ویرایش شد؛ «ادیت» ۰۹:۱۷ فرستاده و ۱۶:۰۷ ویرایش شد).
        for i, k in enumerate(ks[1:], start=1):
            if EDIT_MARK_RE.search(by_key[k]["text"].strip().split("\n", 1)[0]):
                latest_prev = max(parsed[o][2] for o in ks[:i])
                p, st, at = parsed[k]
                if latest_prev >= at:
                    parsed[k] = (p, st, latest_prev + timedelta(seconds=1))
    # اعلام بی‌بستر (فخاری ۰۸/۰۳: «جمع کل 506.000.000»، موقت تا «خودشون میان کامل میکنن») با اعلام
    # بعدیِ بستردار همان روز و سرپرست کنار می‌رود؛ کلیدشان فرق دارد و pick_latest خودش نمی‌فهمد.
    later_with_platform = defaultdict(list)
    for k, (p, st, _) in parsed.items():
        if st in ("loaded", "needs_review") and p.date and p.platform:
            later_with_platform[(p.company, p.date, p.supervisor)].append(by_key[k]["sent_at"])
    for k, (p, st, at) in parsed.items():
        if (st in ("loaded", "needs_review") and p.date and not p.platform
                and any(t > by_key[k]["sent_at"] for t in later_with_platform[(p.company, p.date, p.supervisor)])):
            parsed[k] = (p, "superseded", at)
    return parsed


def _jalali(dt) -> str:
    return jdatetime.date.fromgregorian(date=dt.date()).strftime("%Y/%m/%d")


def process_messages(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT ChatId, MessageId, [Text], COALESCE(EditedAt, SentAt), Sender, SentAt, ReplyToId"
                " FROM dbo.ADV_TG_MSG")
    parsed = parse_all([{"key": (c, m), "text": t, "at": at, "sender": s, "sent_at": sent, "reply_to": rt}
                        for c, m, t, at, s, sent, rt in cur.fetchall()], cutoff=TELEGRAM_FROM)

    winners = pick_latest(parsed)
    counts = {}
    managers = {}
    now = datetime.now()
    for (chat_id, msg_id), (p, status, at) in parsed.items():
        winner = (chat_id, msg_id) in winners
        if status in ("loaded", "needs_review") and not winner:
            status = "superseded"
        counts[status] = counts.get(status, 0) + 1
        source = f"{SOURCE_PREFIX}{chat_id}:{msg_id}"
        for t in TABLES:
            cur.execute(f"DELETE FROM dbo.[{t}] WHERE [_SourceFile] = ?", source)
        if winner:
            if p.company not in managers:
                managers[p.company] = _manager_lookup(cur, p.company)
            _insert_rows(cur, p, source, managers[p.company].get(p.supervisor), now)
        cur.execute(
            "UPDATE dbo.ADV_TG_MSG SET Company = ?, ReportDate = ?, Supervisor = ?, Platform = ?, Total = ?,"
            " Status = ?, Errors = ?, ProcessedAt = ? WHERE ChatId = ? AND MessageId = ?",
            p.company, p.date, p.supervisor, p.platform, p.total, status,
            " | ".join(p.errors) or None, now, chat_id, msg_id)
    conn.commit()
    return counts


def mismatch_text(errors: list, supervisor=None, date=None, total=None) -> str:
    """متن ریپلای (مؤدبانه و کوتاه، خواسته‌ی کاربر): معمولاً یا تاریخ اشتباه است یا تفکیک محصول/عاملیت با مجموع
    نمی‌خواند."""
    date_errs = [e for e in errors if "تاریخ" in e]
    split_errs = [e for e in errors if e.startswith("جمع ")]
    other = [e for e in errors if e not in date_errs and e not in split_errs]
    who = " ".join(x for x in [supervisor, date] if x)
    parts = [f"سلام، وقت بخیر. مغایرت در اعلام هزینه{f' ({who})' if who else ''} :"]
    if date_errs:
        parts.append("📅 تاریخ پیام احتمالاً اشتباه است:\n" + "\n".join(f"• {e}" for e in date_errs))
    if split_errs:
        parts.append("🧮 جمع تفکیک با مجموع یکی نیست:\n" + "\n".join(f"• {_friendly(e)}" for e in split_errs))
    if other:
        parts.append("\n".join(f"• {e}" for e in other))
    if total is not None:
        parts.append(f"فعلاً مجموع {total:,} تومان ثبت شد. لطفاً پیام را اصلاح کنید تا عدد درست جایگزین شود. ممنون")
    else:
        parts.append("لطفاً پیام را اصلاح کنید. ممنون")
    return "\n\n".join(parts)


_SPLIT_ERR = re.compile(r"جمع (\S+) \(([\d,]+)\) ≠ مجموع \(([\d,]+)\)")


def _friendly(error: str) -> str:
    """«جمع محصولات (555,150,000) ≠ مجموع (557,150,000)» → جمله با اختلاف."""
    m = _SPLIT_ERR.fullmatch(error)
    if not m:
        return error
    name, part, total = m.group(1), int(m.group(2).replace(",", "")), int(m.group(3).replace(",", ""))
    gap = total - part
    return (f"جمع {name} {part:,} است ولی مجموع {total:,} اعلام شده "
            f"({abs(gap):,} {'کمتر' if gap > 0 else 'بیشتر'})")


def fixed_text(supervisor=None) -> str:
    return "✅ ممنون، اصلاح شد و عدد جدید ثبت شد."


def reply_to_mismatches(conn, export_since: str | None = None) -> int:
    """ریپلای در گروه به پیام‌های needs_review (یک بار برای هر مجموعه خطا) و اعلام اصلاح بعد از ویرایش.
    پیام‌های دیده‌شده توسط ربات؛ پیام‌های اکسپورت (تاریخچه) فقط با `export_since` (تاریخ گزارش از این روز
    به بعد) جواب می‌گیرند، یا اگر قبلاً دستی ریپلای خورده باشند (فخاری ۰۸/۰۶، تا «برطرف شد» بعد از ادیت برود)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ChatId, MessageId, Status, Errors, Supervisor, ReportDate, Total FROM dbo.ADV_TG_MSG
        WHERE (Source = 'bot' OR RepliedAt IS NOT NULL OR (? IS NOT NULL AND ReportDate >= ?)) AND (
            (Status = 'needs_review' AND (RepliedErrors IS NULL OR RepliedErrors <> Errors))
            OR (Status IN ('loaded', 'superseded') AND RepliedErrors IS NOT NULL))""", export_since, export_since)
    sent = 0
    for chat_id, msg_id, status, errors, supervisor, date, total in cur.fetchall():
        if status == "needs_review":
            text = mismatch_text(errors.split(" | "), supervisor, date, total)
            replied = errors
        else:
            text = fixed_text(supervisor)
            replied = None
        _api("sendMessage", chat_id=chat_id, text=text,
             reply_parameters={"message_id": msg_id, "allow_sending_without_reply": True})
        cur.execute("UPDATE dbo.ADV_TG_MSG SET RepliedErrors = ?, RepliedAt = ? WHERE ChatId = ? AND MessageId = ?",
                    replied, datetime.now(), chat_id, msg_id)
        conn.commit()
        sent += 1
    return sent


def _insert_rows(cur, p, source, manager, now):
    y, m, d = (int(x) for x in p.date.split("/"))
    greg = jdatetime.date(y, m, d).togregorian()
    month = p.date[:7]
    note = "OK" if p.ok else " | ".join(p.errors)[:400]
    agencies, products = balanced(p)
    detail_table, detail_col = DETAIL_TABLE[p.company]
    for agency, amount in agencies.items():
        cur.execute(
            f"INSERT INTO dbo.[{AGN_TABLE[p.company]}] ([تاریخ], [تاریخ میلادی], [ماه], [سرپرست], [مدیر], [بستر],"
            " [عاملیت], [مبلغ], [مغایرت], [ردیف اکسل], [_SourceFile], [_LoadedAt]) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            p.date, greg, month, p.supervisor, manager, p.platform or UNKNOWN, agency, amount, note, 0, source, now)
    for product, amount in products.items():
        cur.execute(
            f"INSERT INTO dbo.[{detail_table}] ([تاریخ], [تاریخ میلادی], [ماه], [سرپرست], [مدیر], [{detail_col}],"
            " [مبلغ], [توضیحات], [ردیف اکسل], [_SourceFile], [_LoadedAt]) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            p.date, greg, month, p.supervisor, manager, product, amount, None if p.ok else note, 0, source, now)


def main() -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / "ad_cost_telegram.log", encoding="utf-8")])
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", help="فایل result.json اکسپورت Telegram Desktop")
    ap.add_argument("--reply-export-since", help="ریپلای مغایرت به پیام‌های اکسپورت هم، از این تاریخ گزارش (1405/08/06)")
    args = ap.parse_args()
    conn = get_connection(SQL_SERVER, SQL_DATABASE)
    try:
        conn.cursor().execute(DDL)
        conn.commit()
        if args.export and Path(args.export).is_dir():
            logger.info("export (html): %d messages stored", import_export_html(conn, Path(args.export)))
        elif args.export:
            logger.info("export: %d messages stored", import_export(conn, Path(args.export)))
        else:
            logger.info("bot: %d messages stored", fetch_bot_updates(conn))
        logger.info("processed: %s", process_messages(conn))
        if not args.export or args.reply_export_since:
            logger.info("mismatch replies sent: %d", reply_to_mismatches(conn, args.reply_export_since))
        from ad_cost.export_excel import export_all  # export_excel خودش از این ماژول import می‌کند
        for path in export_all(conn):
            logger.info("excel: %s", path)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
