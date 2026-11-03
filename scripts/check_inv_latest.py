"""
Acceptance check for db/inv_latest.py (DB_STRUCTURE.md §6): Agg_Vosool_Daily / INV_Latest_* must equal the app's
own reports.vosool() exactly, for the same moment's data. Read-only (SELECT only), no LLM calls.

    python scripts/check_inv_latest.py [1405/06/01:1405/06/31 1405/07/05 ...]

Imports the app («دستیار داده») from DATA_AGENT_DIR, so this script deliberately does not import the robot's
`db` package (the app has its own db.py).
"""

import os
import random
import sys
import time
from pathlib import Path

APP = Path(os.environ.get("DATA_AGENT_DIR", r"E:\دستیار داده"))
os.chdir(APP)
sys.path.insert(0, str(APP))

import jdatetime  # noqa: E402
import pyodbc  # noqa: E402

import reports  # noqa: E402  (the app's module)

CONN = ("DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=Mitra_sarkhosh;"
        "Trusted_Connection=yes;Encrypt=no")
CODES = {"5040": "54", "همکده": "HK"}

# app column -> (Agg condition, value) ; value "amt" = SUM(amt)/1e7 rounded 1, "n" = count
AGG = {
    reports.C_TOTAL: ("1 = 1", "amt_vosool"),
    reports.C_TEAM: ("grp IN ('team', 'test')", "amt_vosool"),
    reports.C_KART: ("grp = 'team' AND kart = 1", "amt_vosool"),
    reports.C_DASTI: ("grp = 'team' AND kart = 0", "amt_vosool"),
    reports.C_TEST: ("grp = 'test'", "amt_vosool"),
    reports.C_SITE: ("grp = 'site'", "amt_vosool"),
    reports.C_NONE: ("grp = 'none'", "amt_vosool"),
    "تعداد فاکتور وصول‌شده": ("1 = 1", "n_vosool"),
    reports.C_RESEND: ("1 = 1", "amt_support"),
    reports.N_RESEND: ("1 = 1", "n_support"),
    reports.N_CANCEL: ("1 = 1", "n_cancel"), reports.C_CANCEL: ("1 = 1", "amt_cancel"),
    reports.N_REJECT: ("1 = 1", "n_reject"), reports.C_REJECT: ("1 = 1", "amt_reject"),
    reports.N_UNPAID: ("1 = 1", "n_unpaid"), reports.C_UNPAID: ("1 = 1", "amt_unpaid"),
}


def from_tables(cur, company, d0, d1):
    code = CODES[company]
    out = {}
    for col, (cond, field) in AGG.items():
        cur.execute(f"SELECT ISNULL(SUM(CAST({field} AS bigint)), 0) FROM dbo.Agg_Vosool_Daily "
                    f"WHERE company = ? AND vos_day BETWEEN ? AND ? AND {cond}", code, d0, d1)
        v = cur.fetchone()[0]
        out[col] = round(v / 1e7, 1) if field.startswith("amt") else int(v)
    sep = "/" if code == "54" else "-"
    lo, hi = d0.replace("/", sep), d1.replace("/", sep) + "z"
    cur.execute(f"SELECT COUNT(*), ISNULL(SUM(amt_rial), 0) FROM dbo.INV_Latest_{code} "
                "WHERE is_counted = 1 AND t_vos IS NULL AND registered_at >= ? AND registered_at < ?", lo, hi)
    n, amt = cur.fetchone()
    out[reports.N_NODATE], out[reports.C_NODATE] = int(n), round(amt / 1e7, 1)
    return out


def from_app(company, d0, d1):
    r = reports.vosool(company, d0, d1)
    if not r.ok:
        raise RuntimeError(r.error)
    row = r.df.iloc[0]
    return {col: (0 if row.get(col) is None or row.get(col) != row.get(col) else row.get(col)) for col in
            list(AGG) + [reports.N_NODATE, reports.C_NODATE]}


def periods(args):
    if args:
        return [tuple(a.split(":")) if ":" in a else (a, a) for a in args]
    random.seed(1405)
    first = jdatetime.date(1405, 1, 1)
    days = [(first + jdatetime.timedelta(days=random.randrange(215))).strftime("%Y/%m/%d") for _ in range(8)]
    return [("1405/06/01", "1405/06/31")] + [(d, d) for d in sorted(days)]


def main():
    cur = pyodbc.connect(CONN).cursor()
    bad = 0
    for d0, d1 in periods(sys.argv[1:]):
        for company in CODES:
            t = time.time()
            app = from_app(company, d0, d1)
            t_app = time.time() - t
            t = time.time()
            tab = from_tables(cur, company, d0, d1)
            t_tab = time.time() - t
            diff = {k: (app[k], tab[k]) for k in app if abs(float(app[k]) - float(tab[k])) > 1e-9}
            bad += bool(diff)
            print(f"{'OK ' if not diff else 'DIFF'} {company:6} {d0}–{d1}  total {tab[reports.C_TOTAL]:>12,.1f}"
                  f"  app {t_app:5.1f}s  tables {t_tab:4.2f}s", flush=True)
            for k, (a, b) in diff.items():
                print(f"      {k}: app={a} tables={b}")
    print("ALL EQUAL" if not bad else f"{bad} period(s) differ")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
