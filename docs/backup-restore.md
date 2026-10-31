# PostgreSQL backup and restore

Back up from a trusted computer with PostgreSQL 17 client utilities (`pg_dump` and `pg_restore`) on PATH and this project's Python dependencies installed. Keep database credentials in `.env` or environment variables. Use Neon's direct connection URL with SSL, not a transaction pooler. Never commit database dumps.

## Backup

Set `DATABASE_URL` to the source database, then:

```powershell
.\.venv\Scripts\python scripts/db_backup.py backup artifacts/maintenance-2026-10-31.dump
```

Use a new filename for each backup. The script refuses to overwrite a file, creates a PostgreSQL custom archive, and passes credentials through the subprocess environment instead of command-line arguments. The archive includes accounts, password hashes, configuration, sessions, history and all application records, so store it with restricted access outside the repository and outside Render's ephemeral filesystem.

## Restore into a new empty database

Create a fresh PostgreSQL database with no public tables. Point `DATABASE_URL` to that target, not to the live source. Then:

```powershell
.\.venv\Scripts\python scripts/db_backup.py restore artifacts/maintenance-2026-10-31.dump --empty-database
.\.venv\Scripts\python manage.py migrate --check
.\.venv\Scripts\python manage.py check
```

Restore checks for existing tables and refuses a nonempty target. PostgreSQL restores in a single transaction with owner/ACL changes omitted. It does not drop or replace a live database. Use a client version at least as new as the database server version.

Validate row counts, representative machine histories, login behavior, report totals and primary-key sequence behavior before using a restored database. Restoring a backup also restores passwords and sessions from its timestamp; invalidate sessions and handle user password resets deliberately when recovering an actual deployment. Back up the source before changing a deployment's database URL.

The initial delivery verifies a local PostgreSQL custom-format dump restored into a separate empty database, comparing all public table counts and deterministic row-content hashes. Hosting-level recovery and an automated production backup schedule are outside the demonstration rollout.
