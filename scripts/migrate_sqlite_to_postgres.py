#!/usr/bin/env python3
"""One-time migration: copy all data from SQLite to PostgreSQL.

Usage (inside the Docker container or on the host):

    python scripts/migrate_sqlite_to_postgres.py \
        --sqlite /workspace/deathstar/deathstar.db \
        --postgres postgresql://deathstar:deathstar@postgres:5432/deathstar

Or using environment variables:

    DEATHSTAR_SQLITE_PATH=/workspace/deathstar/deathstar.db \
    DEATHSTAR_DATABASE_URL=postgresql://deathstar:deathstar@postgres:5432/deathstar \
    python scripts/migrate_sqlite_to_postgres.py

Add --dry-run to preview without writing.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras


TABLES = [
    "conversations",
    "messages",
    "memories",
    "feedback",
    "usage_log",
    "message_queue",
    "branch_prs",
    "conversation_branches",
]

# Tables where SQLite uses INTEGER 0/1 for booleans that Postgres expects as BOOLEAN
BOOL_COLUMNS = {
    "branch_prs": {"draft"},
}

# usage_log has an auto-increment id — reset the Postgres sequence after insert
SEQUENCE_TABLES = {
    "usage_log": "usage_log_id_seq",
}


def migrate(sqlite_path: str, postgres_url: str, dry_run: bool = False) -> None:
    print(f"[migrate] SQLite:   {sqlite_path}")
    print(f"[migrate] Postgres: {postgres_url.split('@')[0]}@***")
    print(f"[migrate] Dry run:  {dry_run}")
    print()

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    # Connect to Postgres
    pg_conn = psycopg2.connect(postgres_url)
    pg_cur = pg_conn.cursor()

    total_rows = 0

    for table in TABLES:
        # Check if table exists in SQLite
        exists = sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not exists:
            print(f"  [skip] {table} — not in SQLite (added in later version)")
            continue

        rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        if not rows:
            print(f"  [skip] {table} — empty")
            continue

        columns = [desc[0] for desc in sqlite_conn.execute(f"SELECT * FROM {table} LIMIT 1").description]  # noqa: S608
        bool_cols = BOOL_COLUMNS.get(table, set())

        # Check if Postgres already has data
        pg_cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        pg_count = pg_cur.fetchone()[0]
        if pg_count > 0:
            print(f"  [skip] {table} — Postgres already has {pg_count} rows (not overwriting)")
            continue

        if dry_run:
            print(f"  [dry-run] {table} — would insert {len(rows)} rows")
            total_rows += len(rows)
            continue

        # Batch insert (quote column names to handle Postgres reserved words like "user")
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(f'"{c}"' for c in columns)
        insert_sql = f'INSERT INTO {table} ({col_names}) VALUES ({placeholders})'  # noqa: S608

        batch = []
        for row in rows:
            values = []
            for col in columns:
                val = row[col]
                # Convert SQLite integer booleans to Python bools for Postgres
                if col in bool_cols:
                    val = bool(val)
                values.append(val)
            batch.append(tuple(values))

        psycopg2.extras.execute_batch(pg_cur, insert_sql, batch, page_size=500)
        print(f"  [done] {table} — {len(rows)} rows")
        total_rows += len(rows)

    # Reset sequences for auto-increment tables
    for table, seq_name in SEQUENCE_TABLES.items():
        if not dry_run:
            pg_cur.execute(f"SELECT MAX(id) FROM {table}")  # noqa: S608
            max_id = pg_cur.fetchone()[0]
            if max_id is not None:
                pg_cur.execute(f"SELECT setval('{seq_name}', %s)", (max_id,))
                print(f"  [seq] {table} — reset {seq_name} to {max_id}")

    if not dry_run:
        pg_conn.commit()
        print(f"\n[migrate] Done — {total_rows} total rows migrated.")

        # Rename SQLite file so we don't accidentally re-migrate
        backup_name = f"{sqlite_path}.migrated.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        try:
            os.rename(sqlite_path, backup_name)
            print(f"[migrate] Renamed SQLite file to {backup_name}")
        except OSError as exc:
            print(f"[migrate] Warning: could not rename SQLite file: {exc}")
    else:
        print(f"\n[dry-run] Would migrate {total_rows} total rows.")

    pg_cur.close()
    pg_conn.close()
    sqlite_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate DeathStar data from SQLite to PostgreSQL")
    parser.add_argument(
        "--sqlite",
        default=os.getenv("DEATHSTAR_SQLITE_PATH", "/workspace/deathstar/deathstar.db"),
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--postgres",
        default=os.getenv("DEATHSTAR_DATABASE_URL", "postgresql://deathstar:deathstar@postgres:5432/deathstar"),
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without writing",
    )
    args = parser.parse_args()

    if not os.path.exists(args.sqlite):
        print(f"[error] SQLite file not found: {args.sqlite}")
        sys.exit(1)

    migrate(args.sqlite, args.postgres, args.dry_run)


if __name__ == "__main__":
    main()
