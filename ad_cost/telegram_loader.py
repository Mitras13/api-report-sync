"""
خواندن پیام‌های گروه «اعلام هزینه تبلیغات» و لود آن‌ها در ADV_AGN_<CO> / ADV_PRD_<CO>.

دو منبع پیام، هر دو اول به‌صورت خام در dbo.ADV_TG_MSG ذخیره می‌شوند:
- ربات (`@API_analizgozareshatbot`, توکن در tokens/telegram_bot.txt) با getUpdates. تلگرام
  آپدیت‌ها را فقط ۲۴ ساعت نگه می‌دارد، پس این باید حداقل روزی یک بار (ترجیحاً ساعتی) اجرا شود.
  ربات فقط پیام‌های بعد از عضویتش را می‌بیند و باید ادمین گروه باشد (privacy mode).
- اکسپورت JSON از Telegram Desktop (`--export result.json`) برای تاریخچه‌ی قبل از ربات.

بعد هر پیام با ad_cost/telegram_parser.py پارس می‌شود. برای هر (شرکت، تاریخ، سرپرست، بستر)
فقط آخرین پیام سالم حساب می‌شود (پیام اصلاحیه یا تکرار در اکسپورت و ربات دو بار شمرده نمی‌شود).
ردیف‌ها با `_SourceFile = 'telegram:<chat_id>:<message_id>'` نوشته می‌شوند و
scripts/load_ad_cost.py این ردیف‌ها را دست نمی‌زند.
تاریخ‌های قبل از TELEGRAM_FROM از اکسل می‌آیند و از تلگرام لود نمی‌شوند.

وضعیت هر پیام در ADV_TG_MSG.[Status]:
  loaded / needs_review (جمع نمی‌خواند یا مبلغ بدفرم؛ [Errors] را ببین) / superseded (پیام
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
import time
from datetime import datetime, timezone
from pathlib import Path

import jdatetime
import requests

from ad_cost.telegram_parser import parse_message
from db.sql_loader import get_connection

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / "tokens" / "telegram_bot.txt"
SQL_SERVER = "localhost"
SQL_DATABASE = "Mitra_sarkhosh"
CHAT_TITLE_KEYWORD = "اعلام هزینه"
TELEGRAM_FROM = "1405/08/09"  # روزهای قبل از این از اکسل می‌آیند
SOURCE_PREFIX = "telegram:"

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
"""


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


def _upsert_message(cur, chat_id, message_id, title, sent_at, edited_at, sender, text, source):
    cur.execute("SELECT EditedAt, [Text] FROM dbo.ADV_TG_MSG WHERE ChatId = ? AND MessageId = ?", chat_id, message_id)
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO dbo.ADV_TG_MSG (ChatId, MessageId, ChatTitle, SentAt, EditedAt, Sender, [Text], Source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            chat_id, message_id, title, sent_at, edited_at, sender, text, source)
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
                                _sender(m.get("from", {})), text, "bot")
                stored += 1
            offset = u["update_id"] + 1
        # آفست فقط بعد از ذخیره‌ی پیام‌ها جلو می‌رود؛ اگر commit نشود، تلگرام دوباره می‌فرستد.
        cur.execute("DELETE FROM dbo.ADV_TG_STATE; INSERT INTO dbo.ADV_TG_STATE VALUES (?)", offset - 1)
        conn.commit()
    return stored


