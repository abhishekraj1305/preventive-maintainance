from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from maintenance.models import PMOccurrence, Notification
from maintenance.scheduling import reconcile


IST = ZoneInfo("Asia/Kolkata")


def test_reminders_start_at_ist_midnight_three_calendar_days_before_due(factory):
    factory.plan.first_due = date(2026, 11, 4)
    factory.plan.save()
    boundary = datetime(2026, 11, 1, tzinfo=IST)
    reconcile(factory.tech, now=boundary - timedelta(microseconds=1))
    assert not PMOccurrence.objects.exists()
    assert not Notification.objects.exists()
    reconcile(factory.tech, now=boundary)
    occurrence = PMOccurrence.objects.get()
    assert occurrence.due == date(2026, 11, 4)
    assert list(Notification.objects.values_list("key", flat=True)) == [f"pm:{occurrence.pk}:soon"]
    reconcile(factory.tech, now=boundary + timedelta(hours=23))
    assert Notification.objects.count() == 1


def test_due_today_becomes_overdue_at_exclusive_ist_deadline(factory):
    factory.plan.first_due = date(2026, 11, 4)
    factory.plan.save()
    due_start = datetime(2026, 11, 4, tzinfo=IST)
    deadline = datetime(2026, 11, 5, tzinfo=IST)
    reconcile(factory.tech, now=due_start)
    occurrence = PMOccurrence.objects.get()
    assert occurrence.deadline == deadline
    reconcile(factory.tech, now=deadline - timedelta(microseconds=1))
    assert not Notification.objects.filter(key__endswith=":overdue").exists()
    reconcile(factory.tech, now=deadline)
    reconcile(factory.tech, now=deadline + timedelta(days=1))
    assert Notification.objects.filter(key=f"pm:{occurrence.pk}:overdue").count() == 1
    assert Notification.objects.filter(key=f"pm:{occurrence.pk}:today").count() == 1
