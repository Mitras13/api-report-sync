"""
Build / refresh the ready-made invoice tables for «دستیار داده» (db/inv_latest.py).

    python scripts/build_inv_latest.py          # incremental (what main.py runs after every download)
    python scripts/build_inv_latest.py --full   # rebuild everything (first run, or after a logic change)

main.py does the incremental refresh itself; this script is for the first build and manual rebuilds.
"""

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from load_raw_data_to_sql import SQL_SERVER, SQL_DATABASE  # noqa: E402
from db.sql_loader import get_connection  # noqa: E402
from db.inv_latest import refresh_all  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    started = time.time()
    conn = get_connection(SQL_SERVER, SQL_DATABASE)
    try:
        for result in refresh_all(conn, full="--full" in sys.argv[1:]):
            logging.info("%s", result)
    finally:
        conn.close()
    logging.info("done in %.0f s", time.time() - started)


if __name__ == "__main__":
    main()
