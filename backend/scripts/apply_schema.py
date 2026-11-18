"""Apply db/schema.sql (idempotent) to the database.

Usage (from backend/):
    python scripts/apply_schema.py                 # DATABASE_URL_DIRECT, else DATABASE_URL
    python scripts/apply_schema.py --url-env TEST_DATABASE_URL

Uses the direct (non-pooled) Neon URL when set: DDL is safer outside the pooler.
Never prints the connection string.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

BACKEND = Path(__file__).resolve().parents[1]
SCHEMA = BACKEND.parent / "db" / "schema.sql"
sys.path.insert(0, str(BACKEND))


def apply(url: str) -> list[str]:
    sql = SCHEMA.read_text(encoding="utf-8")
    with psycopg.connect(url, connect_timeout=30, prepare_threshold=None) as conn:
        conn.execute(sql)
        conn.commit()
        rows = conn.execute(
            "select table_name from information_schema.tables where table_schema = 'public' order by table_name"
        ).fetchall()
        ext = conn.execute("select extversion from pg_extension where extname = 'vector'").fetchone()
    print(f"pgvector installed: {ext[0] if ext else 'NO'}")
    return [r[0] for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url-env", help="name of the env var holding the URL")
    args = parser.parse_args()
    from app.config import get_settings

    settings = get_settings()
    if args.url_env:
        url = os.environ.get(args.url_env, "")
    else:
        url = settings.database_url_direct or settings.database_url
    if not url:
        print("ERROR: no database URL set (DATABASE_URL_DIRECT or DATABASE_URL)")
        return 2
    tables = apply(url)
    print(f"schema applied; tables: {', '.join(tables)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
