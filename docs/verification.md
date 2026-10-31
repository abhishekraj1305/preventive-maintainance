# Verification record — 31 October 2026

## Completed locally

- **54 tests passed** on Python 3.13.14 / Django 5.2.18 / PostgreSQL 17.11, including real simultaneous database transactions. Result: `54 passed in 5.32s`.
- Ruff lint, migration drift check and production-mode Django deployment checks passed.
- Chromium acceptance test passed at 1440px desktop and 390px mobile widths. Verified forced password change, dashboard/list/detail pages, Excel download, operator breakdown → technician restoration, another browser session's status refresh, PM submission → rejection → resubmission → approval, running-hours entry, mobile navigation and offline/reconnection indication. Timers remained correct with an intentionally incorrect device clock and stopped at restoration. No browser JavaScript errors.
- Visual inspection of desktop and mobile screenshots confirmed responsive layout, legible timers and mobile task cards.
- Two independent code reviews completed. Findings were reproduced, corrected and regression-tested: bounded schedule catch-up, historical incident entry, technician attribution, report grouping, account-reset concurrency, stale multi-tab import previews, administrator bootstrap after account retirement and rendering unassigned incidents.
- PostgreSQL backup restored into a **separate empty database**: all **25 public tables / 624 rows** matched deterministic row-content hashes. Repeating restore into that nonempty target was correctly refused.
- The deployed source passed [GitHub Actions on the selected public repository](https://github.com/abhishekraj1305/preventive-maintainance/actions/runs/41173170478), including PostgreSQL, production deployment checks and Chromium. Subsequent commits repeat the checks.

## Covered behavior

Tests include plant/role isolation and filtered downloads, CSRF, login throttling, administrator resets and old-session invalidation, self-approval prevention, duplicate/stale requests, concurrent PM submissions and breakdown reports, reminder deduplication, missed-cycle catch-up, calendar and month-end recurrence including leap years, end-of-day deadlines, rejection history, overnight and ongoing downtime, separate repair duration, occurrence-based compliance, missing/zero runtime, no-failure MTBF, formula-safe Excel output and atomic revalidation of imports.

## Hosted verification

- Render Free web service and Neon Free PostgreSQL 17 database are deployed in Singapore. HTTPS `/health/` returns `200 ok` after querying the database. Render's health-check path is `/health/`; auto-deploy waits for CI checks to pass.
- All seven seeded accounts accepted their initial credentials and enforced mandatory password changes. Secure, HttpOnly session cookies and HSTS were verified. User passwords were left unchanged for first use.
- The hosted sign-in page was checked in Chromium at 1440px desktop and 390px mobile widths: both bundled stylesheets loaded, no horizontal overflow, no JavaScript errors. Screenshots were visually inspected.
- The shared database contains two plants, eight machines, sixteen PM plans, thirty-eight PM tasks, ten breakdowns and twenty-two PM submissions. Initial bootstrap password environment values were cleared and seeding disabled after setup.
- Redeployment `dep-dbinucs9v7es7384r0dg` reached **live** with setup passwords cleared. Before/after content hashes matched for all machine, PM occurrence, breakdown and PM submission records (78 records total), and an existing authenticated session survived the restart. The health endpoint remained healthy after redeployment.

## Reproducibility and limits

Run the commands in README and `scripts/browser_smoke.py` against a disposable PostgreSQL instance. CI repeats these checks on Linux. Local logs, screenshots and backup comparison evidence are under ignored `artifacts/`; they are not source files or credentials to publish.

The full operator → technician → approver workflow is verified using independent browser contexts on a real PostgreSQL-backed local server and repeated in Linux CI. Hosted checks cover deployment, credentials, forced password changes, responsive sign-in and persistence. Physical phones and a timed Render idle cold-start were not measured. Schedule catch-up after inactivity, timer clock correction and reminder deduplication have automated coverage. Free hosting may delay the first request after inactivity.
