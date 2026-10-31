from collections import defaultdict
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .access import scoped_machines, scoped
from .models import PMOccurrence, Breakdown, RuntimeLog


def midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def build_report(user, start, end, plant=None, department=None, machine=None):
    if start > end or (end - start).days > 3660:
        raise ValidationError("Choose an ordered date range of no more than ten years.")
    machines = scoped_machines(user)
    for key, value in [("plant_id", plant), ("department_id", department), ("pk", machine)]:
        if value:
            machines = machines.filter(**{key: value})
    now = timezone.now()
    today = timezone.localdate(now)
    begin, finish = midnight(start), midnight(end + timedelta(days=1))
    machine_list = list(machines)
    ids = [m.pk for m in machine_list]
    tasks = list(scoped(PMOccurrence, user).filter(machine_id__in=ids, due__range=(start, end)))
    eligible = [t for t in tasks if t.deadline <= now]
    on_time = [t for t in eligible if t.status == "approved" and t.completed_at and t.completed_at < t.deadline]
    incidents = list(
        scoped(Breakdown, user)
        .filter(machine_id__in=ids, occurred_at__lt=finish)
        .filter(Q(repair_end__isnull=True) | Q(repair_end__gte=begin))
    )
    # Also include incidents closed in the period for MTTR (full repair duration).
    runtimes = list(scoped(RuntimeLog, user).filter(machine_id__in=ids, date__range=(start, end)))
    by_machine, runtime_by_machine = defaultdict(list), defaultdict(list)
    for incident in incidents:
        by_machine[incident.machine_id].append(incident)
    for log in runtimes:
        runtime_by_machine[log.machine_id].append(log)
    rows = []
    for obj in machine_list:
        records = by_machine[obj.pk]
        logs = runtime_by_machine[obj.pk]
        failures = sum(begin <= b.occurred_at < finish for b in records)
        downtime = sum(
            max(0, (min(b.repair_end or now, finish, now) - max(b.occurred_at, begin)).total_seconds() / 3600)
            for b in records
        )
        repair_hours = [
            b.repair_hours
            for b in records
            if b.repair_end and begin <= b.repair_end < finish and b.repair_hours is not None
        ]
        required_start = max(start, obj.commissioned_on)
        required_end = min(end, today)
        expected_days = max(0, (required_end - required_start).days + 1)
        dates = {r.date for r in logs if required_start <= r.date <= required_end}
        complete = expected_days > 0 and len(dates) == expected_days and end <= today
        hours = float(sum(r.hours for r in logs))
        rows.append(
            {
                "machine": obj,
                "machine_id": obj.pk,
                "code": obj.code,
                "name": obj.name,
                "plant": obj.plant.name,
                "department": obj.department.name,
                "plant_id": obj.plant_id,
                "department_id": obj.department_id,
                "breakdowns": failures,
                "downtime_hours": round(downtime, 4),
                "runtime_hours": hours,
                "runtime_complete": complete,
                "runtime_days": len(dates),
                "expected_days": expected_days,
                "mttr": sum(repair_hours) / len(repair_hours) if repair_hours else None,
                "mtbf": hours / failures if complete and failures else None,
            }
        )
    departments, plants = {}, {}
    for row in rows:
        for target, key, name in (
            (departments, row["department_id"], f"{row['plant']} / {row['department']}"),
            (plants, row["plant_id"], row["plant"]),
        ):
            group = target.setdefault(key, {"id": key, "name": name, "breakdowns": 0, "downtime_hours": 0})
            group["breakdowns"] += row["breakdowns"]
            group["downtime_hours"] += row["downtime_hours"]
    return {
        "start": start,
        "end": end,
        "generated_at": now,
        "machine_rows": rows,
        "department_rows": list(departments.values()),
        "plant_rows": list(plants.values()),
        "machine_count": len(rows),
        "active_machine_count": sum(m.active for m in machine_list),
        "pm_due": len(tasks),
        "pm_machine_count": len({t.machine_id for t in tasks}),
        "pm_completed": sum(t.status == "approved" for t in tasks),
        "pm_pending": sum(t.status in ("pending", "rejected") for t in tasks),
        "pm_awaiting": sum(t.status == "submitted" for t in tasks),
        "pm_overdue": sum(t.status != "approved" and t.deadline <= now for t in tasks),
        "compliance": 100 * len(on_time) / len(eligible) if eligible else None,
        "compliance_numerator": len(on_time),
        "compliance_denominator": len(eligible),
        "breakdown_count": sum(r["breakdowns"] for r in rows),
        "downtime_hours": sum(r["downtime_hours"] for r in rows),
        "pm_tasks": tasks,
    }
