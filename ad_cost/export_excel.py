"""
خروجی اکسل هزینه‌ی تبلیغات از دیتابیس (ADV_AGN_* و ADV_PRD_54 / ADV_TOP_HK)، یک فایل برای هر شرکت.

هر بار که ربات اجرا می‌شود (ad_cost/telegram_loader.py) این فایل‌ها از نو ساخته می‌شوند:
- «روزانه»: تاریخ × سرپرست (جمع عاملیت‌ها) + جمع روز.
- «عاملیت» و «محصول» (همکده: «موضوع»): ردیف‌های جدول، با ستون «توضیحات» برای اعلام‌هایی که مغایرت
  داشته‌اند و هنوز اصلاح نشده‌اند (با ادیت سرپرست، دفعه‌ی بعد خودش پاک می‌شود).
اگر فایل در اکسل باز باشد (قفل)، نسخه با پسوند زمان ذخیره می‌شود.

اجرا:  python -m ad_cost.export_excel
"""
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from ad_cost.telegram_loader import AGN_TABLE, DETAIL_TABLE, SOURCE_PREFIX, SQL_DATABASE, SQL_SERVER
from db.sql_loader import get_connection

OUT_DIR = Path(r"E:\هزینه تبلیغات")
FILE_NAME = {"54": "هزینه_تبلیغات_5040.xlsx", "HK": "هزینه_تبلیغات_همکده.xlsx"}
NOTE_PREFIX = "مغایرت داشته، اصلاح نشده: "

logger = logging.getLogger("ad_cost.excel")


def _read(conn, table: str) -> pd.DataFrame:
    df = pd.read_sql(f"SELECT * FROM dbo.[{table}]", conn)
    df["منبع"] = df["_SourceFile"].map(lambda s: "تلگرام" if s.startswith(SOURCE_PREFIX) else "اکسل")
    return df.drop(columns=["ردیف اکسل", "_LoadedAt"]).sort_values(["تاریخ", "سرپرست"], kind="stable")


def _note(df: pd.DataFrame, col: str) -> pd.Series:
    """توضیح برای ردیف‌های تلگرامِ خطادار (ستون مغایرت/توضیحات = متن خطا)."""
    bad = (df["منبع"] == "تلگرام") & df[col].notna() & (df[col] != "OK")
    return df[col].where(bad).map(lambda e: NOTE_PREFIX + e if isinstance(e, str) else None)


def build(conn, company: str) -> Path:
    detail_table, detail_col = DETAIL_TABLE[company]
    agn = _read(conn, AGN_TABLE[company])
    det = _read(conn, detail_table)
    agn["توضیحات"] = _note(agn, "مغایرت")
    det["توضیحات"] = _note(det, "توضیحات")

    daily = agn.pivot_table(index="تاریخ", columns="سرپرست", values="مبلغ", aggfunc="sum")
    daily.insert(0, "جمع روز", daily.sum(axis=1))
    daily = daily.reset_index()

    path = OUT_DIR / FILE_NAME[company]
    try:
        writer = pd.ExcelWriter(path, engine="openpyxl")
    except PermissionError:
        path = path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M}{path.suffix}")
        logger.warning("excel file is open; writing %s", path)
        writer = pd.ExcelWriter(path, engine="openpyxl")
    with writer:
        daily.to_excel(writer, sheet_name="روزانه", index=False)
        agn.drop(columns=["_SourceFile"]).to_excel(writer, sheet_name="عاملیت", index=False)
        det.drop(columns=["_SourceFile"]).to_excel(writer, sheet_name=detail_col, index=False)
        for ws in writer.book.worksheets:
            ws.sheet_view.rightToLeft = True
            ws.freeze_panes = "B2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = 14
            for row in ws.iter_rows(min_row=2):
                for c in row:
                    if isinstance(c.value, (int, float)) and abs(c.value) > 9999:
                        c.number_format = "#,##0"
    return path


def export_all(conn) -> list:
    return [build(conn, co) for co in AGN_TABLE]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = get_connection(SQL_SERVER, SQL_DATABASE)
    try:
        for p in export_all(conn):
            logger.info("excel: %s", p)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
