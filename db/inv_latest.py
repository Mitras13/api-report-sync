"""
Ready-made invoice tables for the «دستیار داده» app (spec: E:\\دستیار داده\\docs\\DB_STRUCTURE.md).

    dbo.INV_Latest_54 / dbo.INV_Latest_HK   one row per invoice = its latest version (highest _SourceFile),
                                            with collection day, group, team, support/excluded flags pre-computed
    dbo.Agg_Vosool_Daily                    daily sums per (company, day, grp, kart, team_key, manager)
    dbo.Org_Team                            every team label ever seen, first/last registration
    dbo.INV_Latest_Meta                     logic_version + watermark per company

The business rules are the app's (reports.vosool_sql, reports.is_support, reports.excluded_sql,
invoice_policy.collection_sql, org.team_key_sql / org.flag); this module re-implements them in T-SQL and
must change whenever they change. Two safety nets keep the app from reading wrong numbers:

  * logic_version = "<VOSOOL_VERSION> | <invoice_policy.VERSION> | support:<hash of support lists>" uses the
    versions *implemented here*. When the app bumps a version, the strings no longer match and the app keeps
    using its own raw SQL until this module is updated.
  * Support lists are data, not logic: they are read from the app's source (ast, no import) on every refresh,
    so a list change in the app is picked up automatically (and triggers a full rebuild).

Refresh is incremental: invoices of files loaded since the last refresh (dbo.LoadedFiles.LoadedAt watermark),
plus invoices whose latest version points at a file that is no longer loaded (retired/superseded), are
recomputed; Agg_Vosool_Daily is recomputed for their old and new collection days.
"""

import ast
import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_AGENT_DIR = Path(os.environ.get("DATA_AGENT_DIR", r"E:\دستیار داده"))

# Versions of the app logic implemented below (reports.VOSOOL_VERSION, invoice_policy.VERSION).
VOSOOL_VERSION = "vosool-logic 1405-08-05-paid-confirmed"
INVOICE_POLICY_VERSION = "invoice-state-2026-10-27-paid-confirmed-v2"

# Fallback copies of reports.py lists (1405/08/12), used only if the app source can't be read.
DEFAULT_RULES = {
    "SUPPORT_54": ["مسعود قنبری(مدیریت ارسال)", "مینا میرحسینی", "افسانه جوادی", "محدثه نبی", "مژگان رضا نژاد",
                   "مژگان رضا نژاد(پشتیبانی)", "امیر مهدی باکوچی", "آیدا حمیدی فر", "مهسا محمدی",
                   "فرنوش جانبار آینه ده"],
    "NOT_SUPPORT_54": ["طلیعه عزیزیان", "سیده شراره آقاسید هاشم", "هانیه شعله ور مبرهن", "لیلا رضایی"],
    "SUPPORT_HK": ["ادمین پشتیبانی همکده", "مهدیه خوش خبر"],
    "TEST_SUPERVISOR": "سوناز دادخواه",
}

# Same as reports._INV in the app.
COMPANIES = {
    "54": dict(raw="INV_SAL_54", latest="INV_Latest_54", id="[سریال فاکتور]", fin="تایید مالی",
               pay="[وضعیت پرداخت]", card="[تاریخ ثبت اطلاعات پرداختی]", other="[تاریخ وضعیت مالی]",
               sup="[سرپرست سازنده فاکتور]", supervisor="[سوپروایزران سازنده فاکتور]",
               manager="[مدیر سازنده فاکتور]", mob="[شماره مشتری] % CAST(10000000000 AS bigint)",
               fb="[فاکتور برگشتی]", support="SUPPORT_54"),
    "HK": dict(raw="INV_SAL_HK", latest="INV_Latest_HK", id="[شناسه فاکتور]", fin="تایید شده",
               pay="CAST(NULL AS nvarchar(100))", card="[زمان ثبت اطلاعات واریزی]",
               other="[زمان بررسی اطلاعات واریزی]", sup="[سرپرستان ثبت کننده فاکتور]",
               supervisor="[سوپروایزران ثبت کننده فاکتور]", manager="[مدیر فروش]",
               mob="TRY_CAST(RIGHT([شماره مشتری], 10) AS bigint)", fb="CAST(NULL AS float)",
               support="SUPPORT_HK"),
}

