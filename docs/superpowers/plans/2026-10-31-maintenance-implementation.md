# Maintenance Application Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task. User has explicitly approved this design and requested implementation; no additional design approval is needed.

**Goal:** Deliver the approved working multi-plant maintenance demo and deployment package.
**Architecture:** Django monolith with server-rendered pages, authenticated JSON refresh, PostgreSQL source of truth, transactional service layer, no permanent worker.
**Tech Stack:** Python 3.13, Django 5.2 LTS, PostgreSQL, Bootstrap, openpyxl, pytest, Playwright.
**Spec:** ../specs/2026-10-31-maintenance-design.md

## Global constraints
- All user workflows and notifications are in-app; no email/Graph/push.
- Plant authorization applies to every query and mutation; workflow guards run server-side.
- Fixed schedule anchor, IST end-of-day deadlines, preserved missed occurrences.
- Free demo on Render + Neon, personal private GitHub repo; no paid resources.

## Review focus
- Cross-plant foreign-key injection and unauthorized exports/actions.
- Simultaneous updates, duplicate submissions and recurrence catch-up.
- Month end, midnight, partial reporting periods and missing runtime.
- Import previews changing between validation and commit.
- Restart/cold-start persistence and secret-free bootstrap/deployment.

### Task 1: Domain and scheduling
Files: config/settings.py; maintenance/models.py; maintenance/scheduling.py; maintenance/tests/test_domain.py.
Interfaces: due_date(anchor, count, unit, index) -> date; reconcile(user, now=None) -> None; scoped_machines(user) -> QuerySet.
- [x] Write behavior tests for recurrence dates, plant scope, notification deduplication and catch-up; run to failure.
- [x] Create models, migrations and scheduling services; run tests to green.

### Task 2: Transactional workflows and account controls
Files: maintenance/services.py; maintenance/access.py; maintenance/auth.py; maintenance/tests/test_workflows.py.
Interfaces: submit_pm(user, occurrence_id, version, completed_at, notes); review_pm(user, occurrence_id, version, decision, reason); save_breakdown(user, data, pk=None, version=None); save_runtime(user, data, pk=None, version=None).
- [x] Write failing workflow, isolation, stale-edit and validation tests.
- [x] Implement service transactions, audit, notifications, authentication and password controls; run suite.

### Task 3: Reports and workbook exchange
Files: maintenance/reporting.py; maintenance/excel.py; maintenance/tests/test_reporting.py; maintenance/tests/test_excel.py.
Interfaces: build_report(user, start, end, plant=None, department=None, machine=None) -> dict; preview_import(user, workbook) -> dict; commit_import(user, preview) -> counts.
- [x] Write hand-calculated metric/period and atomic-import tests and observe failure.
- [x] Implement filtered reports and validated workbook exchange; run suite.

### Task 4: Complete responsive application
Files: maintenance/forms.py; maintenance/views/; maintenance/urls.py; templates/; static/; maintenance/tests/test_views.py.
Interfaces: session-protected pages plus status JSON containing server_now, urgent totals and unread_count.
- [x] Test route permissions, end-to-end form workflows, account reset and bad inputs before route implementation.
- [x] Build dashboard, masters, plans, PM/approval, incidents, runtime, inbox, reports and import screens.
- [x] Verify all routes and browser behavior on desktop/mobile, including timer and connectivity states.

### Task 5: Demo and deployment
Files: management/commands/; scripts/; .github/workflows/ci.yml; render.yaml; README.md; docs/deployment.md.
- [x] Test idempotent bootstrap/seed and backup/restore on isolated database.
- [x] Implement bootstrap, fictional fixtures, runtime configuration, health endpoints, CI and setup docs.
- [x] Connect private GitHub; finish reviewable artifacts and report the hosting access blocker.
- [ ] Provision Render Free / Neon Free and verify the live hosted URL once working account controls are available.

### Task 6: Independent review and release checks
- [x] Run complete PostgreSQL tests, deployment checks, XLSX and desktop/mobile smoke tests.
- [x] Obtain fresh-context code review; address substantive issues with regression tests.
- [x] Record verified results, commit and deliver app URL or runnable local preview plus any hosting access needed.
