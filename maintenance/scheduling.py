from calendar import monthrange
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from .models import PMPlan, PMOccurrence, Notification


def due_date(anchor, count, unit, index):
    if count < 1 or index < 0 or unit not in ("days", "weeks", "months"):
        raise ValueError("Invalid recurring interval.")
    if unit == "months":
        total = anchor.year * 12 + anchor.month - 1 + count * index
        year, month = divmod(total, 12)
        month += 1
        return date(year, month, min(anchor.day, monthrange(year, month)[1]))
    return anchor + timedelta(days=count * index * (7 if unit == "weeks" else 1))


def notify(user_id, plant_id, key, title, body, url):
    Notification.objects.get_or_create(
        recipient_id=user_id, key=key, defaults={"plant_id": plant_id, "title": title, "body": body, "url": url}
    )


def reconcile(user, now=None):
    from .access import plant_ids

    now = now or timezone.now()
    today = timezone.localdate(now)
    horizon = today + timedelta(days=3)
    ids = plant_ids(user)
    # Serialize per-plan cursor advancement; unique(plan,due) is a second safety net.
    for plan_id in PMPlan.objects.filter(
        active=True, machine__active=True, machine__plant__active=True, machine__plant_id__in=ids
    ).values_list("pk", flat=True):
        with transaction.atomic():
            plan = (
                PMPlan.objects.select_for_update(of=("self",))
                .select_related("machine__plant", "machine__department")
                .get(pk=plan_id)
            )
            if not plan.active or not plan.machine.active or not plan.machine.plant.active:
                continue
            index = plan.next_index
            pending = []
            machine = plan.machine
            snapshot = machine.snapshot()
            while (due := due_date(plan.first_due, plan.interval, plan.unit, index)) <= horizon:
                pending.append(
                    PMOccurrence(
                        plan=plan,
                        due=due,
                        machine=machine,
                        plant_id=machine.plant_id,
                        department_id=machine.department_id,
                        snapshot=snapshot,
                        task_name=plan.name,
                        technician_id=plan.technician_id,
                        approver_id=plan.approver_id,
                    )
                )
                index += 1
            PMOccurrence.objects.bulk_create(pending, ignore_conflicts=True, batch_size=500)
            if index != plan.next_index:
                plan.next_index = index
                plan.save(update_fields=["next_index"])
    occurrences = PMOccurrence.objects.filter(plant_id__in=ids, due__lte=horizon).exclude(status="approved")
    notifications = []
    for occurrence in occurrences.select_related("machine"):
        stage = "overdue" if occurrence.due < today else "today" if occurrence.due == today else "soon"
        snapshot = occurrence.snapshot
        body = (
            f"{snapshot.get('name', occurrence.machine.name)} · {snapshot.get('tonnage', '')} T · "
            f"{snapshot.get('plant', '')} / {snapshot.get('department', '')} · Due {occurrence.due:%d %b %Y}"
        )
        notifications.append(
            Notification(
                recipient_id=occurrence.technician_id,
                plant_id=occurrence.plant_id,
                key=f"pm:{occurrence.pk}:{stage}",
                title=f"{occurrence.task_name}: {stage}",
                body=body,
                url=f"/pm/{occurrence.pk}/",
            )
        )
    Notification.objects.bulk_create(notifications, ignore_conflicts=True, batch_size=500)
