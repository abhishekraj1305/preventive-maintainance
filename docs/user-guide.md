# Using Upkeep

## Accounts and access

An administrator creates users under **Settings**, then grants each non-admin a role in one or more plants. A user may have a different role in each plant. Administrators manage all plants and configuration; workflow submissions and approvals still require the assigned, authorized person. A submitter cannot approve their own work.

Temporary passwords and administrator resets require a password change at the next login. Password reset invalidates other sessions. Five failed login attempts lock the user ID or source IP for 15 minutes. A user who forgets a password contacts an administrator; there is no email reset.

The plant selector limits the visible dashboard and lists. Server-side authorization also checks details, saves, reports, notifications and downloads, regardless of any submitted filter or URL.

## Setup and machine history

1. Add plants and their departments in Settings.
2. Create user accounts and plant memberships.
3. Add a machine with its ID, name, tonnage, department and commissioning date.
4. From its detail page add one or more named PM plans, an initial due date, interval, technician and approver.

Machine IDs are unique within a plant. Use **Active** to archive a machine while retaining its history. Location and commissioning date cannot be changed after operational history exists; archive the old record and create a new machine record for a transfer. Changing names or tonnage is audited. Disabling a plan stops new occurrences but preserves existing work.

The first PM due date is limited to ten years either side of today to bound catch-up work. Each missed cycle becomes its own task. Future occurrences appear three calendar days before their due date. The interval remains anchored to the initial due date: a January 31 monthly plan runs on February month-end, then March 31; a late completion never shifts the plan.

## PM work and reminders

The assigned technician opens a pending or rejected task, enters the actual completion time and work notes, and submits it. The assigned approver approves it or rejects it with a reason. Rejected work can be corrected and resubmitted; previous submissions and decisions remain visible in the task history.

A due date ends at midnight beginning the next day in Asia/Kolkata. Reminders begin three calendar days before that due date. The banner keeps unresolved work visible even after its notification is read. Submissions notify approvers; review decisions notify technicians.

The app reconciles schedules when authenticated users access it, including after hosting inactivity. Reminder event keys and database constraints prevent duplicates. While a page is visible it refreshes shared statuses every 30 seconds and on focus/reconnection. Timers use server timestamps and a monotonic browser clock. A connection warning means fresh status is unavailable; a save is confirmed only after the server accepts it. A stale form must be reloaded before saving.

## Breakdowns and running hours

Operators or technicians report occurrence time and description. Technicians enter repair start/end, root cause and action taken; the administrator can correct records and must identify an authorized plant technician for repair work. Repair end restores the machine and closes the incident. A completed historical incident can be entered through the expanded technician/admin form.

Only one open incident per machine is allowed. Incidents cannot overlap, occur before commissioning or in the future, or have repair timestamps out of order. Downtime starts at breakdown occurrence, including waiting time. Repair duration starts at repair start.

Operators and technicians record actual operating hours for each machine and date, from 0 through 24. Enter `0` explicitly for a non-running day. Missing rows are unknown data, not zero. There is one running-hours record per machine per day; use the existing record to correct it.

## Reports

Reports and downloads calculate on demand and share the same plant/department/machine/date filters. Presets cover today, the current week through today, or the current month through today. Custom dates are inclusive in IST. Archived machines remain available in historical reports.

| Metric | Definition |
| --- | --- |
| Machines | Distinct machine records in scope; active total is separate. |
| PM due | Scheduled task occurrences with due dates in the selected range, including completed tasks. Multiple schedules produce separate tasks. |
| PM completed | Approved occurrences in that due-date range. |
| PM pending | Pending plus rejected occurrences. |
| Awaiting approval | Submitted occurrences waiting for a decision. |
| Overdue | Unapproved occurrences whose deadline has passed; can overlap pending/awaiting counts. |
| Compliance | Approved tasks completed before their deadline / tasks whose deadlines have passed in the selected range. Approval may occur later; completion must be on time. No elapsed deadlines displays N/A. |
| Failures | Incidents whose occurrence date lies in the selected range. |
| Downtime | Incident time overlapping the selected range, clipped to restoration or current time. An overnight incident allocates time to each reporting day. |
| MTTR | Mean complete repair duration for incidents restored in the selected range. Waiting before repair is excluded. No completed repairs displays N/A. |
| MTBF | Recorded running hours / failures. Every calendar day from the later of commissioning or period start through period end must have a runtime row, including zeros. A missing day displays Insufficient data; complete data with no failures displays No failures, not infinity or zero. |

Do not add overlapping PM status totals together. A rejected overdue task appears in both pending and overdue. An incident beginning before the period can contribute downtime without increasing that period's failure count.

## Excel exchange

An administrator downloads the template from **Import**, fills its original columns and uploads an `.xlsx` file. One row describes a machine and an optional PM plan. Repeat identical machine details to add several named plans; leave PM fields blank for a machine-only row. Plant/department codes and technician/approver user IDs must already exist.

Limits: 5 MB compressed, 30 MB expanded, 1,000 data rows; formula cells are rejected. All row errors must be resolved before saving. Existing machine details must match; update them through the app first if necessary. Existing plan names are rejected instead of overwritten. The confirmation is tied to the exact latest preview; an older browser tab cannot confirm a different workbook. Commit revalidates permissions and records and rolls back the entire import on any conflict.

Filtered report exports include summary counts, machine metrics, plant/department aggregates and PM task history. Spreadsheet formula characters in text are escaped. The database remains the source of truth.
