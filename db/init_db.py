"""Initialise the CityPulse SQLite database from schema.sql and seed.sql.

Usage:
    python db/init_db.py          # create if missing
    python db/init_db.py --reset  # delete and recreate
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Resolve paths relative to the project root (parent of db/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "citypulse.db"
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
SEED_PATH = PROJECT_ROOT / "db" / "seed.sql"


def init_db(reset: bool = False) -> Path:
    """Create the database from schema.sql + seed.sql.

    Args:
        reset: If True, delete an existing database first.

    Returns:
        The path to the created database file.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if reset and DB_PATH.exists():
        DB_PATH.unlink()
        # Also remove WAL/SHM sidecars if present
        for suffix in (".db-wal", ".db-shm"):
            sidecar = DB_PATH.with_suffix(suffix)
            if sidecar.exists():
                sidecar.unlink()
        logger.info("Deleted existing database at %s", DB_PATH)

    if DB_PATH.exists():
        logger.info("Database already exists at %s — skipping init (use --reset to recreate)", DB_PATH)
        return DB_PATH

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    seed_sql = SEED_PATH.read_text(encoding="utf-8")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript(schema_sql)
        logger.info("Schema applied.")
        conn.executescript(seed_sql)
        logger.info("Seed data inserted.")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
    finally:
        conn.close()

    logger.info("Database created at %s", DB_PATH)
    return DB_PATH


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Initialise the CityPulse database.")
    parser.add_argument("--reset", action="store_true", help="Delete and recreate the database.")
    args = parser.parse_args()
    try:
        init_db(reset=args.reset)
    except Exception as exc:
        logger.error("Failed to initialise database: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