LATEST_COLUMNS = ("invoice_id, source_file, registered_at, amt_rial, st, fin, pay, pay_type, t_vos, vos_day, grp, "
                  "kart, creator, supervisor, lead_label, team_key, manager, mob, returned_flag, is_counted, "
                  "is_support, excluded_kind")


# ------------------------------------------------------------------ rules

def _literal_assignments(path: Path, names) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    found[target.id] = ast.literal_eval(node.value)
    return found


def load_rules() -> dict:
    """Support lists from the app's reports.py; warns when the app's logic version moved past this module."""
    rules = dict(DEFAULT_RULES)
    try:
        app = _literal_assignments(DATA_AGENT_DIR / "reports.py",
                                   set(DEFAULT_RULES) | {"VOSOOL_VERSION"})
        policy = _literal_assignments(DATA_AGENT_DIR / "invoice_policy.py", {"VERSION"})
    except (OSError, SyntaxError, ValueError):
        logger.warning("INV_Latest | could not read rules from %s, using built-in copies", DATA_AGENT_DIR,
                       exc_info=True)
        return rules
    for key in DEFAULT_RULES:
        if key in app:
            rules[key] = list(app[key]) if isinstance(app[key], (tuple, list)) else app[key]
    if app.get("VOSOOL_VERSION") != VOSOOL_VERSION or policy.get("VERSION") != INVOICE_POLICY_VERSION:
        logger.warning(
            "INV_Latest | app logic is %r / %r but this module implements %r / %r — the app will ignore "
            "INV_Latest_* until db/inv_latest.py is updated",
            app.get("VOSOOL_VERSION"), policy.get("VERSION"), VOSOOL_VERSION, INVOICE_POLICY_VERSION)
    return rules