def import_export(conn, path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    cur = conn.cursor()
    stored = 0
    for m in data.get("messages", []):
        if m.get("type") != "message":
            continue
        raw = m.get("text")
        text = raw if isinstance(raw, str) else "".join(p if isinstance(p, str) else p.get("text", "") for p in raw or [])
        if not text.strip():
            continue
        # اکسپورت شناسه‌ی سوپرگروه را بدون پیشوند -100 می‌دهد؛ ربات با آن.
        chat_id = int(data["id"])
        if data.get("type", "").endswith("supergroup") and chat_id > 0:
            chat_id = int(f"-100{chat_id}")
        edited = m.get("edited")
        _upsert_message(cur, chat_id, m["id"], data.get("name"), datetime.fromisoformat(m["date"]),
                        datetime.fromisoformat(edited) if edited else None, m.get("from"), text, "export")
        stored += 1
    conn.commit()
    return stored


def _manager_lookup(cur, company: str) -> dict:
    """آخرین مدیر شناخته‌شده‌ی هر سرپرست (از ردیف‌های اکسل)."""
    cur.execute(f"""
        SELECT [سرپرست], [مدیر] FROM (
            SELECT [سرپرست], [مدیر], ROW_NUMBER() OVER (PARTITION BY [سرپرست] ORDER BY [تاریخ] DESC) rn
            FROM dbo.[ADV_PRD_{company}] WHERE [مدیر] IS NOT NULL) x WHERE rn = 1""")
    return dict(cur.fetchall())


def process_messages(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT ChatId, MessageId, [Text], COALESCE(EditedAt, SentAt) FROM dbo.ADV_TG_MSG")
    msgs = cur.fetchall()
    parsed = {}
    for chat_id, msg_id, text, at in msgs:
        p = parse_message(text)
        if p.total is None and not p.agencies and not p.products:
            status = "ignored"
        elif p.date and p.date < TELEGRAM_FROM:
            status = "before_cutoff"
        else:
            status = "loaded" if p.ok else "needs_review"
        parsed[(chat_id, msg_id)] = (p, status, at)

    # برای هر (شرکت، تاریخ، سرپرست، بستر) فقط آخرین پیام سالم.
    latest = {}
    for key, (p, status, at) in parsed.items():
        if status == "loaded":
            k = (p.company, p.date, p.supervisor, p.platform)
            if k not in latest or parsed[latest[k]][2] < at:
                latest[k] = key
    winners = set(latest.values())

    counts = {}
    managers = {}
    now = datetime.now()
    for (chat_id, msg_id), (p, status, at) in parsed.items():
        if status == "loaded" and (chat_id, msg_id) not in winners:
            status = "superseded"
        counts[status] = counts.get(status, 0) + 1
        source = f"{SOURCE_PREFIX}{chat_id}:{msg_id}"
        for co in ("54", "HK"):
            for t in (f"ADV_AGN_{co}", f"ADV_PRD_{co}"):
                cur.execute("SELECT OBJECT_ID(?, 'U')", f"dbo.{t}")
                if cur.fetchone()[0] is not None:
                    cur.execute(f"DELETE FROM dbo.[{t}] WHERE [_SourceFile] = ?", source)
        if status == "loaded":
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


def reply_to_mismatches(conn) -> int:
    """ریپلای در گروه به پیام‌های needs_review (یک بار برای هر مجموعه خطا) و اعلام اصلاح بعد از ویرایش.
    فقط پیام‌های دیده‌شده توسط ربات؛ پیام‌های اکسپورت (تاریخچه) جواب نمی‌گیرند."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ChatId, MessageId, Status, Errors, Supervisor, ReportDate FROM dbo.ADV_TG_MSG
        WHERE Source = 'bot' AND (
            (Status = 'needs_review' AND (RepliedErrors IS NULL OR RepliedErrors <> Errors))
            OR (Status IN ('loaded', 'superseded') AND RepliedErrors IS NOT NULL))""")
    sent = 0
    for chat_id, msg_id, status, errors, supervisor, date in cur.fetchall():
        if status == "needs_review":
            who = " ".join(x for x in [supervisor, date] if x)
            lines = "\n".join(f"• {e}" for e in errors.split(" | "))
            text = f"⚠️ مغایرت در اعلام هزینه{f' ({who})' if who else ''}:\n{lines}\n\nلطفاً پیام را ویرایش کنید."
            replied = errors
        else:
            text = "✅ مغایرت برطرف شد و هزینه ثبت شد."
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
    for agency, amount in p.agencies.items():
        cur.execute(
            f"INSERT INTO dbo.[ADV_AGN_{p.company}] ([تاریخ], [تاریخ میلادی], [ماه], [سرپرست], [مدیر], [بستر],"
            " [عاملیت], [مبلغ], [مغایرت], [ردیف اکسل], [_SourceFile], [_LoadedAt]) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            p.date, greg, month, p.supervisor, manager, p.platform, agency, amount, "OK", 0, source, now)
    for product, amount in p.products.items():
        if amount:
            cur.execute(
                f"INSERT INTO dbo.[ADV_PRD_{p.company}] ([تاریخ], [تاریخ میلادی], [ماه], [سرپرست], [مدیر], [محصول],"
                " [مبلغ], [توضیحات], [ردیف اکسل], [_SourceFile], [_LoadedAt]) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                p.date, greg, month, p.supervisor, manager, product, amount, None, 0, source, now)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", help="فایل result.json اکسپورت Telegram Desktop")
    args = ap.parse_args()
    conn = get_connection(SQL_SERVER, SQL_DATABASE)
    try:
        conn.cursor().execute(DDL)
        conn.commit()
        if args.export:
            logger.info("export: %d messages stored", import_export(conn, Path(args.export)))
        else:
            logger.info("bot: %d messages stored", fetch_bot_updates(conn))
        logger.info("processed: %s", process_messages(conn))
        if not args.export:
            logger.info("mismatch replies sent: %d", reply_to_mismatches(conn))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
