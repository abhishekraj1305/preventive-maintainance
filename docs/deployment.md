# Render Free + Neon Free deployment

Use personal accounts for this demonstration. The user selected the public personal GitHub repository `abhishekraj1305/preventive-maintainance` for this deployment. Keep all credentials and data outside source control. Do not select paid service plans, add a persistent disk or create a Render PostgreSQL instance: the database belongs in Neon.

## 1. PostgreSQL on Neon

Create a Free project named `preventive-maintenance-demo`, using PostgreSQL 17 and an AWS region close to the Render service (Singapore where available). Keep the default database or create `maintenance`. Copy the **direct**, non-pooler PostgreSQL connection string with `sslmode=require` from Connect. Treat it as a secret. Direct connections support migrations and backup/restore without pooler restrictions; this demo uses only two web workers and closes connections after requests.

## 2. GitHub and Render

Push this source to the personal repository `preventive-maintainance`. The default deployment branch is `main`. GitHub Actions should pass before deployment.

Create a Render Blueprint using `render.yaml`, or create a Web Service with these settings:

| Setting | Value |
| --- | --- |
| Repository | `abhishekraj1305/preventive-maintainance` |
| Branch | `main` |
| Runtime | Python |
| Instance | **Free** |
| Region | Singapore |
| Build | `bash scripts/build.sh` |
| Start | `bash scripts/start.sh` |
| Health check | `/health/` |
| Auto deploy | After checks pass |

Supply environment settings in Render, never in committed files:

| Variable | Value |
| --- | --- |
| `PYTHON_VERSION` | `3.13.14` |
| `DEBUG` | `0` |
| `SECRET_KEY` | Unique random value, at least 50 characters; Blueprint can generate it. |
| `DATABASE_URL` | Neon direct connection string, including required SSL settings. |
| `DEMO_MODE` | `1` |
| `SEED_DEMO` | `1` for initial setup; set to `0` after successful seeding. |
| `BOOTSTRAP_ADMIN_USERNAME` | `admin` or your chosen user ID. |
| `BOOTSTRAP_ADMIN_PASSWORD` | Unique strong temporary administrator password. |
| `DEMO_PASSWORD` | Different strong temporary password for six fictional staff accounts. |

The Render hostname is automatically allowed from `RENDER_EXTERNAL_HOSTNAME`. A custom domain requires adding it to `ALLOWED_HOSTS` and its HTTPS origin to `CSRF_TRUSTED_ORIGINS`. Do not disable HTTPS redirection for a public deployment.

Startup applies migrations, initializes the first administrator if none exists, optionally seeds an empty demonstration database, then starts Gunicorn. Existing administrators, user password changes and demo records are preserved. Once initialized, remove bootstrap passwords and `DEMO_PASSWORD` from Render settings and set `SEED_DEMO=0`. Keep the database URL and secret key.

## 3. Deployment acceptance

1. Verify `/health/` returns HTTP 200 with a database check; deployment must fail health checks if PostgreSQL is unreachable.
2. Sign in, change the temporary password and complete an operator → technician → approver workflow.
3. Use a second device to verify plant isolation and status refresh; view reports and download a filtered workbook.
4. Redeploy without changing `DATABASE_URL`; verify the saved incident, PM history and changed passwords persist.
5. After an idle cold start, verify outstanding tasks are still present and reminders are not duplicated.
6. Back up and restore a separate empty database following [backup-restore.md](backup-restore.md).

## Limits and troubleshooting

Free hosting has quotas and cold starts. The application does not run keep-alive pings or a permanent scheduler. Accessing it reconciles missed schedules, and the next login shows outstanding reminders. In-app notifications require the app to be open; there are no external alerts.

A failed migration or bootstrap stops startup; inspect deployment logs without posting secrets. If the original admin has been retired, an existing active administrator is sufficient for restart. If no active administrator remains, use a new bootstrap ID and temporary password or perform a controlled database recovery. Do not silently reactivate a retired account.

Application files and database backups stored on the Render service filesystem are ephemeral. Neon stores authoritative application data independently of deployments. Free-tier history is not an operational backup plan. This setup is for demonstration, as described by [Render Free documentation](https://render.com/docs/free) and [Neon plans](https://neon.com/docs/introduction/plans). Python version selection follows [Render's runtime documentation](https://render.com/docs/python-version).
