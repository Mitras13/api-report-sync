"""جایگزینی دانلود دوباره‌ی یک بازه (db/sql_loader.py) با یک اتصال ساختگی که LoadedFiles و جدول داده را در حافظه نگه می‌دارد."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import sql_loader as L  # noqa: E402

OLD = "SaleR/54/54_SaleR_14050330000000_14050330235959_14050618103953.parquet"
NEW = "SaleR/54/54_SaleR_14050330000000_14050330235959_14050618113206.parquet"
OTHER_DAY = "SaleR/54/54_SaleR_14050329000000_14050329235959_14050618103900.parquet"
HALF_1 = "SaleR/HK/HK_SaleR_14031230000000_14031230123130_14050603133824.parquet"
HALF_2 = "SaleR/HK/HK_SaleR_14031230123130_14031230235959_14050603134615.parquet"


class FakeCursor:
    def __init__(self, db):
        self.db, self.rows = db, []

    def execute(self, sql, *params):
        sql = " ".join(sql.split())
        if sql.startswith("SELECT RelativePath, [RowCount]"):
            table, pattern = params
            rx = re.compile("^" + re.escape(pattern).replace(re.escape("!_") + re.escape("%"), "_.*")
                            .replace(re.escape("!_"), "_") + "$")
            self.rows = [(p, n) for p, (t, n) in self.db.loaded.items() if t == table and rx.match(p)]
        elif sql.startswith("DELETE FROM dbo.[SaleR_54] WHERE [_SourceFile]") or sql.startswith(
                "DELETE FROM dbo.[SaleR_HK] WHERE [_SourceFile]"):
            self.db.rows = [r for r in self.db.rows if r != params[0]]
        elif sql.startswith("UPDATE dbo.[LoadedFiles] SET [RowCount] = 0"):
            t, _ = self.db.loaded[params[0]]
            self.db.loaded[params[0]] = (t, 0)
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self):
        self.loaded = {}   # RelativePath -> (TableName, RowCount)
        self.rows = []     # [_SourceFile] of data rows

    def cursor(self):
        return FakeCursor(self)

    def load(self, path, table, n):
        self.loaded[path] = (table, n)
        self.rows += [path] * n


def test_split_range():
    assert L.split_range(NEW) == ("SaleR/54/54_SaleR_14050330000000_14050330235959", "14050618113206")
    assert L.split_range("SaleR/54/odd_name.parquet") == (None, None)


def test_newer_download_replaces_older():
    c = FakeConn()
    c.load(OLD, "SaleR_54", 3)
    c.load(OTHER_DAY, "SaleR_54", 2)
    assert L.supersede_older_versions(c, "SaleR_54", NEW) == [OLD]
    assert OLD not in c.rows and c.rows.count(OTHER_DAY) == 2      # روز دیگر دست نخورد
    assert c.loaded[OLD] == ("SaleR_54", 0)                          # در LoadedFiles می‌ماند → دوباره بار نمی‌شود


def test_older_download_after_newer_is_detected():
    c = FakeConn()
    c.load(NEW, "SaleR_54", 3)
    assert L.newer_version_loaded(c, "SaleR_54", OLD) == NEW
    assert L.newer_version_loaded(c, "SaleR_54", NEW) is None


def test_two_halves_of_a_day_are_not_duplicates():
    c = FakeConn()
    c.load(HALF_1, "SaleR_HK", 4)
    assert L.supersede_older_versions(c, "SaleR_HK", HALF_2) == []
    assert c.rows.count(HALF_1) == 4


def test_already_superseded_not_deleted_twice():
    c = FakeConn()
    c.loaded[OLD] = ("SaleR_54", 0)
    assert L.supersede_older_versions(c, "SaleR_54", NEW) == []


def test_like_escape():
    assert L._like_escape("a_b%c[d!e") == "a!_b!%c![d!!e"