def support_hash(rules: dict) -> str:
    payload = json.dumps({k: rules[k] for k in DEFAULT_RULES}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def logic_version(rules: dict) -> str:
    """The app computes the same string from its own constants and reads INV_Latest_* only on an exact match."""
    return f"{VOSOOL_VERSION} | {INVOICE_POLICY_VERSION} | support:{support_hash(rules)}"


# ------------------------------------------------------------------ SQL pieces (copies of the app's helpers)

def _nlist(values) -> str:
    return ", ".join("N'" + str(v).replace("'", "''") + "'" for v in values) or "N''"


def state_sql(column: str) -> str:
    """invoice_policy.state_sql"""
    text = column
    for char in (8203, 8204, 8205, 65279, 9, 10, 13, 160, 8239):
        text = f"REPLACE({text}, NCHAR({char}), N'')"
    return f"REPLACE({text}, N' ', N'')"


def team_key_sql(col: str) -> str:
    """org.team_key_sql"""
    k0 = f"LTRIM(RTRIM(REPLACE({col}, N'*', N'')))"
    k1 = (f"(CASE WHEN {k0} COLLATE Latin1_General_BIN LIKE N'%[A-E]+' THEN LEFT({k0}, LEN({k0}) - 1) "
          f"ELSE {k0} END)")
    k2 = (f"(CASE WHEN {k1} COLLATE Latin1_General_BIN LIKE N'%[A-E]' THEN RTRIM(LEFT({k1}, LEN({k1}) - 1)) "
          f"ELSE {k1} END)")
    return f"ISNULL(NULLIF({k2}, N''), {k0})"


def _collection_sql(company: str) -> str:
    """invoice_policy.collection_sql, on the columns of the CTE below."""
    if company == "HK":
        return "d.st = N'پرداخت شده'"
    return "d.pay = N'پرداخت شده' AND d.st <> N'لغو شده' AND a.st_norm <> N'ردشده'"


def _support_sql(company: str, rules: dict) -> str:
    """reports.is_support (NOT_SUPPORT_54 applies to both companies; the third rule only to 5040)."""
    cr = "a.cr"
    no_paren = f"(CASE WHEN CHARINDEX(N'(', {cr}) > 0 THEN RTRIM(LEFT({cr}, CHARINDEX(N'(', {cr}) - 1)) ELSE {cr} END)"
    third = ""
    if company == "54":
        third = (f"\n        WHEN d.sup IS NULL AND {cr} NOT LIKE N'%سایت%'"
                 f" AND PATINDEX(N'%[A-Za-z]%', {cr} COLLATE Latin1_General_BIN) = 0"
                 f" AND {cr} NOT LIKE N'%تست%' AND {cr} NOT LIKE N'%موزش%' AND ISNULL(d.fb, 0) = 1 THEN 1")
    return (f"CASE WHEN {no_paren} IN ({_nlist(rules['NOT_SUPPORT_54'])}) THEN 0\n"
            f"        WHEN {cr} IN ({_nlist(rules[COMPANIES[company]['support']])}) OR {cr} LIKE N'%پشتیبان%' THEN 1"
            f"{third}\n        ELSE 0 END")


def latest_select(company: str, rules: dict, where: str = "") -> str:
    """SELECT of LATEST_COLUMNS: the latest version (rn = 1) of every invoice in the raw table [matching where]."""
    c = COMPANIES[company]
    fin = c["fin"]
    rej = f"(d.fin LIKE N'رد%' OR a.st_norm = N'ردشده')"
    # derived table, not a CTE, so the result can follow INSERT INTO directly
    d = f"""(
    SELECT {c['id']} AS invoice_id, _SourceFile AS sf, [تاریخ ثبت] AS reg, [مبلغ فاکتور] AS amt,
           [وضعیت فاکتور] AS st, [وضعیت مالی] AS fin, {c['pay']} AS pay, [نوع پرداخت] AS pay_type,
           CASE [نوع پرداخت] WHEN N'آنلاین' THEN [تاریخ پرداخت] WHEN N'کارت به کارت' THEN {c['card']}
                ELSE {c['other']} END AS t_vos,
           [ثبت کننده] AS creator_raw, {c['sup']} AS sup, {c['supervisor']} AS supervisor,
           {c['manager']} AS manager, {c['mob']} AS mob, {c['fb']} AS fb, [نوع ثبت فاکتور] AS reg_type,
           ROW_NUMBER() OVER (PARTITION BY {c['id']} ORDER BY _SourceFile DESC) AS rn
    FROM dbo.{c['raw']}
    WHERE {c['id']} IS NOT NULL{(' AND ' + where) if where else ''}
) d"""
    return f"""SELECT d.invoice_id, d.sf, LEFT(d.reg, 19), ISNULL(d.amt, 0), d.st, d.fin, d.pay, d.pay_type,
       LEFT(d.t_vos, 19), REPLACE(LEFT(d.t_vos, 10), '-', '/'),
       CASE WHEN d.creator_raw LIKE N'%سایت%' THEN 'site' WHEN d.sup IS NULL THEN 'none'
            WHEN d.sup = N'{rules['TEST_SUPERVISOR']}' THEN 'test' ELSE 'team' END,
       CASE WHEN d.reg_type = N'کارتابلی' THEN 1 ELSE 0 END,
       a.creator, d.supervisor, a.lab, CASE WHEN a.lab IS NULL THEN NULL ELSE {team_key_sql('a.lab')} END,
       LTRIM(RTRIM(d.manager)), d.mob, TRY_CONVERT(tinyint, d.fb), c.is_counted, sp.is_support,
       CASE WHEN c.rej = 1 THEN 'r'
            WHEN c.rej = 0 AND d.fin = N'{fin}' AND d.st = N'لغو شده' THEN 'c'
            WHEN c.rej = 0 AND d.fin = N'{fin}' AND ISNULL(d.st, N'') <> N'لغو شده' AND c.is_counted = 0 THEN 'u' END
FROM {d}
CROSS APPLY (SELECT LTRIM(RTRIM(d.creator_raw)) AS creator, ISNULL(LTRIM(RTRIM(d.creator_raw)), N'') AS cr,
                    NULLIF(LTRIM(RTRIM(d.sup)), N'') AS lab, {state_sql('d.st')} AS st_norm) a
-- rej is NULL when unknown (NULL status), like NOT (...) in reports.excluded_sql
CROSS APPLY (SELECT CASE WHEN d.fin = N'{fin}' AND {_collection_sql(company)} THEN 1 ELSE 0 END AS is_counted,
                    CASE WHEN {rej} THEN 1 WHEN NOT {rej} THEN 0 END AS rej) c
CROSS APPLY (SELECT {_support_sql(company, rules)} AS is_support) sp
WHERE d.rn = 1"""


# ------------------------------------------------------------------ schema

def _latest_ddl(company: str) -> str:
    t = COMPANIES[company]["latest"]
    return f"""
IF OBJECT_ID(N'dbo.{t}', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.{t} (
        invoice_id     bigint         NOT NULL CONSTRAINT PK_{t} PRIMARY KEY,
        source_file    nvarchar(400)  NOT NULL,
        registered_at  nvarchar(19)   NULL,
        amt_rial       bigint         NOT NULL,
        st             nvarchar(100)  NULL,
        fin            nvarchar(100)  NULL,
        pay            nvarchar(100)  NULL,
        pay_type       nvarchar(100)  NULL,
        t_vos          nvarchar(19)   NULL,
        vos_day        nchar(10)      NULL,
        grp            varchar(4)     NOT NULL,
        kart           bit            NOT NULL,
        creator        nvarchar(400)  NULL,
        supervisor     nvarchar(400)  NULL,
        lead_label     nvarchar(200)  NULL,
        team_key       nvarchar(200)  NULL,
        manager        nvarchar(200)  NULL,
        mob            bigint         NULL,
        returned_flag  tinyint        NULL,
        is_counted     bit            NOT NULL,
        is_support     bit            NOT NULL,
        excluded_kind  char(1)        NULL,
        updated_at     datetime2(0)   NOT NULL CONSTRAINT DF_{t}_upd DEFAULT SYSDATETIME()
    ) WITH (DATA_COMPRESSION = PAGE);
    CREATE INDEX IX_{t}_day ON dbo.{t} (vos_day)
        INCLUDE (amt_rial, grp, kart, is_counted, is_support, excluded_kind, team_key, manager, creator, supervisor)
        WITH (DATA_COMPRESSION = PAGE);
    CREATE INDEX IX_{t}_team_day ON dbo.{t} (team_key, vos_day)
        INCLUDE (amt_rial, is_counted, is_support, lead_label, source_file) WITH (DATA_COMPRESSION = PAGE);
    CREATE INDEX IX_{t}_reg ON dbo.{t} (registered_at) INCLUDE (is_counted, t_vos, amt_rial)
        WITH (DATA_COMPRESSION = PAGE);
    CREATE INDEX IX_{t}_mob ON dbo.{t} (mob) INCLUDE (vos_day, amt_rial, is_counted)
        WITH (DATA_COMPRESSION = PAGE);
    CREATE INDEX IX_{t}_file ON dbo.{t} (source_file) WITH (DATA_COMPRESSION = PAGE);
END"""


SHARED_DDL = """
IF OBJECT_ID(N'dbo.INV_Latest_Meta', N'U') IS NULL
    CREATE TABLE dbo.INV_Latest_Meta (
        company        char(2)        NOT NULL PRIMARY KEY,
        logic_version  nvarchar(200)  NOT NULL,
        refreshed_at   datetime2(0)   NOT NULL,
        loaded_upto    datetime2(7)   NULL    -- max dbo.LoadedFiles.LoadedAt already applied
    );
IF OBJECT_ID(N'dbo.Org_Team', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Org_Team (
        company     char(2)        NOT NULL,
        lead_label  nvarchar(200)  NOT NULL,
        manager     nvarchar(200)  NOT NULL,
        team_key    nvarchar(200)  NOT NULL,
        kind        nvarchar(30)   NULL,
        first_reg   nvarchar(19)   NOT NULL,
        last_reg    nvarchar(19)   NOT NULL,
        last_file   nvarchar(400)  NOT NULL,
        n_invoices  int            NOT NULL,
        CONSTRAINT PK_Org_Team PRIMARY KEY (company, lead_label, manager)
    );
    CREATE INDEX IX_Org_Team_key ON dbo.Org_Team (company, team_key, last_reg)
        INCLUDE (lead_label, first_reg, manager, n_invoices);
END
IF OBJECT_ID(N'dbo.Agg_Vosool_Daily', N'U') IS NULL
    CREATE TABLE dbo.Agg_Vosool_Daily (
        company      char(2)        NOT NULL,
        vos_day      nchar(10)      NOT NULL,
        grp          varchar(4)     NOT NULL,
        kart         bit            NOT NULL,
        team_key     nvarchar(200)  NOT NULL,
        manager      nvarchar(200)  NOT NULL,
        n_vosool     int            NOT NULL,
        amt_vosool   bigint         NOT NULL,
        n_support    int            NOT NULL,
        amt_support  bigint         NOT NULL,
        n_cancel int NOT NULL, amt_cancel bigint NOT NULL,
        n_reject int NOT NULL, amt_reject bigint NOT NULL,
        n_unpaid int NOT NULL, amt_unpaid bigint NOT NULL,
        CONSTRAINT PK_Agg_Vosool_Daily PRIMARY KEY (company, vos_day, grp, kart, team_key, manager)
    );
-- incremental refresh looks up invoices by id in the raw table (INV_SAL_54 already has this index)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID(N'dbo.INV_SAL_HK') AND name = N'IX_INV_SAL_HK_id')
    CREATE INDEX IX_INV_SAL_HK_id ON dbo.INV_SAL_HK ([شناسه فاکتور]);
"""


def ensure_schema(conn) -> None:
    cur = conn.cursor()
    cur.execute(SHARED_DDL)
    for company in COMPANIES:
        cur.execute(_latest_ddl(company))
    conn.commit()


# ------------------------------------------------------------------ refresh

def _agg_insert(company: str, days_filter: str) -> str:
    t = COMPANIES[company]["latest"]
    vos = "is_counted = 1 AND is_support = 0"
    sup = "is_counted = 1 AND is_support = 1"

    def pair(cond):
        return (f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN {cond} THEN amt_rial ELSE CAST(0 AS bigint) END)")

    return f"""INSERT INTO dbo.Agg_Vosool_Daily (company, vos_day, grp, kart, team_key, manager, n_vosool, amt_vosool,
    n_support, amt_support, n_cancel, amt_cancel, n_reject, amt_reject, n_unpaid, amt_unpaid)
SELECT '{company}', vos_day, grp, kart, ISNULL(team_key, N''), ISNULL(manager, N''),
       {pair(vos)}, {pair(sup)}, {pair("excluded_kind = 'c'")}, {pair("excluded_kind = 'r'")},
       {pair("excluded_kind = 'u'")}
FROM dbo.{t}
WHERE vos_day IS NOT NULL{days_filter}
GROUP BY vos_day, grp, kart, ISNULL(team_key, N''), ISNULL(manager, N'')
HAVING SUM(CASE WHEN is_counted = 1 OR excluded_kind IS NOT NULL THEN 1 ELSE 0 END) > 0"""


def flag(label, manager, rules) -> str:
    """org.flag"""
    s = str(label or "")
    if s.strip() == rules["TEST_SUPERVISOR"] or "آموزش" in s:
        return "تست و آموزش"
    if "در انتظار" in s:
        return "در انتظار فعالیت"
    if "تست" in s or str(manager or "").strip() == "تست":
        return "تست"
    return None


def _rebuild_org_team(cur, company: str, rules: dict) -> None:
    t = COMPANIES[company]["latest"]
    cur.execute(f"""SELECT lead_label, ISNULL(manager, N''), MAX(team_key), ISNULL(MIN(registered_at), N''),
       ISNULL(MAX(registered_at), N''), MAX(source_file), COUNT(*)
FROM dbo.{t} WHERE lead_label IS NOT NULL GROUP BY lead_label, ISNULL(manager, N'')""")
    rows = [(company, lab, mgr, key, flag(lab, mgr, rules), a, b, f, n)
            for lab, mgr, key, a, b, f, n in cur.fetchall()]
    cur.execute("DELETE FROM dbo.Org_Team WHERE company = ?", company)
    if rows:
        cur.executemany("INSERT INTO dbo.Org_Team (company, lead_label, manager, team_key, kind, first_reg, last_reg, "
                        "last_file, n_invoices) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _write_meta(cur, company: str, version: str, loaded_upto) -> None:
    cur.execute("""MERGE dbo.INV_Latest_Meta AS t
USING (SELECT ? AS company, ? AS logic_version, CAST(? AS datetime2(7)) AS loaded_upto) AS s ON t.company = s.company
WHEN MATCHED THEN UPDATE SET logic_version = s.logic_version, refreshed_at = SYSDATETIME(), loaded_upto = s.loaded_upto
WHEN NOT MATCHED THEN INSERT (company, logic_version, refreshed_at, loaded_upto)
     VALUES (s.company, s.logic_version, SYSDATETIME(), s.loaded_upto);""", company, version, loaded_upto)


def refresh_company(conn, company: str, rules: dict, full: bool = False) -> dict:
    """Bring INV_Latest_<company>, its Agg_Vosool_Daily days, Org_Team and Meta up to date, in one transaction."""
    c = COMPANIES[company]
    t = c["latest"]
    version = logic_version(rules)
    cur = conn.cursor()
    # watermarks travel as text: a Python datetime drops datetime2(7)'s last digit, and the app compares
    # loaded_upto >= MAX(LoadedAt) to decide whether the tables are fresh
    cur.execute("SELECT logic_version, CONVERT(varchar(27), loaded_upto, 121) FROM dbo.INV_Latest_Meta "
                "WHERE company = ?", company)
    meta = cur.fetchone()
    cur.execute("SELECT CONVERT(varchar(27), MAX(LoadedAt), 121) FROM dbo.LoadedFiles WHERE TableName = ?",
                c["raw"])
    upto = cur.fetchone()[0]
    if meta is None or meta[0] != version or meta[1] is None:
        full = True

    try:
        if full:
            logger.info("INV_Latest | %s full rebuild (%s)", company, version)
            cur.execute(f"TRUNCATE TABLE dbo.{t}")
            cur.execute(f"INSERT INTO dbo.{t} WITH (TABLOCK) ({LATEST_COLUMNS})\n{latest_select(company, rules)}")
            cur.execute("DELETE FROM dbo.Agg_Vosool_Daily WHERE company = ?", company)
            cur.execute(_agg_insert(company, ""))
            changed = None
        else:
            cur.execute("DROP TABLE IF EXISTS #files; DROP TABLE IF EXISTS #ids; DROP TABLE IF EXISTS #days;")
            cur.execute("CREATE TABLE #files (f nvarchar(400) COLLATE DATABASE_DEFAULT PRIMARY KEY);"
                        "CREATE TABLE #ids (id bigint PRIMARY KEY);"
                        "CREATE TABLE #days (d nchar(10) COLLATE DATABASE_DEFAULT PRIMARY KEY);")
            cur.execute("""INSERT INTO #files SELECT RelativePath FROM dbo.LoadedFiles
WHERE TableName = ? AND [RowCount] > 0 AND LoadedAt > CAST(? AS datetime2(7)) AND LoadedAt <= CAST(? AS datetime2(7))""",
                        c["raw"], meta[1], upto)
            # invoices in newly loaded files
            cur.execute(f"""INSERT INTO #ids SELECT DISTINCT {c['id']} FROM dbo.{c['raw']}
WHERE _SourceFile IN (SELECT f FROM #files) AND {c['id']} IS NOT NULL""")
            # invoices whose latest version came from a file that was retired or superseded since
            cur.execute(f"""INSERT INTO #ids SELECT l.invoice_id FROM dbo.{t} l
WHERE l.source_file IN (SELECT x.source_file FROM (SELECT DISTINCT source_file FROM dbo.{t}) x
                        WHERE NOT EXISTS (SELECT 1 FROM dbo.LoadedFiles f
                                          WHERE f.RelativePath = x.source_file AND f.[RowCount] > 0))
  AND NOT EXISTS (SELECT 1 FROM #ids i WHERE i.id = l.invoice_id)""")
            cur.execute("SELECT COUNT(*) FROM #ids")
            changed = cur.fetchone()[0]
            if changed:
                cur.execute(f"INSERT INTO #days SELECT DISTINCT vos_day FROM dbo.{t} "
                            "WHERE invoice_id IN (SELECT id FROM #ids) AND vos_day IS NOT NULL")
                cur.execute(f"DELETE FROM dbo.{t} WHERE invoice_id IN (SELECT id FROM #ids)")
                cur.execute(f"INSERT INTO dbo.{t} ({LATEST_COLUMNS})\n"
                            f"{latest_select(company, rules, c['id'] + ' IN (SELECT id FROM #ids)')}")
                cur.execute(f"""INSERT INTO #days SELECT DISTINCT l.vos_day FROM dbo.{t} l
WHERE l.invoice_id IN (SELECT id FROM #ids) AND l.vos_day IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM #days d WHERE d.d = l.vos_day)""")
                cur.execute("DELETE FROM dbo.Agg_Vosool_Daily WHERE company = ? AND vos_day IN (SELECT d FROM #days)",
                            company)
                cur.execute(_agg_insert(company, " AND vos_day IN (SELECT d FROM #days)"))
        if full or changed:
            _rebuild_org_team(cur, company, rules)
        _write_meta(cur, company, version, upto)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    logger.info("INV_Latest | %s %s", company, "rebuilt" if full else f"{changed} invoices refreshed")
    return {"company": company, "full": full, "changed": changed}


def refresh_all(conn, full: bool = False) -> list:
    ensure_schema(conn)
    rules = load_rules()
    return [refresh_company(conn, company, rules, full) for company in COMPANIES]
