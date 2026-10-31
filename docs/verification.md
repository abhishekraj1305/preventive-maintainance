# Verification record — 31 October 2026

## Completed locally

- **54 tests passed** on Python 3.13.14 / Django 5.2.18 / PostgreSQL 17.11, including real simultaneous database transactions. Result: `54 passed in 5.32s`.
- Ruff lint, migration drift check and production-mode Django deployment checks passed.
- Chromium acceptance test passed at 1440px desktop and 390px mobile widths. Verified forced password change, dashboard/list/detail pages, Excel download, operator breakdown → technician restoration, another browser session's status refresh, PM submission → rejection → resubmission → approval, running-hours entry, mobile navigation and offline/reconnection indication. Timers remained correct with an intentionally incorrect device clock and stopped at restoration. No browser JavaScript errors.
- Visual inspection of desktop and mobile screenshots confirmed responsive layout, legible timers and mobile task cards.
- Two independent code reviews completed. Findings were reproduced, corrected and regression-tested: bounded schedule catch-up, historical incident entry, technician attribution, report grouping, account-reset concurrency, stale multi-tab import previews, administrator bootstrap after account retirement and rendering unassigned incidents.
- PostgreSQL backup restored into a **separate empty database**: all **25 public tables / 624 rows** matched deterministic row-content hashes. Repeating restore into that nonempty target was correctly refused.
- The first complete [GitHub Actions Linux run](https://github.com/abhishekraj1305/preventive-maintenance-demo/actions/runs/41172118940) passed every step, including PostgreSQL, production deployment checks and Chromium. Subsequent commits repeat the checks.

## Covered behavior

Tests include plant/role isolation and filtered downloads, CSRF, login throttling, administrator resets and old-session invalidation, self-approval prevention, duplicate/stale requests, concurrent PM submissions and breakdown reports, reminder deduplication, missed-cycle catch-up, calendar and month-end recurrence including leap years, end-of-day deadlines, rejection history, overnight and ongoing downtime, separate repair duration, occurrence-based compliance, missing/zero runtime, no-failure MTBF, formula-safe Excel output and atomic revalidation of imports.

## Reproducibility and remaining hosting checks

Run the commands in README and `scripts/browser_smoke.py` against a disposable PostgreSQL instance. CI repeats these checks on Linux. Local logs, screenshots and backup comparison evidence are under ignored `artifacts/`; they are not source files or credentials to publish.

The browser test verifies independent browser contexts on a real local server. Physical phones and the actual Render/Neon cold-start latency require checking the hosted URL. Local schedule catch-up and database restoration are tested; actual hosted redeployment persistence must be confirmed after deployment. Any hosting status reported at delivery takes precedence over this checklist.
