# Upkeep — Preventive Maintenance & Breakdowns

A working Django application for one organization with several plants. Staff use individual user IDs and passwords on phones or PCs. Updates, PM approvals, countdowns, notifications and reports stay inside the application.

## Included

- Admin configuration and account resets; plant-scoped Operator, Technician and Approver memberships.
- Machine masters and archived history; multiple named, fixed-anchor PM schedules per machine.
- PM completion, rejection, resubmission and independent approval with an audit trail.
- Three-day reminders, due-today/overdue states, a persistent action banner and notification inbox.
- Breakdown reporting and restoration with distinct downtime and repair duration; daily operating hours, including zero-hour days.
- Daily, weekly, monthly and custom reports; PM compliance, downtime, MTTR and operating-hours-based MTBF.
- Validated Excel imports with a review step and atomic saving; filtered Excel exports.
- Secure sessions, CSRF, hashed passwords, login throttling, mandatory password changes and transactional stale-edit protection.

The stack is Python 3.13, Django 5.2 LTS, PostgreSQL, locally bundled Bootstrap and small JavaScript components. PostgreSQL is authoritative; Excel is an exchange format. All dates and deadlines use Asia/Kolkata. There is no email, Microsoft Graph, background worker or offline editing.

## Local setup

Install Python 3.13 and PostgreSQL 17. Create an empty database and a local database user, then run from this directory:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `.env`: set your PostgreSQL `DATABASE_URL`, a random `SECRET_KEY`, a strong initial administrator password and a different temporary demonstration password. Do not commit `.env`. Generate a secret using `python -c "import secrets; print(secrets.token_urlsafe(64))"`.

```powershell
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py bootstrap_app
.\.venv\Scripts\python manage.py seed_demo
.\.venv\Scripts\python manage.py collectstatic --noinput
.\.venv\Scripts\python manage.py runserver 127.0.0.1:8000 --noreload
```

Open http://127.0.0.1:8000. The initial administrator ID comes from `BOOTSTRAP_ADMIN_USERNAME`. Demonstration staff IDs are `north.operator`, `north.tech`, `north.approver`, `south.operator`, `south.tech`, and `south.approver`. Their initial password is the value of `DEMO_PASSWORD`; everyone must change it on first login. Passwords are never hard-coded in the app.

The seed creates two fictional plants, eight machines, multiple schedules, completed and outstanding PM, repair history, and running hours. It requires `DEMO_MODE=1`, refuses an existing non-demo plant directory, and does not overwrite existing demo records or passwords on repeated startup. Omit seeding when starting with an empty real configuration.

## Documentation

- [Using the app and calculation rules](docs/user-guide.md)
- [Render Free and Neon Free deployment](docs/deployment.md)
- [PostgreSQL backup and restore](docs/backup-restore.md)
- [Verification results and limitations](docs/verification.md)

## Verification commands

Use a disposable PostgreSQL development server with a user that can create test databases. `pytest` and the browser check create and remove a separate test database; do not run them concurrently against the same database configuration. Never point test configuration at production.

```powershell
.\.venv\Scripts\ruff check .
.\.venv\Scripts\python manage.py makemigrations --check --dry-run
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python scripts/browser_smoke.py
```

GitHub Actions runs PostgreSQL tests, deployment checks and Chromium acceptance tests. Browser screenshots and logs are uploaded as CI artifacts. Locally they are saved under ignored `artifacts/browser/`.

This is a demonstration deployment. Operational backups, production availability and transfer to organization-owned accounts belong to a later rollout.
