"""
Loads every Parquet file under raw_data/ into SQL Server.

One table is created per (report_code, company_code) folder, e.g.:

    raw_data/INV_SAL/54/*.parquet -> table dbo.INV_SAL_54
    raw_data/INV_SAL/HK/*.parquet -> table dbo.INV_SAL_HK
    raw_data/VP/54/*.parquet      -> table dbo.VP_54
    raw_data/VP/HK/*.parquet      -> table dbo.VP_HK

Already-loaded files are tracked in dbo.LoadedFiles, so re-running this
script only loads files that were added since the last run.

Only one instance of this script may run at a time (enforced via a lock
file) since two concurrent runs writing to the same tables will race each
other and corrupt the tracking table.

Run:

    python load_raw_data_to_sql.py
"""

import logging
import os

import pandas as pd

from downloaders.downloader_core import RAW_DATA_ROOT, configure_logging
from db.sql_loader import (
    ensure_database,
    get_connection,
    ensure_tracking_table,
    is_file_loaded,
    mark_file_loaded,
    load_dataframe_into_table,
)

SQL_SERVER = "localhost"
SQL_DATABASE = "Mitra_sarkhosh"

LOCK_PATH = RAW_DATA_ROOT.parent / ".load_raw_data_to_sql.lock"


def acquire_lock():
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"Another run of this script appears to be in progress "
            f"(lock file exists: {LOCK_PATH}). If you're sure no other run "
            f"is active (e.g. it crashed without cleaning up), delete that "
            f"file and try again."
        )
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))


def release_lock():
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def iter_parquet_files():
    """Yield (report_code, company_code, table_name, file_path) for every
    Parquet file under raw_data/<report_code>/<company_code>/, sorted so
    files are always loaded in the same order."""
    for report_dir in sorted(p for p in RAW_DATA_ROOT.iterdir() if p.is_dir()):
        for company_dir in sorted(p for p in report_dir.iterdir() if p.is_dir()):
            table_name = f"{report_dir.name}_{company_dir.name}"
            for file_path in sorted(company_dir.glob("*.parquet")):
                yield report_dir.name, company_dir.name, table_name, file_path


def main():
    configure_logging()
    logger = logging.getLogger(__name__)

    acquire_lock()
    try:
        _run(logger)
    finally:
        release_lock()


def _run(logger):
    logger.info("=" * 70)
    logger.info("SQL Server load started | server=%s | database=%s", SQL_SERVER, SQL_DATABASE)
    logger.info("=" * 70)

    ensure_database(SQL_SERVER, SQL_DATABASE)
    conn = get_connection(SQL_SERVER, SQL_DATABASE)
    ensure_tracking_table(conn)

    total_files = 0
    loaded_files = 0
    skipped_files = 0
    failed_files = 0
    rows_per_table = {}

    try:
        for report_code, company_code, table_name, file_path in iter_parquet_files():
            total_files += 1
            relative_path = str(file_path.relative_to(RAW_DATA_ROOT)).replace("\\", "/")

            if is_file_loaded(conn, relative_path):
                skipped_files += 1
                continue

            try:
                df = pd.read_parquet(file_path)
                row_count = load_dataframe_into_table(conn, table_name, df, relative_path)
                mark_file_loaded(conn, relative_path, table_name, row_count)

                loaded_files += 1
                rows_per_table[table_name] = rows_per_table.get(table_name, 0) + row_count

                logger.info(
                    "%s | loaded %s -> %d rows", table_name, relative_path, row_count
                )

            except Exception:
                failed_files += 1
                conn.rollback()
                logger.exception("%s | FAILED to load %s", table_name, relative_path)
                continue
    finally:
        conn.close()

    logger.info("=" * 70)
    logger.info(
        "SQL Server load finished | total=%d | loaded=%d | skipped=%d | failed=%d",
        total_files,
        loaded_files,
        skipped_files,
        failed_files,
    )
    for table_name, row_count in sorted(rows_per_table.items()):
        logger.info("  %-14s | rows inserted this run=%d", table_name, row_count)
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
