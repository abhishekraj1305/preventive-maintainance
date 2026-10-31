# Approved maintenance application design

Build the user-approved multi-plant preventive maintenance and breakdown app: Python 3.13, Django 5.2 LTS, PostgreSQL, Bootstrap, responsive browser UI, Asia/Kolkata time.

Individual ID/password accounts; Admin manages users and masters, Operator reports breakdowns and runtime, Technician submits PM and repairs, Approver approves/rejects. Multiple plants per user with server-enforced isolation and no self approval. Admin reset forces password change. No email, Graph, external notifications, offline writes, or photo uploads.

Machines have multiple named recurring PM plans, fixed anchor dates, day/week/month intervals, designated technician and approver. End-of-day deadlines; warning begins three days before. Preserve missed cycles and history. Rejection requires reason and permits resubmission. In-app inbox, persistent urgent banner, server-based PM/down timers, refresh every 30 seconds while visible and on reconnect. No worker required; reconcile idempotently on access.

Breakdowns: occurrence/description, repair start/end, root cause/action/technician, open/in repair/closed. One open incident per machine, no overlapping intervals, ordered times. Daily actual runtime 0..24 hours with explicit zero days. Machine history and audits preserved.

Reports: filtered daily/weekly/monthly/custom periods, unique machine counts separate from PM occurrence counts; approved on-time completed tasks divided by elapsed scheduled deadlines. Breakdown frequency, clipped downtime, MTTR for repairs closed in period, MTBF from actual runtime and incident starts (missing hours or zero failures => unavailable). Excel import preview/atomic commit and filtered exports; DB authoritative.

Private personal GitHub repository preventive-maintenance-demo, Render Free app, Neon Free DB. Free-tier cold starts accepted. Synthetic two-plant demo, secure bootstrap, health endpoint, CI, deployment and tested backup/restore instructions. Production availability and ownership transfer are later rollout.
