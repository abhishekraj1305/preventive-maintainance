"""PostgreSQL backup/restore helper. Credentials never enter process arguments.

Usage: python scripts/db_backup.py backup artifacts/demo.dump
       python scripts/db_backup.py restore artifacts/demo.dump --empty-database

Set DATABASE_URL; prepend the PostgreSQL bin directory to PATH.
Restore refuses any target with existing public tables.
"""

import argparse
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit, unquote, parse_qs

from dotenv import load_dotenv
import psycopg


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--empty-database", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql://")):
        parser.error("DATABASE_URL must point to PostgreSQL.")
    parts = urlsplit(url)
    env = os.environ.copy()
    env.update(
        PGHOST=parts.hostname or "",
        PGPORT=str(parts.port or 5432),
        PGDATABASE=unquote(parts.path.lstrip("/")),
        PGUSER=unquote(parts.username or ""),
        PGPASSWORD=unquote(parts.password or ""),
    )
    query = parse_qs(parts.query)
    if "sslmode" in query:
        env["PGSSLMODE"] = query["sslmode"][0]
    if args.action == "backup":
        if args.file.exists():
            parser.error("Backup file already exists; choose a new filename.")
        args.file.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", str(args.file)], env=env, check=True
        )
        print(f"Backup saved: {args.file}")
    else:
        if not args.empty_database:
            parser.error("Restore requires --empty-database and a new, empty target database.")
        with psycopg.connect(url) as connection:
            count = connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
            ).fetchone()[0]
        if count:
            parser.error("Target contains tables. Restore refused; create a fresh database.")
        subprocess.run(
            [
                "pg_restore",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "--single-transaction",
                "--dbname",
                env["PGDATABASE"],
                str(args.file),
            ],
            env=env,
            check=True,
        )
        print("Restore completed into an empty database.")


if __name__ == "__main__":
    main()
