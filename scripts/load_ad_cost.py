"""
لود اکسل «بودجه‌بندی تبلیغات» (هزینه‌ی روزانه‌ی تبلیغات هر سرپرست) به SQL Server.

اکسل دستی است (از واحد تبلیغات، نه API)، پس جدا از main.py / load_raw_data_to_sql.py
لود می‌شود. دو شیت داده‌ی خام دارد و هر کدام یک جدول می‌شود:

- شیت «عاملیت»  -> dbo.ADV_AGN_<CO>: هر ردیف = تاریخ × سرپرست × بستر × عاملیت × مبلغ
  (ستون «مغایرت» خودِ اکسل هم نگه داشته می‌شود).
- شیت «محصول»   -> dbo.ADV_PRD_<CO>: شیت پهن (یک ستون برای هر محصول) به شکل بلند
  (تاریخ × سرپرست × محصول × مبلغ) درمی‌آید؛ خانه‌های خالی/صفر/«-» حذف می‌شوند.
  اگر «جمع» یک ردیف از مجموع محصولاتش بیشتر باشد (مثلاً هزینه‌ی «باکس همه‌ی
  محصولات» که در توضیحات آمده)، اختلاف با محصول «تقسیم‌نشده» ثبت می‌شود تا جمع
  جدول با جمع اکسل یکی بماند. ردیف‌های عیناً تکراری (ورود دستی دوباره) یک بار شمرده می‌شوند.

جمع دو شیت در خودِ اکسل با هم برابر نیست (شیت «مغایرت» اکسل)؛ این اسکریپت چیزی را
اصلاح نمی‌کند، فقط عین منبع را لود می‌کند.

هر اجرا ردیف‌های اکسلیِ جدول آن شرکت را کامل جایگزین می‌کند (DELETE + INSERT در یک تراکنش)،
چون اکسل تجمعی است و هر نسخه‌ی جدیدش کل سال را دارد. ردیف‌های تلگرام (`_SourceFile` با پیشوند
`telegram:`) دست نمی‌خورند.

اجرا:
    python scripts/load_ad_cost.py "<مسیر اکسل>" --company 54
    python scripts/load_ad_cost.py "<مسیر اکسل>" --company 54 --dry-run
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

import jdatetime
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.sql_loader import get_connection  # noqa: E402

SQL_SERVER = "localhost"
SQL_DATABASE = "Mitra_sarkhosh"

UNALLOCATED_PRODUCT = "تقسیم‌نشده"
# ستون‌های غیرمحصول شیت «محصول»؛ هر ستون دیگر بین «سرپرست» و «جمع» یک محصول است.
PRODUCT_SHEET_META = {"ماه", "تاریخ", "سرپرست", "جمع", "تاریخ فرمت", "مدیر", "توضیحات"}


def jalali_to_gregorian(s: str):
    y, m, d = (int(x) for x in str(s).strip().split("/"))
    return jdatetime.date(y, m, d).togregorian()


def _amount(v):
    n = pd.to_numeric(v, errors="coerce")
    return None if pd.isna(n) else int(round(float(n)))


def read_agency(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="عاملیت", dtype=str)
    df = df[["تاریخ", "سرپرست", "بستر", "عاملیت", "مبلغ", "مغایرت"]].copy()
    df["ردیف اکسل"] = df.index + 2  # +1 هدر، +1 شروع از ۱
    df["مبلغ"] = df["مبلغ"].map(_amount)
    df = df[df["مبلغ"].notna()].astype({"مبلغ": "int64"})
    for c in ["سرپرست", "بستر", "عاملیت", "مغایرت"]:
        df[c] = df[c].where(df[c].notna(), None).map(lambda x: x.strip() if isinstance(x, str) else x)
    return df.reset_index(drop=True)


def read_product(path: Path) -> pd.DataFrame:
    wide = pd.read_excel(path, sheet_name="محصول", dtype=str)
    cols = list(wide.columns)
    products = [c for c in cols[cols.index("سرپرست") + 1: cols.index("جمع")] if c not in PRODUCT_SHEET_META]
    # ردیف تکراریِ ورود دستی (همان تاریخ، سرپرست و همه‌ی مبالغ؛ مدیر مهم نیست): آخری می‌ماند.
    key = ["تاریخ", "سرپرست", *products, "جمع"]
    dup = wide.duplicated(key, keep="last") & (pd.to_numeric(wide["جمع"], errors="coerce").fillna(0) != 0)
    for i, r in wide[dup].iterrows():
        print(f"dropped duplicate product row {i + 2}: {r['تاریخ']} {r['سرپرست']} جمع={r['جمع']} مدیر={r['مدیر']}")
    wide = wide[~dup]
    rows = []
    for i, r in wide.iterrows():
        base = {
            "تاریخ": r["تاریخ"],
            "سرپرست": str(r["سرپرست"]).strip(),
            "مدیر": None if pd.isna(r["مدیر"]) else str(r["مدیر"]).strip(),
            "توضیحات": None if pd.isna(r["توضیحات"]) else str(r["توضیحات"]).strip(),
            "ردیف اکسل": i + 2,
        }
        total = 0
        for p in products:
            amt = _amount(r[p])
            if amt:
                rows.append({**base, "محصول": str(p).strip(), "مبلغ": amt})
                total += amt
        row_sum = _amount(r["جمع"]) or 0
        if row_sum > total:
            rows.append({**base, "محصول": UNALLOCATED_PRODUCT, "مبلغ": row_sum - total})
    return pd.DataFrame(rows), products


def add_common(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df["تاریخ"] = df["تاریخ"].str.strip()
    df.insert(1, "تاریخ میلادی", df["تاریخ"].map(jalali_to_gregorian))
    df.insert(2, "ماه", df["تاریخ"].str.slice(0, 7))
    df["_SourceFile"] = source
    df["_LoadedAt"] = datetime.now()
    return df


AGN_DDL = """
CREATE TABLE dbo.[{t}] (
    [تاریخ] NVARCHAR(10) NOT NULL, [تاریخ میلادی] DATE NOT NULL, [ماه] NVARCHAR(7) NOT NULL,
    [سرپرست] NVARCHAR(100) NOT NULL, [مدیر] NVARCHAR(100) NULL,
    [بستر] NVARCHAR(100) NULL, [عاملیت] NVARCHAR(100) NULL,
    [مبلغ] BIGINT NOT NULL, [مغایرت] NVARCHAR(50) NULL,
    [ردیف اکسل] INT NOT NULL, [_SourceFile] NVARCHAR(400) NOT NULL, [_LoadedAt] DATETIME2(0) NOT NULL
)"""
PRD_DDL = """
CREATE TABLE dbo.[{t}] (
    [تاریخ] NVARCHAR(10) NOT NULL, [تاریخ میلادی] DATE NOT NULL, [ماه] NVARCHAR(7) NOT NULL,
    [سرپرست] NVARCHAR(100) NOT NULL, [مدیر] NVARCHAR(100) NULL,
    [محصول] NVARCHAR(100) NOT NULL, [مبلغ] BIGINT NOT NULL, [توضیحات] NVARCHAR(MAX) NULL,
    [ردیف اکسل] INT NOT NULL, [_SourceFile] NVARCHAR(400) NOT NULL, [_LoadedAt] DATETIME2(0) NOT NULL
)"""
AGN_COLS = ["تاریخ", "تاریخ میلادی", "ماه", "سرپرست", "مدیر", "بستر", "عاملیت", "مبلغ", "مغایرت",
            "ردیف اکسل", "_SourceFile", "_LoadedAt"]
PRD_COLS = ["تاریخ", "تاریخ میلادی", "ماه", "سرپرست", "مدیر", "محصول", "مبلغ", "توضیحات",
            "ردیف اکسل", "_SourceFile", "_LoadedAt"]


def replace_table(cur, table: str, ddl: str, cols: list, df: pd.DataFrame) -> None:
    cur.execute("SELECT OBJECT_ID(?, 'U')", f"dbo.{table}")
    if cur.fetchone()[0] is None:
        cur.execute(ddl.format(t=table))
    else:
        # ردیف‌های تلگرام (ad_cost/telegram_loader.py) مال این اکسل نیستند.
        cur.execute(f"DELETE FROM dbo.[{table}] WHERE [_SourceFile] NOT LIKE 'telegram:%'")
    col_sql = ", ".join(f"[{c}]" for c in cols)
    marks = ", ".join("?" for _ in cols)
    data = [tuple(None if pd.isna(v) else v for v in row) for row in df[cols].itertuples(index=False)]
    cur.fast_executemany = True
    cur.executemany(f"INSERT INTO dbo.[{table}] ({col_sql}) VALUES ({marks})", data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("excel")
    ap.add_argument("--company", required=True, choices=["54", "HK"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    path = Path(args.excel)
    source = path.name

    prd, products = read_product(path)
    prd = add_common(prd, source)
    agn = add_common(read_agency(path), source)
    # شیت «عاملیت» ستون مدیر ندارد؛ از شیت «محصول» (همان تاریخ و سرپرست) گرفته می‌شود.
    mgr = prd.dropna(subset=["مدیر"]).drop_duplicates(["تاریخ", "سرپرست"]).set_index(["تاریخ", "سرپرست"])["مدیر"]
    agn["مدیر"] = [mgr.get((d, s)) for d, s in zip(agn["تاریخ"], agn["سرپرست"])]

    print(f"products ({len(products)}): {', '.join(products)}")
    for name, df in [("agency", agn), ("product", prd)]:
        print(f"{name}: rows={len(df):,} sum={df['مبلغ'].sum():,} "
              f"range={df['تاریخ'].min()}..{df['تاریخ'].max()}")
    print(f"agency rows without manager: {agn['مدیر'].isna().sum()}")
    if args.dry_run:
        return

    conn = get_connection(SQL_SERVER, SQL_DATABASE)
    try:
        cur = conn.cursor()
        replace_table(cur, f"ADV_AGN_{args.company}", AGN_DDL, AGN_COLS, agn)
        replace_table(cur, f"ADV_PRD_{args.company}", PRD_DDL, PRD_COLS, prd)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("loaded.")


if __name__ == "__main__":
    main()
