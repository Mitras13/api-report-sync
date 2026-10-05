"""
Loads the Parquet files under raw_data/<REPORT_CODE>/<COMPANY_CODE>/ into SQL
Server, one table per (report_code, company_code) combination (e.g. the
table `INV_SAL_54` holds every file under raw_data/INV_SAL/54/).

Re-running is safe: every file that has already been loaded is recorded in
the `dbo.LoadedFiles` tracking table and is skipped on the next run. Each
data table also carries a `_SourceFile` column, and any rows previously
loaded from a given file are deleted before that file is re-inserted, so a
retried or interrupted run can never leave duplicate rows behind.

Column names come straight from the source data (Persian headers included).
Table schemas are created from the first file seen for that table and are
widened automatically (BIGINT -> FLOAT -> NVARCHAR(MAX)) if a later file
needs a wider type for an existing column, or a brand-new column appears.
"""

import logging
import math

import pandas as pd
import pyodbc

logger = logging.getLogger(__name__)

TRACKING_TABLE = "LoadedFiles"

# Schema-widening order for a given column: BIGINT -> FLOAT -> NVARCHAR(MAX).
# BIT is only ever used when a column's very first file is boolean; any
# conflict with another type widens straight to NVARCHAR(MAX).
_TYPE_RANK = {"BIT": 0, "BIGINT": 1, "FLOAT": 2, "NVARCHAR(MAX)": 3}


def get_connection(server: str, database: str) -> pyodbc.Connection:
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={database};"
        "Trusted_Connection=yes;"
        "Encrypt=no;"
    )
    conn = pyodbc.connect(conn_str, timeout=10)
    conn.autocommit = False
    return conn


def ensure_database(server: str, database: str) -> None:
    """Create the target database on `server` if it doesn't already exist."""
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};"
        "DATABASE=master;"
        "Trusted_Connection=yes;"
        "Encrypt=no;"
    )
    conn = pyodbc.connect(conn_str, timeout=10, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT database_id FROM sys.databases WHERE name = ?", database)
        if cur.fetchone() is None:
            logger.info("Database %r does not exist, creating it", database)
            cur.execute(f"CREATE DATABASE [{_escape_ident(database)}]")
    finally:
        conn.close()


def _escape_ident(name: str) -> str:
    return name.replace("]", "]]")


def quote_ident(name: str) -> str:
    return f"[{_escape_ident(name)}]"


def ensure_tracking_table(conn: pyodbc.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables WHERE name = ?
        )
        BEGIN
            CREATE TABLE dbo.[%s] (
                RelativePath NVARCHAR(400) NOT NULL PRIMARY KEY,
                TableName NVARCHAR(200) NOT NULL,
                [RowCount] BIGINT NOT NULL,
                LoadedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
            )
        END
        """
        % _escape_ident(TRACKING_TABLE),
        TRACKING_TABLE,
    )
    conn.commit()


def is_file_loaded(conn: pyodbc.Connection, relative_path: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        f"SELECT 1 FROM dbo.{quote_ident(TRACKING_TABLE)} WHERE RelativePath = ?",
        relative_path,
    )
    return cur.fetchone() is not None


def mark_file_loaded(
    conn: pyodbc.Connection, relative_path: str, table_name: str, row_count: int
) -> None:
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO dbo.{quote_ident(TRACKING_TABLE)}
            (RelativePath, TableName, [RowCount])
        VALUES (?, ?, ?)
        """,
        relative_path,
        table_name,
        row_count,
    )
    conn.commit()


def unmark_file_loaded(conn: pyodbc.Connection, relative_path: str) -> None:
    cur = conn.cursor()
    cur.execute(
        f"DELETE FROM dbo.{quote_ident(TRACKING_TABLE)} WHERE RelativePath = ?",
        relative_path,
    )
    conn.commit()


def _sql_type_for_dtype(dtype) -> str:
    if pd.api.types.is_bool_dtype(dtype):
        return "BIT"
    if pd.api.types.is_integer_dtype(dtype):
        return "BIGINT"
    if pd.api.types.is_float_dtype(dtype):
        return "FLOAT"
    return "NVARCHAR(MAX)"


def table_exists(conn: pyodbc.Connection, table_name: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sys.tables WHERE name = ?", table_name)
    return cur.fetchone() is not None


def get_table_column_types(conn: pyodbc.Connection, table_name: str) -> dict:
    """Return {column_name: sql_type} for an existing table."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.name, t.name, c.max_length
        FROM sys.columns c
        JOIN sys.types t ON c.user_type_id = t.user_type_id
        WHERE c.object_id = OBJECT_ID('dbo.' + QUOTENAME(?))
        """,
        table_name,
    )
    result = {}
    for col_name, sql_type, max_length in cur.fetchall():
        sql_type = sql_type.upper()
        if sql_type in ("NVARCHAR", "VARCHAR") and max_length == -1:
            result[col_name] = "NVARCHAR(MAX)"
        elif sql_type in ("BIGINT", "INT", "SMALLINT", "TINYINT"):
            result[col_name] = "BIGINT"
        elif sql_type in ("FLOAT", "REAL", "DECIMAL", "NUMERIC"):
            result[col_name] = "FLOAT"
        elif sql_type == "BIT":
            result[col_name] = "BIT"
        else:
            result[col_name] = "NVARCHAR(MAX)"
    return result


def create_table(conn: pyodbc.Connection, table_name: str, df: pd.DataFrame) -> None:
    columns_sql = ",\n            ".join(
        f"{quote_ident(col)} {_sql_type_for_dtype(df[col].dtype)} NULL"
        for col in df.columns
    )
    cur = conn.cursor()
    cur.execute(
        f"CREATE TABLE dbo.{quote_ident(table_name)} (\n"
        f"            [_SourceFile] NVARCHAR(400) NOT NULL,\n"
        f"            {columns_sql}\n"
        f"        )"
    )
    cur.execute(
        f"CREATE INDEX {quote_ident('IX_' + table_name + '_SourceFile')} "
        f"ON dbo.{quote_ident(table_name)} ([_SourceFile])"
    )
    conn.commit()
    logger.info("Created table dbo.%s with %d columns", table_name, len(df.columns))


def reconcile_schema(conn: pyodbc.Connection, table_name: str, df: pd.DataFrame) -> dict:
    """
    Make sure every column in `df` exists in the table with a wide-enough
    type. Returns {column_name: sql_type} for the table's current schema
    (after any ALTER TABLE statements have been applied).
    """
    existing = get_table_column_types(conn, table_name)
    cur = conn.cursor()

    for col in df.columns:
        needed_type = _sql_type_for_dtype(df[col].dtype)

        if col not in existing:
            cur.execute(
                f"ALTER TABLE dbo.{quote_ident(table_name)} "
                f"ADD {quote_ident(col)} {needed_type} NULL"
            )
            existing[col] = needed_type
            logger.info(
                "Table %s | added new column %r (%s)", table_name, col, needed_type
            )
            continue

        current_type = existing[col]
        if _TYPE_RANK[needed_type] > _TYPE_RANK[current_type]:
            cur.execute(
                f"ALTER TABLE dbo.{quote_ident(table_name)} "
                f"ALTER COLUMN {quote_ident(col)} {needed_type} NULL"
            )
            logger.info(
                "Table %s | widened column %r from %s to %s",
                table_name,
                col,
                current_type,
                needed_type,
            )
            existing[col] = needed_type

    conn.commit()
    return existing


def _column_values(series: pd.Series, target_type: str) -> list:
    dtype = series.dtype

    if target_type == "BIGINT" and pd.api.types.is_integer_dtype(dtype):
        return series.tolist()

    if target_type == "BIT" and pd.api.types.is_bool_dtype(dtype):
        return series.tolist()

    if target_type == "FLOAT":
        return [None if pd.isna(v) else float(v) for v in series.tolist()]

    if target_type == "BIGINT":
        # e.g. table column is BIGINT but this file produced floats/objects.
        return [None if pd.isna(v) else int(v) for v in series.tolist()]

    if target_type == "BIT":
        return [None if pd.isna(v) else bool(v) for v in series.tolist()]

    # NVARCHAR(MAX)
    values = []
    for v in series.tolist():
        if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v):
            values.append(None)
        else:
            values.append(str(v))
    return values


def delete_rows_for_file(conn: pyodbc.Connection, table_name: str, relative_path: str) -> None:
    """Remove any rows already loaded from this file (safety net against
    duplicate inserts from a retried or previously interrupted run)."""
    cur = conn.cursor()
    cur.execute(
        f"DELETE FROM dbo.{quote_ident(table_name)} WHERE [_SourceFile] = ?",
        relative_path,
    )


def insert_dataframe(
    conn: pyodbc.Connection,
    table_name: str,
    df: pd.DataFrame,
    column_types: dict,
    relative_path: str,
    batch_size: int = 2000,
) -> int:
    if df.empty:
        return 0

    columns = list(df.columns)
    col_lists = [_column_values(df[col], column_types[col]) for col in columns]
    rows = list(zip([relative_path] * len(df), *col_lists))

    all_columns = ["_SourceFile"] + columns
    placeholders = ", ".join("?" for _ in all_columns)
    col_idents = ", ".join(quote_ident(c) for c in all_columns)
    insert_sql = (
        f"INSERT INTO dbo.{quote_ident(table_name)} ({col_idents}) "
        f"VALUES ({placeholders})"
    )

    cur = conn.cursor()
    cur.fast_executemany = True

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        cur.executemany(insert_sql, batch)

    conn.commit()
    return len(rows)


def load_dataframe_into_table(
    conn: pyodbc.Connection, table_name: str, df: pd.DataFrame, relative_path: str
) -> int:
    if not table_exists(conn, table_name):
        create_table(conn, table_name, df)

    column_types = reconcile_schema(conn, table_name, df)
    delete_rows_for_file(conn, table_name, relative_path)
    return insert_dataframe(conn, table_name, df, column_types, relative_path)
